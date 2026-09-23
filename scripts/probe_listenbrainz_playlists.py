"""Fetch a bounded explicit set of public ListenBrainz playlists into a local snapshot."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
from uuid import UUID

from opennoise.ingest.listenbrainz.playlists import (
    PlaylistProbeSettings,
    fetch_public_playlist_snapshots,
    write_public_playlist_snapshot_bundle,
)


def _playlist_mbid(value: str) -> UUID:
    """Parse one explicit MusicBrainz playlist UUID at the command boundary."""
    try:
        return UUID(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("playlist MBID must be a UUID") from error


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--playlist-mbid",
        action="append",
        type=_playlist_mbid,
        required=True,
        help="Explicit public ListenBrainz playlist MusicBrainz UUID; repeat at most 50 times.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="New local JSON path. Existing paths are never replaced.",
    )
    return parser.parse_args()


async def _run() -> None:
    arguments = _arguments()
    settings = PlaylistProbeSettings()
    snapshots = await fetch_public_playlist_snapshots(
        arguments.playlist_mbid,
        settings=settings,
        raw_object_directory=arguments.output.parent / "raw" / "sha256",
    )
    write_public_playlist_snapshot_bundle(
        snapshots,
        arguments.output,
        raw_object_directory=arguments.output.parent / "raw" / "sha256",
    )


if __name__ == "__main__":
    asyncio.run(_run())
