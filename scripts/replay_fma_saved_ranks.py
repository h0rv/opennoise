"""Verify the small tracked FMA saved-rank pack and every reported metric offline."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from opennoise.ml.fma_saved_replay import replay_saved_pack


def main() -> None:
    """Verify an explicit saved pack without fitting or requesting audio/source data."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pack", type=Path)
    args = parser.parse_args()
    sys.stdout.write(json.dumps(replay_saved_pack(args.pack), indent=2) + "\n")


if __name__ == "__main__":
    main()
