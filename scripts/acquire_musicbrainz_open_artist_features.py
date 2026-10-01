"""Acquire diverse native artist tags and descriptors for open microgenre modeling."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

import httpx

from opennoise.catalog.musicbrainz_open_features import (
    acquire_open_artist_features,
    verify_open_artist_features,
)


def _progress(done: int, total: int) -> None:
    sys.stderr.write(f"new native feature metadata: {done}/{total}\n")
    sys.stderr.flush()


async def _acquire(args: argparse.Namespace) -> dict[str, object]:
    async with httpx.AsyncClient(timeout=30.0) as client:
        return await acquire_open_artist_features(
            catalog_directory=args.catalog_directory,
            name_directory=args.name_directory,
            license_path=args.license_path,
            directory=args.output_directory,
            client=client,
            user_agent="OpenNoise/0.1 (bounded local noncommercial research; https://github.com/h0rv/opennoise)",
            new_artist_limit=args.limit,
            progress=_progress,
        )


def main() -> int:
    """Build retained source metadata or replay its complete feature projection offline."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog-directory", type=Path, required=True)
    parser.add_argument("--name-directory", type=Path, required=True)
    parser.add_argument("--license-path", type=Path, required=True)
    parser.add_argument("--output-directory", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=5000)
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
