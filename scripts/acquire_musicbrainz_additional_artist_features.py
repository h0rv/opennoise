"""Acquire a disjoint native artist feature expansion with fixed hash stratification."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

import httpx

from opennoise.catalog.musicbrainz_bulk_artist_features import acquire_additional_artist_features
from opennoise.catalog.musicbrainz_open_features import verify_open_artist_features


def _progress(done: int, total: int) -> None:
    if done % 1000 == 0 or done == total:
        sys.stderr.write(f"additional native artist metadata: {done}/{total}\n")
        sys.stderr.flush()


async def _acquire(args: argparse.Namespace) -> dict[str, object]:
    async with httpx.AsyncClient(timeout=30.0) as client:
        return await acquire_additional_artist_features(
            catalog_directory=args.catalog_directory,
            existing_feature_directory=args.existing_feature_directory,
            directory=args.output_directory,
            client=client,
            user_agent="OpenNoise/0.1 (bounded local noncommercial research; https://github.com/h0rv/opennoise)",
            artist_limit=args.limit,
            progress=_progress,
        )


def main() -> int:
    """Create new retained pages or verify the complete projection offline."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog-directory", type=Path, required=True)
    parser.add_argument("--existing-feature-directory", type=Path, required=True)
    parser.add_argument("--output-directory", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=15000)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    result = (
        verify_open_artist_features(directory=args.output_directory)
        if args.verify_only
        else asyncio.run(_acquire(args))
    )
    sys.stdout.write(json.dumps(result, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
