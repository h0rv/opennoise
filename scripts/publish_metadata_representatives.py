"""Persist a verified metadata-example artifact in any compatible object store."""

from __future__ import annotations

import argparse
from pathlib import Path

from opennoise.serving.metadata.representative_publication import publish_metadata_representatives
from opennoise.storage import LocalObjectStore


def main() -> int:
    """Parse local paths and emit one deterministic publication receipt."""
    parser = argparse.ArgumentParser()
    parser.add_argument("artifact", type=Path)
    parser.add_argument("--catalog-database", type=Path, required=True)
    parser.add_argument("--object-store", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    receipt = publish_metadata_representatives(
        arguments.artifact,
        LocalObjectStore(arguments.object_store),
        arguments.catalog_database,
    )
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(receipt.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
