"""Build and publish the open-evidence label graph review layer."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from musix.taxonomy.open_label_graph_model import (
    OpenLabelGraphSettings,
    build_open_label_graph_model_from_path,
    publish_open_label_graph_model,
)
from musix.taxonomy.seed_reconciliation import load_seed_reconciliation
from musix.storage import LocalObjectStore


def build_parser() -> argparse.ArgumentParser:
    """Expose the sealed open evidence inputs and bounded tuning controls."""
    parser = argparse.ArgumentParser(prog="build-open-label-graph-model")
    parser.add_argument("--seed-target-artifact", type=Path, required=True)
    parser.add_argument("--seed-reconciliation", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--object-store", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--split-seed", type=int, default=20260906)
    parser.add_argument("--calibration-fraction", type=float, default=0.2)
    parser.add_argument("--test-fraction", type=float, default=0.2)
    parser.add_argument("--hard-negatives-per-anchor", type=int, default=8)
    parser.add_argument("--candidates-per-label", type=int, default=5)
    parser.add_argument("--maximum-retrieval-candidates", type=int, default=500)
    parser.add_argument("--minimum-review-precision", type=float, default=0.8)
    parser.add_argument("--minimum-lexical-score", type=float, default=0.25)
    return parser


def main() -> int:
    """Build, evaluate, verify, and publish one open label graph model."""
    arguments = build_parser().parse_args()
    settings = OpenLabelGraphSettings(
        split_seed=arguments.split_seed,
        calibration_fraction=arguments.calibration_fraction,
        test_fraction=arguments.test_fraction,
        hard_negatives_per_anchor=arguments.hard_negatives_per_anchor,
        candidates_per_label=arguments.candidates_per_label,
        maximum_retrieval_candidates=arguments.maximum_retrieval_candidates,
        minimum_review_precision=arguments.minimum_review_precision,
        minimum_lexical_score=arguments.minimum_lexical_score,
    )
    artifact = build_open_label_graph_model_from_path(
        arguments.seed_target_artifact,
        load_seed_reconciliation(arguments.seed_reconciliation),
        settings,
    )
    receipt, _write = publish_open_label_graph_model(
        artifact, output_path=arguments.output, store=LocalObjectStore(arguments.object_store)
    )
    arguments.receipt.parent.mkdir(parents=True, exist_ok=True)
    arguments.receipt.write_text(receipt.model_dump_json(indent=2) + "\n", encoding="utf-8")
    sys.stdout.write(
        json.dumps(
            {
                "coverage": artifact.coverage.model_dump(),
                "heldout_comparison": artifact.heldout_comparison.model_dump(),
                "calibrated_review_threshold": artifact.calibrated_review_threshold,
                "receipt": receipt.model_dump(),
            },
            indent=2,
        )
        + "\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
