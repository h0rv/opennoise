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
from musix.ingest import ImportOptions, import_jsonl
from musix.models import Settings


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
        case _:
            raise RuntimeError(f"unknown command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
"""Command line entry points for the local app and importer."""
