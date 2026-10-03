"""Verify source-only FMA memberships against every frozen query and calibration component."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from opennoise.ml.fma_memberships import replay_membership_pack


def main() -> None:
    """Replay thresholds, suggestions and metrics without fitting or obtaining audio."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--saved-pack", type=Path, required=True)
    parser.add_argument("--memberships", type=Path, required=True)
    args = parser.parse_args()
    sys.stdout.write(
        json.dumps(replay_membership_pack(args.saved_pack, args.memberships), indent=2) + "\n"
    )


if __name__ == "__main__":
    main()
