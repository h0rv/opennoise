"""Export a frozen validation-only FMA source-positive membership calibration arm."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from opennoise.ml.fma_memberships import build_membership_pack


def main() -> None:
    """Keep baseline read-only and require a fresh explicit output directory."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--saved-pack", type=Path, required=True)
    parser.add_argument("--declaration", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    sys.stdout.write(
        json.dumps(build_membership_pack(args.saved_pack, args.declaration, args.output), indent=2)
        + "\n"
    )


if __name__ == "__main__":
    main()
