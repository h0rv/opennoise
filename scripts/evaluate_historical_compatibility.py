"""Compare a historical compatibility artifact to an independent public model artifact."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from pydantic import ValidationError

from musix.history.historical_compatibility import (
    evaluate_historical_compatibility,
    load_public_comparison,
)
from musix.models.historical import HistoricalCompatibilityManifest


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("historical_manifest", type=Path)
    parser.add_argument("public_model", type=Path)
    parser.add_argument("--report", type=Path)
    return parser.parse_args()


def main() -> int:
    """Write a reproducible observed-only geometry and relationship comparison report."""
    arguments = _arguments()
    try:
        historical = HistoricalCompatibilityManifest.model_validate_json(
            arguments.historical_manifest.read_text(encoding="utf-8")
        )
        public = load_public_comparison(arguments.public_model)
        report = evaluate_historical_compatibility(historical, public)
    except (OSError, ValidationError, ValueError) as error:
        sys.stderr.write(f"historical compatibility evaluation failed: {error}\n")
        return 2
    payload = report.model_dump_json(indent=2) + "\n"
    if arguments.report is None:
        sys.stdout.write(payload)
    else:
        arguments.report.parent.mkdir(parents=True, exist_ok=True)
        arguments.report.write_text(payload, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
