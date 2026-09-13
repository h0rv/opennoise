"""Build a public-only, non-membership taxonomy anchor artifact for legacy names."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from opennoise.taxonomy.seeds.taxonomy import (
    PublicTaxonomyConfig,
    build_genre_seed_public_taxonomy,
    write_genre_seed_public_taxonomy,
)


def main() -> int:
    """Build and write one deterministic public taxonomy expansion artifact."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed-artifact", type=Path, required=True)
    parser.add_argument("--public-catalog-database", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-seed-count", type=int, default=6291)
    parser.add_argument("--max-ancestor-depth", type=int, default=3)
    arguments = parser.parse_args()
    try:
        artifact = build_genre_seed_public_taxonomy(
            arguments.seed_artifact,
            arguments.public_catalog_database,
            config=PublicTaxonomyConfig(
                expected_seed_count=arguments.expected_seed_count,
                max_ancestor_depth=arguments.max_ancestor_depth,
            ),
        )
        byte_sha = write_genre_seed_public_taxonomy(artifact, arguments.output)
    except (OSError, ValueError) as error:
        sys.stderr.write(f"public seed taxonomy build failed: {error}\n")
        return 2
    sys.stdout.write(
        f"logical output sha256: {artifact.output_sha256}\n"
        f"written byte sha256: {byte_sha}\n"
        f"coverage: {artifact.coverage.model_dump_json()}\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
