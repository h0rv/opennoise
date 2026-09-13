"""Command line entry points for the local app and importer."""

import argparse
import asyncio
import hashlib
import json
import os
import resource
import sys
import time
from contextlib import suppress
from datetime import datetime
from pathlib import Path

import httpx
import uvicorn

from opennoise.adapters.everynoise import QUINT_SOURCE, fetch_verified_source
from opennoise.catalog.artists import ArtistProjector
from opennoise.catalog.co_listens import ArtistCoListenProjector, ArtistCoListenRunProjector
from opennoise.catalog.musicbrainz import RecordingProjector, ReleaseGroupProjector
from opennoise.catalog.registry import ProjectorRegistry
from opennoise.db import Database
from opennoise.history.signals.publication import (
    build_historical_signal_publication,
    publish_historical_signal_publication,
)
from opennoise.ingest.jsonl import ImportOptions, import_jsonl
from opennoise.ingest.musicbrainz.release_hydration import (
    HydrationSettings,
    MusicBrainzReleaseHydrationArtifact,
    MusicBrainzReleaseTrackHydrationAdapter,
    load_representative_artifact,
    materialize_hydration_catalog,
    write_hydration_artifact,
)
from opennoise.ingest.musicbrainz.research_graph import (
    ResearchGraphBuildConfig,
    build_gate,
    build_musicbrainz_research_graph,
    evaluate_sealed_graph,
    write_research_graph,
)
from opennoise.ml.publish import publish_public_model, resolve_public_policy_id
from opennoise.models import Settings
from opennoise.models.historical import HistoricalCompatibilityReceipt
from opennoise.models.historical_signal import HistoricalSignalArtifact
from opennoise.models.pipeline import SourceLimits
from opennoise.pipeline.manifest import (
    load_download_source,
    load_reacquirable_download_sources,
    source_acquisition_status,
)
from opennoise.pipeline.runner import DeterministicPartition, PipelineOptions, run_source_pipeline
from opennoise.pipeline.source_cache import (
    SourceCacheAcquisition,
    SourceCacheLimits,
    acquire_source_cache,
    load_source_cache_receipt,
    publish_source_cache_receipt,
    restore_source_cache,
    verify_source_cache_receipt,
    write_source_cache_receipt,
)
from opennoise.serving.bootstrap import bootstrap_everynoise
from opennoise.serving.open.construction_graph import (
    OpenConstructionGraphConfig,
    build_open_construction_graph,
    publish_open_construction_graph,
)
from opennoise.serving.representative_catalog_ranking import (
    RepresentativeCatalogRankingConfig,
    RepresentativeCatalogRankingReport,
    RepresentativeCatalogRankingRepository,
    publish_representative_catalog_ranking,
    write_representative_catalog_ranking,
)
from opennoise.sources.listenbrainz import ListenBrainzIncrementalAdapter
from opennoise.sources.musicbrainz import (
    MusicBrainzArtistDumpAdapter,
    MusicBrainzRecordingDumpAdapter,
    MusicBrainzReleaseGroupDumpAdapter,
)
from opennoise.sources.registry import AdapterRegistry
from opennoise.storage import LocalObjectStore
from opennoise.taxonomy.seeds.universe import (
    build_genre_seed_universe,
    write_genre_seed_universe,
)


def _serve(args: argparse.Namespace) -> int:
    os.environ["OPENNOISE_DATABASE_PATH"] = str(args.database)
    with suppress(KeyboardInterrupt):
        uvicorn.run("opennoise.serving.app:app", host=args.host, port=args.port)
    return 0


def _ingest(args: argparse.Namespace) -> int:
    summary = asyncio.run(
        import_jsonl(
            ImportOptions(
                input_path=args.input,
                database_path=args.database,
                vault_path=args.vault,
                source_key=args.source_key,
                source_name=args.source_name,
            )
        )
    )
    sys.stdout.write(f"{summary.model_dump_json(indent=2)}\n")
    return 0


