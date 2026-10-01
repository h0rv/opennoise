"""Replay a captured outbound artist link projection without network access."""

import argparse
import json
import sys
from pathlib import Path

from opennoise.serving.metadata.artist_links import verify_artist_link_projection


def main() -> int:
    """Print counts only after the exact source relationships verify."""
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    artifact = verify_artist_link_projection(
        args.directory / "artist-links.json",
        args.directory / "receipt.json",
    )
    sys.stdout.write(
        json.dumps(
            {
                "artists": len(artifact["artists"]),
                "links": sum(len(artist["links"]) for artist in artifact["artists"]),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
