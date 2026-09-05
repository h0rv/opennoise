"""Export, verify, or restore a portable cache-only public-release custody bundle."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from musix.pipeline.public_release_bundle import (
    PublicReleaseBundleDestinations,
    PublicReleaseBundleError,
    export_public_release_bundle,
    restore_public_release_bundle,
    verify_public_release_bundle,
)
from musix.storage import LocalObjectStore, ObjectKey


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    subcommands = parser.add_subparsers(dest="command", required=True)
    export = subcommands.add_parser("export")
    export.add_argument("--custody-receipt", type=Path, required=True)
    export.add_argument("--release-directory", type=Path, required=True)
    export.add_argument("--custody-store", type=Path, required=True)
    export.add_argument("--bundle-store", type=Path, required=True)
    verify = subcommands.add_parser("verify")
    verify.add_argument("--bundle-store", type=Path, required=True)
    verify.add_argument("--receipt-key", required=True)
    restore = subcommands.add_parser("restore")
    restore.add_argument("--bundle-store", type=Path, required=True)
    restore.add_argument("--receipt-key", required=True)
    restore.add_argument("--cache-database", type=Path, required=True)
    restore.add_argument("--release-directory", type=Path, required=True)
    restore.add_argument("--evidence-directory", type=Path, required=True)
    restore.add_argument("--objective-gates-directory", type=Path, required=True)
    restore.add_argument("--custody-receipt", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    """Run one explicit cache-only bundle operation."""
    arguments = _arguments()
    try:
        if arguments.command == "export":
            receipt, key = export_public_release_bundle(
                custody_receipt_path=arguments.custody_receipt,
                release_directory=arguments.release_directory,
                custody_store=LocalObjectStore(arguments.custody_store),
                bundle_store=LocalObjectStore(arguments.bundle_store),
            )
            sys.stdout.write(f"{receipt.model_dump_json(indent=2)}\nreceipt_key={key.value}\n")
        elif arguments.command == "verify":
            receipt = verify_public_release_bundle(
                LocalObjectStore(arguments.bundle_store), ObjectKey(value=arguments.receipt_key)
            )
            sys.stdout.write(f"{receipt.model_dump_json(indent=2)}\n")
        else:
            restored = restore_public_release_bundle(
                store=LocalObjectStore(arguments.bundle_store),
                receipt_key=ObjectKey(value=arguments.receipt_key),
                destinations=PublicReleaseBundleDestinations(
                    cache_database=arguments.cache_database,
                    release_directory=arguments.release_directory,
                    evidence_directory=arguments.evidence_directory,
                    objective_gates_directory=arguments.objective_gates_directory,
                    custody_receipt=arguments.custody_receipt,
                ),
            )
            sys.stdout.write(f"{restored.receipt.model_dump_json(indent=2)}\n")
    except (PublicReleaseBundleError, ValueError) as error:
        raise SystemExit(f"public release bundle failed: {error}") from error
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
