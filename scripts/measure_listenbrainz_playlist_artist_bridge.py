"""Bridge one source-pinned ListenBrainz playlist recording sample to MusicBrainz credits."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

import httpx

from opennoise.analysis.listenbrainz_playlist_artist_bridge import (
    ListenBrainzPlaylistArtistBridgeError,
    make_playlist_selection_receipt,
    measure_playlist_artist_bridge,
)


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--playlist-bundle", type=Path, required=True)
    parser.add_argument("--expected-playlist-bundle-file-sha256", required=True)
    parser.add_argument("--raw-object-directory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--response-cache-directory", type=Path, required=True)
    parser.add_argument("--user-agent", required=True)
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    return parser.parse_args()


async def _run(arguments: argparse.Namespace) -> None:
    selection = make_playlist_selection_receipt(
        arguments.playlist_bundle, raw_object_directory=arguments.raw_object_directory
    )
    if (
        selection.source_playlist_bundle_file_sha256
        != arguments.expected_playlist_bundle_file_sha256
    ):
        raise ValueError("playlist bundle file SHA-256 does not match the required expected value")
    async with httpx.AsyncClient(
        timeout=arguments.timeout_seconds, follow_redirects=False
    ) as client:
        artifact = await measure_playlist_artist_bridge(
            selection,
            client,
            user_agent=arguments.user_agent,
            response_cache_directory=arguments.response_cache_directory,
        )
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = arguments.output.with_name(f".{arguments.output.name}.tmp")
    try:
        temporary.write_text(artifact.model_dump_json(indent=2), encoding="utf-8")
        temporary.replace(arguments.output)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> int:
    """Write one new local-only, source-pinned exact artist-credit bridge artifact."""
    arguments = _arguments()
    if arguments.output.exists():
        sys.stderr.write("playlist artist bridge output already exists\n")
        return 2
    try:
        asyncio.run(_run(arguments))
    except (ListenBrainzPlaylistArtistBridgeError, OSError, ValueError) as error:
        sys.stderr.write(f"playlist artist bridge failed: {error}\n")
        return 1
    sys.stdout.write(f"wrote local-only playlist artist bridge: {arguments.output}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
