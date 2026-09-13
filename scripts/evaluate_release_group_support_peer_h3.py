"""Evaluate a local support peer artifact against bridge-resolved H3 positives."""

from __future__ import annotations

import argparse
from pathlib import Path

from opennoise.peers.support.h3_evaluation import evaluate_support_peer_h3


def main() -> int:
    """Write a sealed, evaluation-only support peer report."""
    parser = argparse.ArgumentParser(description=__doc__)
    for option in (
        "candidate",
        "reconciliation",
        "public-input",
        "bridge",
        "bridge-receipt",
        "historical-database",
        "output",
    ):
        parser.add_argument(f"--{option}", type=Path, required=True)
    parser.add_argument("--bridge-receipt-sha256", required=True)
    arguments = parser.parse_args()
    report = evaluate_support_peer_h3(
        candidate_path=arguments.candidate,
        reconciliation_path=arguments.reconciliation,
        public_input_path=arguments.public_input,
        bridge_path=arguments.bridge,
        bridge_receipt_path=arguments.bridge_receipt,
        bridge_receipt_sha256=arguments.bridge_receipt_sha256,
        historical_database_path=arguments.historical_database,
    )
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
