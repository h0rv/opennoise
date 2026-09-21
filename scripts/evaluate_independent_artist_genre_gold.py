"""Evaluate a sealed independent artist--genre gold set against supplied predictions."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from opennoise.evidence.independent_artist_genre_gold import (
    evaluate_independent_gold,
    load_gold_set,
    load_prediction_set,
)


def main() -> int:
    """Write a deterministic, custody-bound diagnostic or production gate report."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gold", required=True, type=Path)
    parser.add_argument("--predictions", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    arguments = parser.parse_args()
    try:
        gold, gold_sha256 = load_gold_set(arguments.gold)
        predictions, prediction_sha256 = load_prediction_set(arguments.predictions)
        report = evaluate_independent_gold(
            gold,
            predictions,
            gold_file_sha256=gold_sha256,
            prediction_file_sha256=prediction_sha256,
        )
        arguments.report.parent.mkdir(parents=True, exist_ok=True)
        arguments.report.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
    except (OSError, ValueError) as error:
        sys.stderr.write(f"independent gold evaluation failed: {error}\n")
        return 2
    sys.stdout.write(report.model_dump_json(indent=2) + "\n")
    return 0 if report.release_quality_eligible else 2


if __name__ == "__main__":
    raise SystemExit(main())
