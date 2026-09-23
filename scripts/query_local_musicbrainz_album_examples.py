"""Query the verified local MusicBrainz Album example report as JSON."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from opennoise.serving.local.musicbrainz_album_discovery import (
    AlbumDiscoveryError,
    load_album_examples_report,
    load_verified_artist_metadata,
    query_album_examples,
    response_json,
)


def main() -> int:
    """Print exact matches from a local-only Album example report."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--report",
        type=Path,
        default=Path(".cache/musicbrainz-release-group-album-examples-v1/report.json"),
    )
    query = parser.add_mutually_exclusive_group(required=True)
    query.add_argument("--genre-name", help="exact native genre name")
    query.add_argument("--artist-mbid", help="exact credited artist MBID")
    parser.add_argument("--artist-metadata-database", type=Path)
    parser.add_argument("--artist-metadata-artifact", type=Path)
    arguments = parser.parse_args()

    if (arguments.artist_metadata_database is None) != (arguments.artist_metadata_artifact is None):
        parser.error("artist metadata database and artifact must be provided together")
    try:
        report = load_album_examples_report(arguments.report)
        metadata = (
            load_verified_artist_metadata(
                arguments.artist_metadata_database, arguments.artist_metadata_artifact
            )
            if arguments.artist_metadata_database is not None
            and arguments.artist_metadata_artifact is not None
            else None
        )
        result = query_album_examples(
            report,
            genre_name=arguments.genre_name,
            artist_mbid=arguments.artist_mbid,
            artist_metadata=metadata,
        )
    except (AlbumDiscoveryError, OSError, ValueError) as error:
        sys.stderr.write(f"local Album example query failed: {error}\n")
        return 1
    sys.stdout.write(response_json(result) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
