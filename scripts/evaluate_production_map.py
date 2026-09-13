"""Reject a production-map evidence bundle that does not meet usability gates."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from opennoise.ml.production_map_qa import evaluate_production_map
from opennoise.models.production_qa import ProductionMapAcceptanceInput


def main() -> int:
    """Validate one JSON evidence bundle and write a machine-readable report."""
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("--report", type=Path)
    arguments = parser.parse_args()
    evidence = ProductionMapAcceptanceInput.model_validate_json(arguments.input.read_text())
    result = evaluate_production_map(evidence)
    payload = json.dumps(asdict(result), indent=2, sort_keys=True) + "\n"
    if arguments.report is not None:
        arguments.report.parent.mkdir(parents=True, exist_ok=True)
        arguments.report.write_text(payload)
    else:
        sys.stdout.write(payload)
    if not result.accepted:
        for failure in result.failures:
            sys.stderr.write(f"production-map QA failed: {failure}\n")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
