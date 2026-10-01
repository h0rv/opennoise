"""Acquire independent artist genres/tags for exact new native release-credit identities."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

import httpx

from opennoise.catalog.musicbrainz_native_artist_features import (
    acquire_native_artist_features,
    verify_native_artist_features,
)


def _progress(done: int, total: int) -> None:
    sys.stderr.write(f"native credited artist features: {done}/{total}\n")
    sys.stderr.flush()


async def _acquire(args: argparse.Namespace) -> dict[str, object]:
    async with httpx.AsyncClient(timeout=30.0) as client:
        return await acquire_native_artist_features(
            catalog_directory=args.catalog_directory,
            release_directory=args.release_directory,
            directory=args.output_directory,
            license_path=args.license_path,
            client=client,
            user_agent="OpenNoise/0.1 (bounded local noncommercial research; https://github.com/h0rv/opennoise)",
            progress=_progress,
        )


def main() -> int:
    """Create a separate artist source artifact or replay it without an HTTP client."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog-directory", type=Path, required=True)
    parser.add_argument("--release-directory", type=Path, required=True)
    parser.add_argument("--output-directory", type=Path, required=True)
    parser.add_argument("--license-path", type=Path, required=True)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    result = (
        verify_native_artist_features(directory=args.output_directory)
        if args.verify_only
        else asyncio.run(_acquire(args))
    )
    sys.stdout.write(json.dumps(result, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
