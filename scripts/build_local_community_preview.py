"""Build a verified static emergent-community explorer inside the local cache."""

import argparse
import json
import sys
from pathlib import Path

from opennoise.deployment.community_preview import build_community_preview


def main() -> None:
    """Export source-bound communities without modifying public artifacts."""
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ("source", "model", "features", "output"):
        parser.add_argument(f"--{flag}", type=Path, required=True)
    args = parser.parse_args()
    receipt = build_community_preview(
        source=args.source, model_directory=args.model, features=args.features, output=args.output
    )
    sys.stdout.write(
        json.dumps(
            {"coverage": receipt["coverage"], "output_sha256": receipt["output_sha256"]}, indent=2
        )
        + "\n"
    )


if __name__ == "__main__":
    main()
