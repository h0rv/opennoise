"""Command line entry points for the local app and importer."""

import argparse
import asyncio
import os
import sys
from contextlib import suppress
from pathlib import Path

import uvicorn

from musix.adapters.everynoise import QUINT_SOURCE, fetch_verified_source
from musix.bootstrap import bootstrap_everynoise
from musix.catalog.artists import ArtistProjector
from musix.catalog.registry import ProjectorRegistry
from musix.ingest import ImportOptions, import_jsonl
from musix.models import Settings
from musix.models.pipeline import SourceLimits
from musix.pipeline.manifest import load_download_source
from musix.pipeline.runner import DeterministicPartition, PipelineOptions, run_source_pipeline
from musix.sources.musicbrainz import MusicBrainzArtistDumpAdapter
from musix.sources.registry import AdapterRegistry


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
    registry = AdapterRegistry((MusicBrainzArtistDumpAdapter(),))
    summary = asyncio.run(
        run_source_pipeline(
            source,
            registry,
            ProjectorRegistry((ArtistProjector(),)),
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


def parser() -> argparse.ArgumentParser:
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
    ingest_source.add_argument("--partition-prefix", default="0")
    ingest_source.add_argument("--max-archive-bytes", type=int, default=4 * 1024 * 1024 * 1024)
    ingest_source.add_argument("--max-record-bytes", type=int, default=64 * 1024 * 1024)
    ingest_source.add_argument("--max-records", type=int, default=10_000_000)
    ingest_source.add_argument("--timeout-seconds", type=float, default=6 * 60 * 60)
    ingest_source.add_argument("--checkpoint-every", type=int, default=10_000)
    ingest_source.set_defaults(handler=_ingest_source)
    return command_parser


def main() -> int:
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
        case _:
            raise RuntimeError(f"unknown command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
"""Command line entry points for the local app and importer."""
