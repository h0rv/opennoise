"""Build review-only learned MusicBrainz tag-label alignment candidates."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from musix.learned_label_alignment import (
    LearnedLabelAlignmentSettings,
    build_learned_label_alignment,
    publish_learned_label_alignment,
)
from musix.musicbrainz_seed_targets import load_seed_target_artifact
from musix.seed_reconciliation import load_seed_reconciliation
from musix.storage import LocalObjectStore


def build_parser() -> argparse.ArgumentParser:
    """Expose the two sealed source artifacts and bounded model settings."""
    parser = argparse.ArgumentParser(prog="build-learned-label-alignment")
    parser.add_argument("--seed-target-artifact", type=Path, required=True)
    parser.add_argument("--seed-reconciliation", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--object-store", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--validation-seed-fraction", type=float, default=0.2)
    parser.add_argument("--split-seed", type=int, default=20260905)
    parser.add_argument("--hard-negatives-per-positive", type=int, default=4)
    parser.add_argument("--candidates-per-unresolved-seed", type=int, default=20)
    parser.add_argument("--l2-regularization", type=float, default=1.0)
    parser.add_argument("--review-score-threshold", type=float, default=0.5)
    return parser


def main() -> int:
    """Build, verify, and publish one review-only alignment experiment."""
    arguments = build_parser().parse_args()
    settings = LearnedLabelAlignmentSettings(
        validation_seed_fraction=arguments.validation_seed_fraction,
        split_seed=arguments.split_seed,
        hard_negatives_per_positive=arguments.hard_negatives_per_positive,
        candidates_per_unresolved_seed=arguments.candidates_per_unresolved_seed,
        l2_regularization=arguments.l2_regularization,
        review_score_threshold=arguments.review_score_threshold,
    )
    artifact = build_learned_label_alignment(
        load_seed_target_artifact(arguments.seed_target_artifact),
        load_seed_reconciliation(arguments.seed_reconciliation),
        settings,
    )
    receipt, _write = publish_learned_label_alignment(
        artifact,
        output_path=arguments.output,
        store=LocalObjectStore(arguments.object_store),
    )
    arguments.receipt.parent.mkdir(parents=True, exist_ok=True)
    arguments.receipt.write_text(receipt.model_dump_json(indent=2) + "\n", encoding="utf-8")
    sys.stdout.write(
        json.dumps(
            {
                "coverage": artifact.coverage.model_dump(),
                "train_metrics": artifact.train_metrics.model_dump(),
                "validation_metrics": artifact.validation_metrics.model_dump(),
                "receipt": receipt.model_dump(),
            },
            indent=2,
        )
        + "\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
