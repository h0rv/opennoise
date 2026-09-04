"""Run independent structural release gates for a historical hierarchy artifact."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from musix.historical_hierarchy_release_gate import evaluate_historical_hierarchy_release_gate
from musix.models.historical_signal import HistoricalSignalArtifact


def main() -> int:
    """Print gate results and return nonzero when a release condition fails."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--signal-artifact", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    try:
        artifact = HistoricalSignalArtifact.model_validate_json(
            arguments.signal_artifact.read_text(encoding="utf-8")
        )
        report = evaluate_historical_hierarchy_release_gate(artifact)
        payload = report.model_dump_json(indent=2) + "\n"
        if arguments.output:
            arguments.output.parent.mkdir(parents=True, exist_ok=True)
            arguments.output.write_text(payload, encoding="utf-8")
    except (OSError, ValueError) as error:
        sys.stderr.write(f"historical hierarchy release gate failed: {error}\n")
        return 2
    sys.stdout.write(payload)
    return 0 if report.passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
