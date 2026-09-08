"""Evaluate a sealed peer candidate against exact bridge-resolved H3 overlap."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from musix.peer_similarity_h3_bridge import evaluate_peer_similarity_h3_bridge


def main() -> int:
    """Write a local evaluation-only report with no construction side effects."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--public-input", type=Path, required=True)
    parser.add_argument("--bridge", type=Path, required=True)
    parser.add_argument("--bridge-receipt", type=Path, required=True)
    parser.add_argument("--bridge-receipt-sha256", required=True)
    parser.add_argument("--historical-database", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    report = evaluate_peer_similarity_h3_bridge(
        candidate_path=arguments.candidate,
        public_input_path=arguments.public_input,
        bridge_path=arguments.bridge,
        bridge_receipt_path=arguments.bridge_receipt,
        bridge_receipt_sha256=arguments.bridge_receipt_sha256,
        historical_database_path=arguments.historical_database,
    )
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
    sys.stdout.write(report.model_dump_json() + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
