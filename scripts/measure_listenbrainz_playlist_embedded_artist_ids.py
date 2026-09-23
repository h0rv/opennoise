"""Write a local-only receipt for embedded JSPF artist-identifier source claims."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from opennoise.analysis.listenbrainz_playlist_artist_bridge import (
    ListenBrainzPlaylistArtistBridgeArtifact,
)
from opennoise.analysis.listenbrainz_playlist_embedded_artist_ids import (
    ListenBrainzPlaylistEmbeddedArtistIdsError,
    measure_embedded_artist_identifiers,
)


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--playlist-bundle", type=Path, required=True)
    parser.add_argument("--raw-object-directory", type=Path, required=True)
    parser.add_argument("--exact-musicbrainz-bridge", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    """Measure one pre-existing local raw-object cohort without network access."""
    arguments = _arguments()
    if arguments.output.exists() or arguments.output.is_symlink():
        sys.stderr.write("embedded artist-identifier output already exists\n")
        return 2
    try:
        bridge = (
            ListenBrainzPlaylistArtistBridgeArtifact.model_validate_json(
                arguments.exact_musicbrainz_bridge.read_bytes()
            )
            if arguments.exact_musicbrainz_bridge is not None
            else None
        )
        artifact = measure_embedded_artist_identifiers(
            arguments.playlist_bundle,
            raw_object_directory=arguments.raw_object_directory,
            exact_musicbrainz_bridge=bridge,
        )
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(artifact.model_dump_json(indent=2), encoding="utf-8")
    except (ListenBrainzPlaylistEmbeddedArtistIdsError, OSError, ValueError) as error:
        sys.stderr.write(f"embedded artist-identifier measurement failed: {error}\n")
        return 1
    sys.stdout.write(f"wrote local-only embedded artist-identifier receipt: {arguments.output}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
