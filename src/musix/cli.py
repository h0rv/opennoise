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
    return command_parser


def main() -> int:  # noqa: PLR0911
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
        case "publish-public-model":
            return _publish_public_model(args)
        case "publish-historical-signal-map":
            return _publish_historical_signal_map(args)
        case "build-genre-seed-universe":
            return _build_genre_seed_universe(args)
        case _:
            raise RuntimeError(f"unknown command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
"""Command line entry points for the local app and importer."""
