"""Evaluate a historical hierarchy artifact without changing or clustering it."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from musix.historical_hierarchy_evaluation import evaluate_historical_hierarchy
from musix.models.historical_signal import HistoricalSignalArtifact


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--signal-artifact", type=Path, required=True)
    parser.add_argument("--baseline-artifact", type=Path)
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def _load(path: Path) -> HistoricalSignalArtifact:
    return HistoricalSignalArtifact.model_validate_json(path.read_text(encoding="utf-8"))


def main() -> int:
    """Print a structural and evaluation-only lexical report."""
    arguments = _arguments()
    try:
        artifact = _load(arguments.signal_artifact)
        baseline = _load(arguments.baseline_artifact) if arguments.baseline_artifact else None
        report = evaluate_historical_hierarchy(artifact, baseline=baseline)
        payload = report.model_dump_json(indent=2) + "\n"
        if arguments.output:
            arguments.output.parent.mkdir(parents=True, exist_ok=True)
            arguments.output.write_text(payload, encoding="utf-8")
    except (OSError, ValueError) as error:
        sys.stderr.write(f"historical hierarchy evaluation failed: {error}\n")
        return 2
    sys.stdout.write(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