def _bootstrap(args: argparse.Namespace) -> int:
    async def run() -> str:
        source_path = args.source
        if source_path is None:
            source_path = await fetch_verified_source(QUINT_SOURCE, args.vault / "raw" / "sha256")
        summary = await bootstrap_everynoise(
            database_path=args.database,
            vault_path=args.vault,
            source_path=source_path,
        )
        return summary.model_dump_json(indent=2)

    sys.stdout.write(f"{asyncio.run(run())}\n")
    return 0


def _ingest_source(args: argparse.Namespace) -> int:
    source = load_download_source(args.manifest, args.source_id)
    registry = AdapterRegistry(
        (
            MusicBrainzArtistDumpAdapter(),
            MusicBrainzReleaseGroupDumpAdapter(),
            MusicBrainzRecordingDumpAdapter(),
            ListenBrainzIncrementalAdapter(),
        )
    )
    summary = asyncio.run(
        run_source_pipeline(
            source,
            registry,
            ProjectorRegistry(
                (
                    ArtistProjector(),
                    ReleaseGroupProjector(),
                    RecordingProjector(),
                    ArtistCoListenProjector(),
                    ArtistCoListenRunProjector(),
                )
            ),
            PipelineOptions(
                manifest_path=args.manifest,
                source_id=args.source_id,
                database_path=args.database,
                vault_path=args.vault,
                partition=DeterministicPartition(sha256_prefix=args.partition_prefix),
                limits=SourceLimits(
                    max_archive_bytes=args.max_archive_bytes,
                    max_record_bytes=args.max_record_bytes,
                    max_records=args.max_records,
                    timeout_seconds=args.timeout_seconds,
                ),
                checkpoint_every=args.checkpoint_every,
            ),
        )
    )
    sys.stdout.write(f"{summary.model_dump_json(indent=2)}\n")
    return 0


