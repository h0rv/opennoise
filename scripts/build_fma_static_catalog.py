"""Build the separate native FMA source catalog after full offline custody replay."""

import argparse
import json
import sys
from pathlib import Path

from opennoise.deployment.fma_static import build_fma_static


def main() -> None:
    """Build only into a fresh local destination."""
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ("source", "projected", "output"):
        parser.add_argument(f"--{flag}", required=True, type=Path)
    args = parser.parse_args()
    receipt = build_fma_static(source=args.source, projected=args.projected, output=args.output)
    sys.stdout.write(
        json.dumps({key: value for key, value in receipt.items() if key != "files"}, indent=2)
        + "\n"
    )


if __name__ == "__main__":
    main()
