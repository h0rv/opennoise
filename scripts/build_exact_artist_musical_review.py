"""Freeze a method-blind exact-artist musical review without fabricated listeners."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from opennoise.review.artist_musical_cohort import DEFAULT_MODEL_RECEIPT, build_packet


def main() -> None:
    """Build public forms and separate private coordinator keys in new directories."""
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("model", "artists", "genres", "recordings", "pilot", "core", "output"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--expected-model-receipt", default=DEFAULT_MODEL_RECEIPT)
    args = parser.parse_args()
    result = build_packet(
        args.model,
        args.artists,
        args.genres,
        args.recordings,
        args.pilot,
        args.output,
        core=args.core,
        expected_model_receipt=args.expected_model_receipt,
    )
    sys.stdout.write(json.dumps(result, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
