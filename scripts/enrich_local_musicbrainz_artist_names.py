"""Acquire or replay bounded exact-MBID names for a local source cohort."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

import httpx

from opennoise.catalog.musicbrainz_artist_names import (
    acquire_artist_name_enrichment,
    verify_artist_name_enrichment,
)


def _progress(done: int, total: int) -> None:
    if done % 1000 == 0 or done == total:
        sys.stderr.write(f"artist metadata batches: {done}/{total}\n")
        sys.stderr.flush()


async def _acquire(args: argparse.Namespace) -> dict[str, object]:
    async with httpx.AsyncClient(timeout=30.0) as client:
        return await acquire_artist_name_enrichment(
            catalog_directory=args.catalog_directory,
            directory=args.output_directory,
            client=client,
            user_agent="OpenNoise/0.1 (bounded metadata research; https://github.com/h0rv/opennoise)",
            limit=args.limit,
            progress=_progress,
        )


def main() -> int:
    """Retain exact official response bytes; replay without any HTTP client in verify mode."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog-directory", type=Path, required=True)
    parser.add_argument("--output-directory", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=40_000)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    result = (
        verify_artist_name_enrichment(
            catalog_directory=args.catalog_directory, directory=args.output_directory
        )
        if args.verify_only
        else asyncio.run(_acquire(args))
    )
    sys.stdout.write(
        json.dumps(
            {key: value for key, value in result.items() if key not in {"rows", "pages"}},
            sort_keys=True,
        )
        + "\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
