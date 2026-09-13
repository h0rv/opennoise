"""Run the source-neutral microgenre signal checkpoint over a sealed JSON graph."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from musix.taxonomy.open.microgenre_signal import (
    MicrogenreSignalSettings,
    build_microgenre_signal_checkpoint,
    load_source_neutral_microgenre_input,
    verify_microgenre_signal_checkpoint,
)


def build_parser() -> argparse.ArgumentParser:
    """Expose only deterministic, bounded baseline controls."""
    parser = argparse.ArgumentParser(prog="build-microgenre-signal-checkpoint")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--split-seed", type=int, default=20260913)
    parser.add_argument("--heldout-fraction", type=float, default=0.25)
    parser.add_argument("--score-threshold", type=float, default=0.35)
    parser.add_argument("--evaluation-k", type=int, default=10)
    parser.add_argument("--max-generated-candidates-per-relation", type=int, default=500)
    return parser


def main() -> int:
    """Build a review-only artifact and print concise held-out metrics."""
    arguments = build_parser().parse_args()
    settings = MicrogenreSignalSettings(
        split_seed=arguments.split_seed,
        heldout_fraction=arguments.heldout_fraction,
        score_threshold=arguments.score_threshold,
        evaluation_k=arguments.evaluation_k,
        max_generated_candidates_per_relation=arguments.max_generated_candidates_per_relation,
    )
    artifact = build_microgenre_signal_checkpoint(
        load_source_neutral_microgenre_input(arguments.input), settings
    )
    verify_microgenre_signal_checkpoint(artifact)
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(artifact.model_dump_json(indent=2) + "\n", encoding="utf-8")
    sys.stdout.write(
        json.dumps(
            {
                "coverage": artifact.coverage.model_dump(),
                "relations": [metric.model_dump() for metric in artifact.relation_metrics],
                "output_sha256": artifact.output_sha256,
            },
            indent=2,
        )
        + "\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
