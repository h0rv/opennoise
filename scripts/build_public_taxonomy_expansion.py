"""Build and publish a factual-and-review-separated CC0 taxonomy expansion."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from opennoise.serving.public.taxonomy_expansion import (
    PublicTaxonomyExpansionConfig,
    build_public_taxonomy_expansion,
    publish_public_taxonomy_expansion,
)
from opennoise.storage import LocalObjectStore


def main() -> None:
    """Parse explicit paths and write a gated, immutable public graph artifact."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--taxonomy-artifact", type=Path, required=True)
    parser.add_argument("--public-catalog-database", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--object-store", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--expected-legacy-seed-count", type=int, default=6291)
    arguments = parser.parse_args()
    artifact = build_public_taxonomy_expansion(
        arguments.taxonomy_artifact,
        arguments.public_catalog_database,
        config=PublicTaxonomyExpansionConfig(
            expected_legacy_seed_count=arguments.expected_legacy_seed_count
        ),
    )
    receipt, _ = publish_public_taxonomy_expansion(
        artifact,
        output_path=arguments.output,
        store=LocalObjectStore(arguments.object_store),
    )
    arguments.receipt.parent.mkdir(parents=True, exist_ok=True)
    arguments.receipt.write_text(receipt.model_dump_json(indent=2) + "\n", encoding="utf-8")
    sys.stdout.write(receipt.model_dump_json(indent=2) + "\n")


if __name__ == "__main__":
    main()
