"""Compose a local named-style atlas, inferred communities and source explorer."""

import argparse
import json
import sys
from pathlib import Path

from opennoise.deployment.discovery_product import build_discovery_product


def main() -> None:
    """Build a fresh verified composition confined to the project cache."""
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ("atlas", "communities", "output"):
        parser.add_argument(f"--{flag}", required=True, type=Path)
    args = parser.parse_args()
    receipt = build_discovery_product(
        atlas=args.atlas, communities=args.communities, output=args.output
    )
    sys.stdout.write(
        json.dumps(
            {"output": str(args.output), "output_sha256": receipt["output_sha256"]}, indent=2
        )
        + "\n"
    )


if __name__ == "__main__":
    main()
