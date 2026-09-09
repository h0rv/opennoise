"""Run the compatibility-only H3 evaluator."""

from __future__ import annotations

import argparse
from pathlib import Path

from musix.serving.public.artist_membership_historical import (
    evaluate_public_artist_membership_historical,
)


def main() -> int:
    """Parse paths and write the strict frozen evaluation report."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--approved-input", type=Path, required=True)
    parser.add_argument("--public-database", type=Path, required=True)
    parser.add_argument("--historical-database", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--k", type=int, default=50)
    args = parser.parse_args()
    report = evaluate_public_artist_membership_historical(
        candidate_path=args.candidate,
        approved_input_path=args.approved_input,
        public_database_path=args.public_database,
        historical_database_path=args.historical_database,
        k=args.k,
    )
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
