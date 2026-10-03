"""Run the two-arm post-inspection selected-rule source-recovery diagnostic."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from opennoise.ml.wikidata_selected_rule_diagnostic import ARMS, diagnostic


def main() -> None:
    """Create a separate sealed diagnostic without promotion or tuning."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-pack", required=True, type=Path)
    parser.add_argument("--source-receipt-sha256", required=True)
    parser.add_argument("--selection-pack", required=True, type=Path)
    parser.add_argument("--selection-receipt-sha256", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    report = diagnostic(
        args.source_pack,
        args.source_receipt_sha256,
        args.selection_pack,
        args.selection_receipt_sha256,
        args.output,
    )
    sys.stdout.write(
        json.dumps(
            {
                "revision": report["revision"],
                "outer_source_positive_r10": {
                    split: {arm: values["arms"][arm]["all"]["recall"]["10"] for arm in ARMS}
                    for split, values in report["outer_splits"].items()
                },
                "peak_rss_bytes": report["peak_rss_bytes"],
                "fresh_confirmation": False,
                "calibrated_musical_probability": False,
                "acceptance_gate_pass": False,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )


if __name__ == "__main__":
    main()
