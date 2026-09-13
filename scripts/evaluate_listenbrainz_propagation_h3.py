"""Evaluate sealed ListenBrainz review candidates against bridge-resolved H3 positives."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from opennoise.ingest.listenbrainz.h3_evaluation import (
    ListenBrainzH3EvaluationInputs,
    ListenBrainzH3EvaluationSettings,
    evaluate_listenbrainz_propagation_h3,
    publish_listenbrainz_h3_evaluation,
)
from opennoise.storage import LocalObjectStore


def build_parser() -> argparse.ArgumentParser:
    """Declare sealed construction and separate evaluation custody boundaries."""
    parser = argparse.ArgumentParser(prog="evaluate-listenbrainz-propagation-h3")
    parser.add_argument("--frontier-v5", type=Path, required=True)
    parser.add_argument("--frontier-v5-receipt", type=Path, required=True)
    parser.add_argument("--listenbrainz-propagation", type=Path, required=True)
    parser.add_argument("--listenbrainz-propagation-receipt", type=Path, required=True)
    parser.add_argument("--bridge", type=Path, required=True)
    parser.add_argument("--bridge-receipt", type=Path, required=True)
    parser.add_argument("--bridge-receipt-sha256", required=True)
    parser.add_argument("--historical-database", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--object-store", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    return parser


def main() -> int:
    """Write an evaluation-only, positive-only H3 report."""
    arguments = build_parser().parse_args()
    artifact = evaluate_listenbrainz_propagation_h3(
        ListenBrainzH3EvaluationInputs(
            frontier_path=arguments.frontier_v5,
            frontier_receipt_path=arguments.frontier_v5_receipt,
            propagation_path=arguments.listenbrainz_propagation,
            propagation_receipt_path=arguments.listenbrainz_propagation_receipt,
            bridge_path=arguments.bridge,
            bridge_receipt_path=arguments.bridge_receipt,
            bridge_receipt_sha256=arguments.bridge_receipt_sha256,
            historical_database_path=arguments.historical_database,
        ),
        ListenBrainzH3EvaluationSettings(),
    )
    receipt = publish_listenbrainz_h3_evaluation(
        artifact, output_path=arguments.output, store=LocalObjectStore(arguments.object_store)
    )
    arguments.receipt.parent.mkdir(parents=True, exist_ok=True)
    arguments.receipt.write_text(receipt.model_dump_json(indent=2) + "\n", encoding="utf-8")
    sys.stdout.write(artifact.model_dump_json(indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
