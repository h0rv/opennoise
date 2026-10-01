"""Independently evaluate a frozen local source-topic artifact."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from opennoise.analysis.emergent_community_evaluation import evaluate_topic_run


def main() -> None:
    """Require a complete immutable input run and a fresh local evaluation file."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-directory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = evaluate_topic_run(directory=args.model_directory, output=args.output)
    print(json.dumps(report, indent=2))  # noqa: T201 - explicit diagnostic CLI output.


if __name__ == "__main__":
    main()
