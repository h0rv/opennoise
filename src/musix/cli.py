"""Command line entry points for the local app and importer."""

import argparse
import asyncio
import json
import os
import resource
import sys
import time
from contextlib import suppress
from pathlib import Path

import httpx
import uvicorn

from musix.adapters.everynoise import QUINT_SOURCE, fetch_verified_source
from musix.bootstrap import bootstrap_everynoise
from musix.catalog.artists import ArtistProjector
from musix.catalog.co_listens import ArtistCoListenProjector, ArtistCoListenRunProjector
from musix.catalog.musicbrainz import RecordingProjector, ReleaseGroupProjector
from musix.catalog.registry import ProjectorRegistry
from musix.genre_seed_universe import build_genre_seed_universe, write_genre_seed_universe
from musix.historical_signal_publication import (
    build_historical_signal_publication,
    publish_historical_signal_publication,
)
from musix.ingest import ImportOptions, import_jsonl
from musix.ml.publish import publish_public_model, resolve_public_policy_id
from musix.models import Settings
from musix.models.historical import HistoricalCompatibilityReceipt
from musix.models.historical_signal import HistoricalSignalArtifact
from musix.models.pipeline import SourceLimits
from musix.musicbrainz_release_hydration import (
    HydrationSettings,
    MusicBrainzReleaseHydrationArtifact,
    MusicBrainzReleaseTrackHydrationAdapter,
    load_representative_artifact,
    materialize_hydration_catalog,
    write_hydration_artifact,
)
from musix.musicbrainz_research_graph import (
    ResearchGraphBuildConfig,
    build_gate,
    build_musicbrainz_research_graph,
    evaluate_sealed_graph,
    write_research_graph,
)
from musix.pipeline.manifest import load_download_source
from musix.pipeline.runner import DeterministicPartition, PipelineOptions, run_source_pipeline
from musix.sources.listenbrainz import ListenBrainzIncrementalAdapter
from musix.sources.musicbrainz import (
    MusicBrainzArtistDumpAdapter,
    MusicBrainzRecordingDumpAdapter,
    MusicBrainzReleaseGroupDumpAdapter,
)
from musix.sources.registry import AdapterRegistry
from musix.storage import LocalObjectStore


def _serve(args: argparse.Namespace) -> int:
    os.environ["MUSIX_DATABASE_PATH"] = str(args.database)
    with suppress(KeyboardInterrupt):
        uvicorn.run("musix.app:app", host=args.host, port=args.port)
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


def parser() -> argparse.ArgumentParser:  # noqa: PLR0915
    """Build the command line parser."""
    settings = Settings()
    command_parser = argparse.ArgumentParser(prog="musix")
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


def main() -> int:  # noqa: C901, PLR0911
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
        case "hydrate-musicbrainz-releases":
            return _hydrate_musicbrainz_releases(args)
        case "publish-public-model":
            return _publish_public_model(args)
        case "publish-historical-signal-map":
            return _publish_historical_signal_map(args)
        case "build-genre-seed-universe":
            return _build_genre_seed_universe(args)
        case "build-musicbrainz-research-graph":
            return _build_musicbrainz_research_graph(args)
        case "evaluate-musicbrainz-research-graph":
            return _evaluate_musicbrainz_research_graph(args)
        case _:
            raise RuntimeError(f"unknown command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
"""Command line entry points for the local app and importer."""