def _file_sha256(path: Path) -> str:
    """Hash exact manifest bytes before binding them into a cache receipt."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _source_cache_status(args: argparse.Namespace) -> int:
    """Report whether selected declarations may be network-acquired or need an operator."""
    statuses = tuple(
        source_acquisition_status(args.manifest, source_id) for source_id in args.source_id
    )
    sys.stdout.write(
        json.dumps([status.model_dump(mode="json") for status in statuses], indent=2) + "\n"
    )
    return 0


def _acquire_source_cache(args: argparse.Namespace) -> int:
    """Build a bounded immutable raw-input cache from network-verifiable declarations."""
    sources = load_reacquirable_download_sources(args.manifest, tuple(args.source_id))
    receipt = asyncio.run(
        acquire_source_cache(
            sources,
            acquisition=SourceCacheAcquisition(
                declared_manifest_sha256=_file_sha256(args.manifest),
                work_directory=args.work_directory,
                limits=SourceCacheLimits(
                    max_sources=args.max_sources,
                    max_total_bytes=args.max_total_bytes,
                    max_concurrency=args.max_concurrency,
                    timeout_seconds=args.timeout_seconds,
                ),
                storage_scope=args.storage_scope,
            ),
            store=LocalObjectStore(args.object_store),
        )
    )
    verify_source_cache_receipt(
        receipt,
        sources,
        declared_manifest_sha256=_file_sha256(args.manifest),
    )
    match args.storage_scope:
        case "local_vault":
            digest = write_source_cache_receipt(receipt, output=args.receipt)
            sys.stdout.write(
                json.dumps(
                    {"receipt": receipt.model_dump(mode="json"), "receipt_sha256": digest}, indent=2
                )
                + "\n"
            )
        case "portable_object_store":
            publication = publish_source_cache_receipt(
                receipt,
                output=args.receipt,
                store=LocalObjectStore(args.object_store),
            )
            sys.stdout.write(publication.model_dump_json(indent=2) + "\n")
        case _:
            raise RuntimeError(f"unknown source cache scope: {args.storage_scope}")
    return 0


def _restore_source_cache(args: argparse.Namespace) -> int:
    """Reconstruct downloader-compatible raw input paths from a supplied receipt."""
    sources = load_reacquirable_download_sources(args.manifest, tuple(args.source_id))
    receipt = load_source_cache_receipt(args.receipt)
    verify_source_cache_receipt(
        receipt,
        sources,
        declared_manifest_sha256=_file_sha256(args.manifest),
    )
    restored = asyncio.run(
        restore_source_cache(
            receipt,
            destination_root=args.destination,
            store=LocalObjectStore(args.object_store),
            max_concurrency=args.max_concurrency,
        )
    )
    sys.stdout.write(
        json.dumps([item.model_dump(mode="json") for item in restored], indent=2) + "\n"
    )
    return 0


def _hydrate_musicbrainz_releases(args: argparse.Namespace) -> int:
    """Retain a small core-metadata release/track slice, never playable media."""
    representatives, source_sha256 = load_representative_artifact(args.representatives)

    async def run() -> MusicBrainzReleaseHydrationArtifact:
        async with httpx.AsyncClient(timeout=args.timeout_seconds) as client:
            adapter = MusicBrainzReleaseTrackHydrationAdapter(
                client,
                HydrationSettings(
                    cache_directory=args.cache_directory,
                    max_genres=args.max_genres,
                    max_releases_per_seed=args.max_releases_per_seed,
                    max_attempts=args.max_attempts,
                    offline=args.offline,
                ),
                user_agent=args.user_agent,
            )
            return await adapter.hydrate(representatives, source_sha256=source_sha256)

    artifact = asyncio.run(run())
    receipt = write_hydration_artifact(
        artifact,
        output=args.output,
        store=LocalObjectStore(args.object_store),
    )
    result = {"publication": receipt.model_dump(mode="json")}
    if args.database is not None:
        result["catalog"] = materialize_hydration_catalog(
            artifact,
            database_path=args.database,
            artifact_sha256=receipt.artifact.sha256,
        ).model_dump(mode="json")
    sys.stdout.write(json.dumps(result, indent=2) + "\n")
    return 0


def _publish_public_model(args: argparse.Namespace) -> int:
    policy_id = args.policy_id
    if args.policy_source_key is not None:
        policy_id = resolve_public_policy_id(args.database, args.policy_source_key)
    summary = publish_public_model(
        args.database,
        args.artifact,
        policy_id=policy_id,
    )
    sys.stdout.write(f"{summary.model_dump_json(indent=2)}\n")
    return 0


def _publish_historical_signal_map(args: argparse.Namespace) -> int:
    """Publish the H3-only historical map without changing the public default map."""
    started = time.monotonic()
    signal = HistoricalSignalArtifact.model_validate_json(
        args.signal_artifact.read_text(encoding="utf-8")
    )
    compatibility = HistoricalCompatibilityReceipt.model_validate_json(
        args.compatibility_receipt.read_text(encoding="utf-8")
    )
    artifact = build_historical_signal_publication(signal, compatibility)
    receipt, object_write = publish_historical_signal_publication(
        artifact,
        output_path=args.output,
        store=LocalObjectStore(args.object_store),
    )
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    args.receipt.write_text(receipt.model_dump_json(indent=2) + "\n", encoding="utf-8")
    report = {
        "revision": artifact.revision,
        "source_signal_artifact_sha256": artifact.source_signal_artifact_sha256,
        "publication_receipt": receipt.model_dump(mode="json"),
        "object_write": object_write.model_dump(mode="json"),
        "quality": artifact.quality.model_dump(mode="json"),
        "signal_quality": signal.quality.model_dump(mode="json"),
        "coordinate_evaluation": signal.coordinate_evaluation.model_dump(mode="json"),
        "progressive_lods": [item.model_dump(mode="json") for item in signal.progressive_lods],
        "tile_count": len(signal.tiles),
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1_024,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    sys.stdout.write(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return 0


def _build_genre_seed_universe(args: argparse.Namespace) -> int:
    """Build the name-only H2 bridge against approved catalog databases."""
    artifact = build_genre_seed_universe(args.seed_artifact, args.catalog_databases)
    write_genre_seed_universe(artifact, args.output)
    sys.stdout.write(artifact.model_dump_json(indent=2) + "\n")
    return 0


def _build_open_construction_graph(args: argparse.Namespace) -> int:
    """Build and publish the public-only graph over every retained name seed."""
    graph = build_open_construction_graph(
        args.seed_artifact,
        args.taxonomy_artifact,
        args.public_catalog_database,
        config=OpenConstructionGraphConfig(
            expected_seed_count=args.expected_seed_count,
            max_review_anchor_degree=args.max_review_anchor_degree,
        ),
    )
    receipt, object_write = publish_open_construction_graph(
        graph, output_path=args.output, store=LocalObjectStore(args.object_store)
    )
    args.gate_report.parent.mkdir(parents=True, exist_ok=True)
    args.gate_report.write_text(receipt.gate.model_dump_json(indent=2) + "\n", encoding="utf-8")
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    args.receipt.write_text(receipt.model_dump_json(indent=2) + "\n", encoding="utf-8")
    sys.stdout.write(
        json.dumps(
            {
                "logical_output_sha256": graph.output_sha256,
                "receipt": receipt.model_dump(mode="json"),
                "object_write": object_write.model_dump(mode="json"),
                "coverage": graph.coverage.model_dump(mode="json"),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    return 0


def _build_musicbrainz_research_graph(args: argparse.Namespace) -> int:
    """Build a local-only graph from name seeds and direct MusicBrainz evidence."""
    graph = build_musicbrainz_research_graph(
        args.coverage,
        args.reconstruction_inputs,
        args.research_database,
        config=ResearchGraphBuildConfig(
            expected_genre_count=args.expected_genre_count,
            max_neighbors=args.max_neighbors,
            landscape_iterations=args.landscape_iterations,
        ),
    )
    byte_sha = write_research_graph(args.output, graph)
    gate = build_gate(graph)
    args.gate_report.parent.mkdir(parents=True, exist_ok=True)
    args.gate_report.write_text(gate.model_dump_json(indent=2) + "\n", encoding="utf-8")
    sys.stdout.write(
        json.dumps(
            {
                "logical_output_sha256": graph.output_sha256,
                "written_byte_sha256": byte_sha,
                "quality": graph.quality.model_dump(mode="json"),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    return 0


def _evaluate_musicbrainz_research_graph(args: argparse.Namespace) -> int:
    """Run the read-only topology benchmark only after graph hash verification."""
    report = evaluate_sealed_graph(
        args.graph,
        args.historical_benchmark,
        expected_graph_sha256=args.expected_graph_sha256,
        neighbor_count=args.neighbor_count,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
    sys.stdout.write(report.model_dump_json(indent=2) + "\n")
    return 0


def _build_representative_catalog_candidates(args: argparse.Namespace) -> int:
    """Rank evidence-backed release-group candidates without audio or audience inputs."""
    database = Database(args.database)
    database.initialize()
    config = RepresentativeCatalogRankingConfig(
        max_genres=args.max_genres,
        max_candidates_per_genre=args.max_candidates_per_genre,
        minimum_direct_source_families=args.minimum_direct_source_families,
    )
    with database.connect() as connection:
        artifact, replayed = RepresentativeCatalogRankingRepository(connection).build(
            run_ref=args.run_ref,
            genre_ids=args.genre_id,
            config=config,
            policy_id=args.policy_id,
            generated_at=args.generated_at,
        )
        connection.commit()
    digest, size = write_representative_catalog_ranking(artifact, args.output)
    publication = publish_representative_catalog_ranking(
        args.output, LocalObjectStore(args.object_store)
    )
    report = RepresentativeCatalogRankingReport(
        artifact_sha256=digest,
        artifact_byte_size=size,
        publication=publication,
        replayed=replayed,
    )
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
    sys.stdout.write(report.model_dump_json(indent=2) + "\n")
    return 0


def parser() -> argparse.ArgumentParser:  # noqa: PLR0915
    """Build the command line parser."""
    settings = Settings()
    command_parser = argparse.ArgumentParser(prog="opennoise")
    commands = command_parser.add_subparsers(dest="command", required=True)
    serve = commands.add_parser("serve", help="run the local web app")
    serve.add_argument("--host", default=settings.host)
    serve.add_argument("--port", type=int, default=settings.port)
    serve.add_argument(
        "--database",
        type=Path,
        default=settings.database_path,
    )
    serve.set_defaults(handler=_serve)
    ingest = commands.add_parser("ingest", help="import local JSONL metadata")
    ingest.add_argument("input", type=Path)
    ingest.add_argument("--source-key", required=True)
    ingest.add_argument("--source-name", required=True)
    ingest.add_argument(
        "--database",
        type=Path,
        default=settings.database_path,
    )
    ingest.add_argument("--vault", type=Path, default=settings.vault_path)
    ingest.set_defaults(handler=_ingest)
    bootstrap = commands.add_parser(
        "bootstrap-everynoise", help="load the pinned Every Noise genre map"
    )
    bootstrap.add_argument("--source", type=Path)
    bootstrap.add_argument("--database", type=Path, default=settings.database_path)
    bootstrap.add_argument("--vault", type=Path, default=settings.vault_path)
    bootstrap.set_defaults(handler=_bootstrap)
    ingest_source = commands.add_parser(
        "ingest-source", help="download and ingest a pinned manifest source"
    )
    ingest_source.add_argument("source_id")
    ingest_source.add_argument("--manifest", type=Path, default=Path("config/data_sources.toml"))
    ingest_source.add_argument("--database", type=Path, default=settings.database_path)
    ingest_source.add_argument("--vault", type=Path, default=settings.vault_path)
    ingest_source.add_argument("--partition-prefix", default="")
    ingest_source.add_argument("--max-archive-bytes", type=int, default=4 * 1024 * 1024 * 1024)
    ingest_source.add_argument("--max-record-bytes", type=int, default=64 * 1024 * 1024)
    ingest_source.add_argument("--max-records", type=int, default=10_000_000)
    ingest_source.add_argument("--timeout-seconds", type=float, default=6 * 60 * 60)
    ingest_source.add_argument("--checkpoint-every", type=int, default=10_000)
    ingest_source.set_defaults(handler=_ingest_source)
    source_cache_status = commands.add_parser(
        "source-cache-status",
        help="report whether selected raw sources are network-verifiable or operator-supplied",
    )
    source_cache_status.add_argument("source_id", nargs="+")
    source_cache_status.add_argument(
        "--manifest", type=Path, default=Path("config/data_sources.toml")
    )
    source_cache_status.set_defaults(handler=_source_cache_status)
    acquire_cache = commands.add_parser(
        "acquire-source-cache",
        help="acquire bounded, pinned public metadata into a content-addressed object store",
    )
    acquire_cache.add_argument("source_id", nargs="+")
    acquire_cache.add_argument("--manifest", type=Path, default=Path("config/data_sources.toml"))
    acquire_cache.add_argument("--object-store", required=True, type=Path)
    acquire_cache.add_argument("--work-directory", required=True, type=Path)
    acquire_cache.add_argument("--receipt", required=True, type=Path)
    acquire_cache.add_argument("--max-sources", type=int, default=8)
    acquire_cache.add_argument("--max-total-bytes", type=int, default=128 * 1024 * 1024)
    acquire_cache.add_argument("--max-concurrency", type=int, default=2)
    acquire_cache.add_argument("--timeout-seconds", type=float, default=120.0)
    acquire_cache.add_argument(
        "--storage-scope",
        choices=("local_vault", "portable_object_store"),
        default="local_vault",
    )
    acquire_cache.set_defaults(handler=_acquire_source_cache)
    restore_cache = commands.add_parser(
        "restore-source-cache",
        help="restore a receipt's raw source cache without network access",
    )
    restore_cache.add_argument("source_id", nargs="+")
    restore_cache.add_argument("--manifest", type=Path, default=Path("config/data_sources.toml"))
    restore_cache.add_argument("--object-store", required=True, type=Path)
    restore_cache.add_argument("--receipt", required=True, type=Path)
    restore_cache.add_argument("--destination", required=True, type=Path)
    restore_cache.add_argument("--max-concurrency", type=int, default=2)
    restore_cache.set_defaults(handler=_restore_source_cache)
    hydrate = commands.add_parser(
        "hydrate-musicbrainz-releases",
        help=(
            "hydrate a bounded metadata-only release, medium, and track slice; "
            "tracks are not playable media"
        ),
    )
    hydrate.add_argument("--representatives", type=Path, required=True)
    hydrate.add_argument("--output", type=Path, required=True)
    hydrate.add_argument("--object-store", type=Path, required=True)
    hydrate.add_argument("--cache-directory", type=Path, required=True)
    hydrate.add_argument("--user-agent", required=True)
    hydrate.add_argument("--max-genres", type=int, default=20)
    hydrate.add_argument("--max-releases-per-seed", type=int, default=1)
    hydrate.add_argument("--max-attempts", type=int, default=3)
    hydrate.add_argument("--timeout-seconds", type=float, default=30.0)
    hydrate.add_argument("--offline", action="store_true")
    hydrate.add_argument("--database", type=Path)
    hydrate.set_defaults(handler=_hydrate_musicbrainz_releases)
    representatives = commands.add_parser(
        "build-representative-catalog-candidates",
        help=(
            "rank bounded release-group representative candidates from direct metadata evidence; "
            "never uses audio, streams, listeners, popularity, or quality data"
        ),
    )
    representatives.add_argument("--database", type=Path, default=settings.database_path)
    representatives.add_argument("--run-ref", required=True)
    representatives.add_argument("--policy-id", required=True, type=int)
    representatives.add_argument("--generated-at", required=True, type=datetime.fromisoformat)
    representatives.add_argument("--genre-id", action="append", type=int, default=[])
    representatives.add_argument("--max-genres", type=int, default=100)
    representatives.add_argument("--max-candidates-per-genre", type=int, default=20)
    representatives.add_argument("--minimum-direct-source-families", type=int, default=1)
    representatives.add_argument("--output", required=True, type=Path)
    representatives.add_argument("--object-store", required=True, type=Path)
    representatives.add_argument("--report", required=True, type=Path)
    representatives.set_defaults(handler=_build_representative_catalog_candidates)
    publish_model = commands.add_parser(
        "publish-public-model",
        help="verify and publish a public graph artifact",
    )
    publish_model.add_argument("artifact", type=Path)
    publish_model.add_argument("--database", type=Path, default=settings.database_path)
    policy = publish_model.add_mutually_exclusive_group(required=True)
    policy.add_argument("--policy-id", type=int)
    policy.add_argument("--policy-source-key")
    publish_model.set_defaults(handler=_publish_public_model)
    publish_historical = commands.add_parser(
        "publish-historical-signal-map",
        help="seal a 6,291-node H3-only historical map for explicit local opt-in",
    )
    publish_historical.add_argument("--signal-artifact", type=Path, required=True)
    publish_historical.add_argument("--compatibility-receipt", type=Path, required=True)
    publish_historical.add_argument("--output", type=Path, required=True)
    publish_historical.add_argument("--object-store", type=Path, required=True)
    publish_historical.add_argument("--receipt", type=Path, required=True)
    publish_historical.add_argument("--report", type=Path, required=True)
    publish_historical.set_defaults(handler=_publish_historical_signal_map)
    seed_universe = commands.add_parser(
        "build-genre-seed-universe",
        help="resolve retained H2 names against approved catalog SQLite databases",
    )
    seed_universe.add_argument("--seed-artifact", type=Path, required=True)
    seed_universe.add_argument(
        "--catalog-database",
        "--database",
        dest="catalog_databases",
        type=Path,
        action="append",
        required=True,
        help="approved public or local-research catalog database; repeatable",
    )
    seed_universe.add_argument("--output", type=Path, required=True)
    seed_universe.set_defaults(handler=_build_genre_seed_universe)
    open_graph = commands.add_parser(
        "build-open-construction-graph",
        help="build and publish a public-only graph over all retained name seeds",
    )
    open_graph.add_argument("--seed-artifact", type=Path, required=True)
    open_graph.add_argument("--taxonomy-artifact", type=Path, required=True)
    open_graph.add_argument("--public-catalog-database", type=Path, required=True)
    open_graph.add_argument("--output", type=Path, required=True)
    open_graph.add_argument("--object-store", type=Path, required=True)
    open_graph.add_argument("--receipt", type=Path, required=True)
    open_graph.add_argument("--gate-report", type=Path, required=True)
    open_graph.add_argument("--expected-seed-count", type=int, default=6291)
    open_graph.add_argument("--max-review-anchor-degree", type=int, default=24)
    open_graph.set_defaults(handler=_build_open_construction_graph)
    research_graph = commands.add_parser(
        "build-musicbrainz-research-graph",
        help="build a sealed local-only MusicBrainz name-seed research graph",
    )
    research_graph.add_argument("--coverage", type=Path, required=True)
    research_graph.add_argument("--reconstruction-inputs", type=Path, required=True)
    research_graph.add_argument("--research-database", type=Path, required=True)
    research_graph.add_argument("--output", type=Path, required=True)
    research_graph.add_argument("--gate-report", type=Path, required=True)
    research_graph.add_argument("--expected-genre-count", type=int, default=724)
    research_graph.add_argument("--max-neighbors", type=int, default=12)
    research_graph.add_argument("--landscape-iterations", type=int, default=80)
    research_graph.set_defaults(handler=_build_musicbrainz_research_graph)
    evaluate_research_graph = commands.add_parser(
        "evaluate-musicbrainz-research-graph",
        help="compare a sealed local graph against historical topology only",
    )
    evaluate_research_graph.add_argument("--graph", type=Path, required=True)
    evaluate_research_graph.add_argument("--expected-graph-sha256", required=True)
    evaluate_research_graph.add_argument("--historical-benchmark", type=Path, required=True)
    evaluate_research_graph.add_argument("--output", type=Path, required=True)
    evaluate_research_graph.add_argument("--neighbor-count", type=int, default=10)
    evaluate_research_graph.set_defaults(handler=_evaluate_musicbrainz_research_graph)
    return command_parser


def main() -> int:  # noqa: C901, PLR0911, PLR0912
    """Run the selected command."""
    args = parser().parse_args()
    match args.command:
        case "serve":
            return _serve(args)
        case "ingest":
            return _ingest(args)
        case "bootstrap-everynoise":
            return _bootstrap(args)
        case "ingest-source":
            return _ingest_source(args)
        case "source-cache-status":
            return _source_cache_status(args)
        case "acquire-source-cache":
            return _acquire_source_cache(args)
        case "restore-source-cache":
            return _restore_source_cache(args)
        case "hydrate-musicbrainz-releases":
            return _hydrate_musicbrainz_releases(args)
        case "build-representative-catalog-candidates":
            return _build_representative_catalog_candidates(args)
        case "publish-public-model":
            return _publish_public_model(args)
        case "publish-historical-signal-map":
            return _publish_historical_signal_map(args)
        case "build-genre-seed-universe":
            return _build_genre_seed_universe(args)
        case "build-open-construction-graph":
            return _build_open_construction_graph(args)
        case "build-musicbrainz-research-graph":
            return _build_musicbrainz_research_graph(args)
        case "evaluate-musicbrainz-research-graph":
            return _evaluate_musicbrainz_research_graph(args)
        case _:
            raise RuntimeError(f"unknown command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
"""Command line entry points for the local app and importer."""
