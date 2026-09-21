"""Evaluate one fixed local v3 candidate against held-out historical positives."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from opennoise.checkpoints.v3_terminal_historical_evaluation import (
    V3TerminalHistoricalEvaluationError,
    V3TerminalHistoricalEvaluationInputs,
    build_v3_terminal_historical_evaluation,
    write_v3_terminal_historical_evaluation,
)


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--serving-database", type=Path, required=True)
    parser.add_argument("--historical-reference", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--output-receipt", type=Path)
    return parser.parse_args()


def main() -> int:
    """Print a report, optionally writing only the report and its receipt."""
    arguments = _arguments()
    if (arguments.output is None) != (arguments.output_receipt is None):
        sys.stderr.write(
            "v3 terminal historical evaluation requires both output paths or neither\n"
        )
        return 2
    try:
        report = build_v3_terminal_historical_evaluation(
            V3TerminalHistoricalEvaluationInputs(
                model=arguments.model,
                receipt=arguments.receipt,
                serving_database=arguments.serving_database,
                historical_reference=arguments.historical_reference,
            )
        )
        if arguments.output is not None and arguments.output_receipt is not None:
            write_v3_terminal_historical_evaluation(
                arguments.output, arguments.output_receipt, report
            )
    except (OSError, ValueError, V3TerminalHistoricalEvaluationError) as error:
        sys.stderr.write(f"v3 terminal historical evaluation failed: {error}\n")
        return 2
    sys.stdout.write(report.model_dump_json(indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
