"""Create a local source-bound selection, optionally then run exact lookups."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

import httpx

from opennoise.analysis.listenbrainz_playlist_artist_followup import (
    ListenBrainzPlaylistArtistFollowupError,
    make_followup_selection,
    measure_followup_artist_credits,
)


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--playlist-bundle", type=Path, required=True)
    parser.add_argument("--raw-object-directory", type=Path, required=True)
    parser.add_argument("--prior-bridge", type=Path, required=True)
    parser.add_argument("--selection-output", type=Path, required=True)
    parser.add_argument("--live-output", type=Path)
    parser.add_argument("--response-cache-directory", type=Path)
    parser.add_argument("--user-agent")
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    return parser.parse_args()


async def _run(arguments: argparse.Namespace) -> None:
    selection = make_followup_selection(
        arguments.playlist_bundle,
        raw_object_directory=arguments.raw_object_directory,
        prior_bridge_file=arguments.prior_bridge,
    )
    _write_new_json(arguments.selection_output, selection.model_dump_json(indent=2))
    if arguments.live_output is None:
        return
    if arguments.response_cache_directory is None or arguments.user_agent is None:
        raise ValueError("live lookup requires --response-cache-directory and --user-agent")
    async with httpx.AsyncClient(
        timeout=arguments.timeout_seconds, follow_redirects=False
    ) as client:
        artifact = await measure_followup_artist_credits(
            selection,
            client,
            user_agent=arguments.user_agent,
            response_cache_directory=arguments.response_cache_directory,
        )
    _write_new_json(arguments.live_output, artifact.model_dump_json(indent=2))


def _write_new_json(path: Path, content: str) -> None:
    if path.exists():
        raise FileExistsError(f"output already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        temporary.write_text(content, encoding="utf-8")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> int:
    """Write only a dry selection unless all live arguments are explicit."""
    try:
        asyncio.run(_run(_arguments()))
    except (ListenBrainzPlaylistArtistFollowupError, OSError, ValueError) as error:
        sys.stderr.write(f"playlist artist follow-up audit failed: {error}\n")
        return 1
    sys.stdout.write("wrote local-only playlist artist follow-up selection or audit\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
