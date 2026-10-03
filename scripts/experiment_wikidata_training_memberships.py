"""Run a frozen training-only innerfold source-positive completion diagnostic."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from opennoise.ml.wikidata_training_experiment import experiment


def main() -> None:
    """Create a new isolated artifact; never apply selection to confirmation."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-pack", type=Path, required=True)
    parser.add_argument("--source-receipt-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = experiment(args.source_pack, args.output, args.source_receipt_sha256)
    sys.stdout.write(
        json.dumps(
            {
                "selected_arm_training_only": report["selected_arm_training_only"],
                "mean_innerfold_recall_at_10": report["mean_innerfold_recall_at_10"],
                "peak_rss_bytes": report["peak_rss_bytes"],
                "confirmation_evaluation": False,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )


if __name__ == "__main__":
    main()
