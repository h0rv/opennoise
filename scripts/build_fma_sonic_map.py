"""Build or independently replay a separately named train-only native FMA descriptor map."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from opennoise.ml.fma_sonic_map import build_map, replay_map


def main() -> None:
    """Require explicit immutable sources and new output; never change legacy artifacts."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--features", type=Path, required=True)
    parser.add_argument("--saved-pack", type=Path, required=True)
    parser.add_argument("--declaration", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    if args.verify:
        result = replay_map(args.metadata, args.features, args.saved_pack, args.output)
    else:
        if args.declaration is None:
            parser.error("--declaration required for a new map")
        result = build_map(
            args.metadata, args.features, args.saved_pack, args.declaration, args.output
        )
    sys.stdout.write(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    main()
