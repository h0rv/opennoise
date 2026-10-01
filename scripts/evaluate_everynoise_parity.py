"""Evaluate measurable Every Noise reference gaps in a verified local explorer."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from opennoise.analysis.everynoise_parity import build_everynoise_parity_report


def main() -> None:
    """Require explicit reference, preview, and cache-only report paths."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", required=True, type=Path)
    parser.add_argument("--preview", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    report = build_everynoise_parity_report(
        reference=args.reference, preview=args.preview, output=args.output
    )
    sys.stdout.write(
        json.dumps(
            {
                key: report[key]
                for key in (
                    "reference_genre_count",
                    "candidate_genre_count",
                    "placed_candidate_genres",
                    "complete_artist_projection",
                    "overall_parity",
                    "output_sha256",
                )
            },
            indent=2,
        )
        + "\n"
    )


if __name__ == "__main__":
    main()
