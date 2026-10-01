"""Build a static local explorer from verified model, catalog, and native labels."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from opennoise.deployment.direct_custody_preview import build_local_direct_custody_preview


def main() -> int:
    """Require explicit immutable local inputs and a new cache-only destination."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-directory", required=True, type=Path)
    parser.add_argument("--catalog-directory", required=True, type=Path)
    parser.add_argument("--label-directory", required=True, type=Path)
    parser.add_argument("--artist-name-directory", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    receipt = build_local_direct_custody_preview(
        model_directory=args.model_directory,
        catalog_directory=args.catalog_directory,
        label_directory=args.label_directory,
        output=args.output,
        artist_name_directory=args.artist_name_directory,
    )
    sys.stdout.write(json.dumps(receipt, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
