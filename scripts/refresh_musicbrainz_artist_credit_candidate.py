"""Refresh exact MusicBrainz artist credits for a bounded local release candidate."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

import httpx

from opennoise.ingest.musicbrainz.artist_credit_enrichment import (
    ArtistCreditRefreshSettings,
    MusicBrainzArtistCreditRefreshAdapter,
    write_artist_credit_refresh_candidate,
)


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hydration-artifact", required=True, type=Path)
    parser.add_argument("--cache-directory", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--user-agent", required=True)
    parser.add_argument("--offline", action="store_true")
    return parser.parse_args()


async def _run(arguments: argparse.Namespace) -> str:
    settings = ArtistCreditRefreshSettings(
        cache_directory=arguments.cache_directory, offline=arguments.offline
    )
    async with httpx.AsyncClient(timeout=30.0) as client:
        adapter = MusicBrainzArtistCreditRefreshAdapter(
            client, settings, user_agent=arguments.user_agent
        )
        candidate = await adapter.refresh(
            source_hydration_artifact_path=arguments.hydration_artifact
        )
    return write_artist_credit_refresh_candidate(candidate, output=arguments.output)


def main() -> int:
    """Write only a local artifact and refresh cache, never a public or sealed DB."""
    print(asyncio.run(_run(_arguments())))  # noqa: T201
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
