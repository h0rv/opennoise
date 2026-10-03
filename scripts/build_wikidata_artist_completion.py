"""Build a frozen source-conditional exact-artist P136 completion experiment."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from opennoise.ml.wikidata_artist_completion import build


def main() -> None:
    """Run directly without introducing another project task runner."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artists", type=Path, required=True)
    parser.add_argument("--genres", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    sys.stdout.write(
        json.dumps(build(args.artists, args.genres, args.output), indent=2, sort_keys=True) + "\n"
    )


if __name__ == "__main__":
    main()
