"""Restore one hash-locked catalog snapshot for a lineage-bound downstream build."""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

from musix.serving.catalog_snapshot import CatalogSnapshotRestoreError, restore_catalog_snapshot


def main() -> int:
    """Restore source bytes, verify their catalog contract, and write a receipt."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--expected-taxonomy-catalog-sha256", required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    arguments = parser.parse_args()
    try:
        receipt = restore_catalog_snapshot(
            arguments.source,
            arguments.destination,
            expected_taxonomy_catalog_sha256=arguments.expected_taxonomy_catalog_sha256,
        )
    except (CatalogSnapshotRestoreError, OSError, sqlite3.Error) as error:
        sys.stderr.write(f"catalog snapshot restoration failed: {error}\n")
        return 2
    arguments.receipt.parent.mkdir(parents=True, exist_ok=True)
    arguments.receipt.write_text(receipt.model_dump_json(indent=2) + "\n", encoding="utf-8")
    sys.stdout.write(receipt.model_dump_json(indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
