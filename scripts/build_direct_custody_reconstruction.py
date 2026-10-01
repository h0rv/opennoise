"""Compare source-only linear reconstruction on isolated validation and test observations."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from opennoise.ml.direct_custody_reconstruction import build_reconstruction


def main() -> int:
    """Write a new local reconstruction experiment from verified portable custody."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--receipt",
        type=Path,
        default=Path("config/releases/musicbrainz-direct-proper-genre-custody-v1/receipt.json"),
    )
    parser.add_argument(
        "--object-store",
        type=Path,
        default=Path("data/release/musicbrainz-direct-proper-genre-custody-v1/objects"),
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = build_reconstruction(
        receipt_path=args.receipt, object_store=args.object_store, output=args.output
    )
    sys.stdout.write(
        json.dumps({"selected_arm": report["selected_arm"], "test": report["test"]}, indent=2)
        + "\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
