"""Certify sealed source-neutral inputs, with an optional separate historical evaluation."""

from __future__ import annotations

import argparse
from pathlib import Path

from musix.checkpoints.source_neutral_certification import (
    SourceNeutralCheckpointInputs,
    build_source_neutral_checkpoint_certification,
    evaluate_source_neutral_checkpoint_against_historical,
    write_historical_checkpoint_evaluation,
    write_source_neutral_checkpoint_certification,
)


def main() -> int:
    """Parse explicit sealed paths and persist the deterministic certification."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--graph-database", type=Path, required=True)
    parser.add_argument("--graph-receipt", type=Path, required=True)
    parser.add_argument("--consensus", type=Path, required=True)
    parser.add_argument("--taxonomy", type=Path, required=True)
    parser.add_argument("--historical-evaluation", type=Path)
    parser.add_argument("--historical-output", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    inputs = SourceNeutralCheckpointInputs(
        graph_database=arguments.graph_database,
        graph_receipt=arguments.graph_receipt,
        consensus_micro_neighborhoods=arguments.consensus,
        exact_qid_taxonomy=arguments.taxonomy,
    )
    if (arguments.historical_evaluation is None) != (arguments.historical_output is None):
        parser.error("--historical-evaluation and --historical-output must be provided together")
    certification = build_source_neutral_checkpoint_certification(inputs)
    write_source_neutral_checkpoint_certification(arguments.output, certification)
    if arguments.historical_evaluation is not None and arguments.historical_output is not None:
        write_historical_checkpoint_evaluation(
            arguments.historical_output,
            evaluate_source_neutral_checkpoint_against_historical(
                certification, inputs, arguments.historical_evaluation
            ),
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
