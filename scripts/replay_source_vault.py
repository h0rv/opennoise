"""Verify and restore raw source objects for a release manifest."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from opennoise.pipeline.source_vault_replay import (
    SourceVaultReplayError,
    load_report,
    replay_listenbrainz_source_vault_to_candidate_database,
    replay_source_vault_to_candidate_database,
    restore_source_vault,
    verify_source_vault,
    write_candidate_database_report,
    write_report,
)
from opennoise.storage import LocalObjectStore


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    verify = subparsers.add_parser("verify")
    verify.add_argument("--manifest", type=Path, required=True)
    verify.add_argument("--vault", type=Path, required=True)
    verify.add_argument("--report", type=Path, required=True)
    verify.add_argument("--object-store", type=Path)
    restore = subparsers.add_parser("restore")
    restore.add_argument("--manifest", type=Path, required=True)
    restore.add_argument("--report", type=Path, required=True)
    restore.add_argument("--object-store", type=Path, required=True)
    restore.add_argument("--destination", type=Path, required=True)
    candidate = subparsers.add_parser("candidate-database")
    candidate.add_argument("--manifest", type=Path, required=True)
    candidate.add_argument("--report", type=Path, required=True)
    candidate.add_argument("--vault", type=Path, required=True)
    candidate.add_argument("--candidate-database", type=Path, required=True)
    candidate.add_argument("--replay-report", type=Path, required=True)
    candidate_listenbrainz = subparsers.add_parser("candidate-listenbrainz-database")
    candidate_listenbrainz.add_argument("--manifest", type=Path, required=True)
    candidate_listenbrainz.add_argument("--report", type=Path, required=True)
    candidate_listenbrainz.add_argument("--vault", type=Path, required=True)
    candidate_listenbrainz.add_argument("--candidate-database", type=Path, required=True)
    candidate_listenbrainz.add_argument("--replay-report", type=Path, required=True)
    candidate_listenbrainz.add_argument("--source-manifest", type=Path, required=True)
    return parser


def main() -> int:
    """Run one source-vault verification or restore operation."""
    arguments = _parser().parse_args()
    try:
        if arguments.command == "verify":
            store = LocalObjectStore(arguments.object_store) if arguments.object_store else None
            report = verify_source_vault(arguments.manifest, arguments.vault, object_store=store)
            write_report(report, arguments.report)
            sys.stdout.write(f"{report.model_dump_json(indent=2)}\n")
        elif arguments.command == "restore":
            restore_source_vault(
                load_report(arguments.report),
                LocalObjectStore(arguments.object_store),
                arguments.destination,
                manifest_path=arguments.manifest,
            )
            sys.stdout.write(f"restored {arguments.report} to {arguments.destination}\n")
        elif arguments.command == "candidate-database":
            candidate = replay_source_vault_to_candidate_database(
                load_report(arguments.report),
                arguments.vault,
                arguments.candidate_database,
                manifest_path=arguments.manifest,
            )
            write_candidate_database_report(candidate, arguments.replay_report)
            sys.stdout.write(f"{candidate.model_dump_json(indent=2)}\n")
        else:
            candidate = replay_listenbrainz_source_vault_to_candidate_database(
                load_report(arguments.report),
                arguments.vault,
                arguments.candidate_database,
                manifest_path=arguments.manifest,
                source_manifest_path=arguments.source_manifest,
            )
            write_candidate_database_report(candidate, arguments.replay_report)
            sys.stdout.write(f"{candidate.model_dump_json(indent=2)}\n")
    except SourceVaultReplayError as error:
        sys.stderr.write(f"source vault replay failed: {error}\n")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
