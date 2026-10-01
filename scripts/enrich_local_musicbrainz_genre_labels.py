"""Acquire bounded official genre dictionary labels for local exact-UUID enrichment."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

import httpx

from opennoise.catalog.musicbrainz_genre_labels import (
    acquire_native_musicbrainz_genre_labels,
    build_local_musicbrainz_genre_label_join,
)
from opennoise.sources.musicbrainz import MusicBrainzClient


async def _run(directory: Path) -> None:
    async with httpx.AsyncClient(timeout=30.0) as http_client:
        client = MusicBrainzClient(
            http_client,
            user_agent="OpenNoise/0.1 (bounded metadata research; https://github.com/h0rv/opennoise)",
        )
        result = await acquire_native_musicbrainz_genre_labels(client=client, directory=directory)
    sys.stdout.write(
        json.dumps({"genre_count": result["genre_count"], "output_sha256": result["output_sha256"]})
        + "\n"
    )


def main() -> int:
    """Write retained source pages and a verifiable local-only label projection."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-directory", type=Path, default=Path(".cache/musicbrainz-native-genre-labels")
    )
    parser.add_argument("--catalog-directory", type=Path)
    args = parser.parse_args()
    asyncio.run(_run(args.output_directory))
    if args.catalog_directory is not None:
        join = build_local_musicbrainz_genre_label_join(
            catalog_directory=args.catalog_directory,
            label_directory=args.output_directory,
            output_path=args.output_directory / "seed-genre-join.json",
        )
        sys.stdout.write(
            json.dumps(
                {
                    "resolved_seed_count": join["resolved_seed_count"],
                    "abstained_seed_count": join["abstained_seed_count"],
                    "join_output_sha256": join["output_sha256"],
                }
            )
            + "\n"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
