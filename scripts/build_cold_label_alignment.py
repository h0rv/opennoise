"""Build the conservative cold-label checkpoint from the sealed local cache."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

from opennoise.ml.label_alignment import (
    ColdLabelAlignmentInputs,
    ColdLabelAlignmentSettings,
    build_cold_label_alignment,
    write_cold_label_alignment,
)


def _shared_cache_root() -> Path:
    """Find the main-checkout cache even when invoked from a linked worktree."""
    git = shutil.which("git")
    if git is None:
        raise RuntimeError("git is required to locate the shared OpenNoise cache")
    completed = subprocess.run(  # noqa: S603 - fixed git subcommand after absolute PATH lookup.
        [git, "rev-parse", "--path-format=absolute", "--git-common-dir"],
        check=True,
        capture_output=True,
        text=True,
    )
    return Path(completed.stdout.strip()).parent / ".cache"


def _parser(cache_root: Path) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--graph-database", type=Path, default=cache_root / "evidence-graph-v2.sqlite"
    )
    parser.add_argument(
        "--graph-receipt", type=Path, default=cache_root / "evidence-graph-v2.receipt.json"
    )
    parser.add_argument(
        "--reconciliation",
        type=Path,
        default=cache_root / "musicbrainz-full-seed-targets/pipeline/seed-reconciliation.json",
    )
    parser.add_argument("--output-root", type=Path, default=cache_root / "cold-label-alignment-v1")
    parser.add_argument("--supplemental-vocabulary", type=Path)
    parser.add_argument("--supplemental-vocabulary-receipt", type=Path)
    parser.add_argument(
        "--allow-partial-supplemental-vocabulary",
        action="store_true",
        help=(
            "allow a bounded prefix only for an exploratory run; default checkpoint selection "
            "requires completed_source_member=true"
        ),
    )
    parser.add_argument("--split-seed", type=int, default=20260913)
    parser.add_argument("--masked-evaluation-fraction", type=float, default=0.2)
    parser.add_argument("--candidates-per-seed", type=int, default=5)
    parser.add_argument("--maximum-head-candidates", type=int, default=250)
    parser.add_argument("--minimum-review-score", type=float, default=0.68)
    return parser


def main() -> int:
    """Build, seal, and print the portable checkpoint summary."""
    arguments = _parser(_shared_cache_root()).parse_args()
    artifact = build_cold_label_alignment(
        ColdLabelAlignmentInputs(
            graph_database=arguments.graph_database,
            graph_receipt=arguments.graph_receipt,
            reconciliation=arguments.reconciliation,
            supplemental_vocabulary=arguments.supplemental_vocabulary,
            supplemental_vocabulary_receipt=arguments.supplemental_vocabulary_receipt,
            supplemental_vocabulary_selection=(
                "allow_partial"
                if arguments.allow_partial_supplemental_vocabulary
                else "complete_only"
            ),
        ),
        ColdLabelAlignmentSettings(
            split_seed=arguments.split_seed,
            masked_evaluation_fraction=arguments.masked_evaluation_fraction,
            candidates_per_seed=arguments.candidates_per_seed,
            maximum_head_candidates=arguments.maximum_head_candidates,
            minimum_review_score=arguments.minimum_review_score,
        ),
    )
    receipt, artifact_path, receipt_path = write_cold_label_alignment(
        artifact, arguments.output_root
    )
    sys.stdout.write(
        json.dumps(
            {
                "artifact": str(artifact_path),
                "receipt": str(receipt_path),
                "logical_output_sha256": artifact.output_sha256,
                "artifact_sha256": receipt.artifact_sha256,
                "coverage": artifact.coverage.model_dump(mode="json"),
                "masked_evaluation": artifact.masked_evaluation.model_dump(mode="json"),
            },
            sort_keys=True,
        )
        + "\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
