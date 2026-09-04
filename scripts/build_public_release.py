"""Build the qualified public serving release from the sealed local cache."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from musix.pipeline.public_release import PublicReleaseSettings, build_public_release


def main() -> int:
    """Run the cache-only Phase 3 publication command."""
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--release-directory",
        type=Path,
        default=Path("config/releases/phase3-public-20260831"),
    )
    parser.add_argument(
        "--cache-database",
        type=Path,
        default=Path("data/phase3-public-qualified.sqlite"),
    )
    parser.add_argument("--serving-database", type=Path, default=Path("data/public.sqlite"))
    parser.add_argument(
        "--model-output", type=Path, default=Path("data/model/phase3-public-model.json")
    )
    parser.add_argument(
        "--receipt-output", type=Path, default=Path("data/release/phase3-public-receipt.json")
    )
    parser.add_argument("--max-direct-memberships", type=int, default=100_000)
    parser.add_argument("--max-artist-pairs", type=int, default=250_000)
    parser.add_argument("--max-metadata-candidates", type=int, default=100_000)
    parser.add_argument("--neighbors-per-genre", type=int, default=25)
    arguments = parser.parse_args()
    settings = PublicReleaseSettings(
        release_directory=arguments.release_directory,
        cache_database=arguments.cache_database,
        serving_database=arguments.serving_database,
        model_output=arguments.model_output,
        receipt_output=arguments.receipt_output,
        max_direct_memberships=arguments.max_direct_memberships,
        max_artist_pairs=arguments.max_artist_pairs,
        max_metadata_candidates=arguments.max_metadata_candidates,
        neighbors_per_genre=arguments.neighbors_per_genre,
    )
    result = build_public_release(settings)
    sys.stdout.write(f"{result.model_dump_json(indent=2)}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
