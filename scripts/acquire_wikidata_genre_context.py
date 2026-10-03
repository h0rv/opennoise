"""Acquire or replay literal native P136 vocabulary and outward P279 context."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from opennoise.ingest.wikidata.genre_context import acquire, verify_pack


def main() -> None:
    """Use a separate immutable pack and preserve the original artist input."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--artists", type=Path, required=True)
    parser.add_argument("--core", type=Path, required=True)
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    result = (verify_pack if args.verify else acquire)(args.output, args.artists, args.core)
    sys.stdout.write(json.dumps(result, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
