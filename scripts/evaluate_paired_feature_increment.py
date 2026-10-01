"""Compare frozen models on old and augmented source features with shared targets."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from opennoise.analysis.paired_feature_increment import evaluate_paired_increment


def main() -> None:
    """Require two frozen source inputs and a fresh local research destination."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--old-features", required=True, type=Path)
    parser.add_argument("--augmented-features", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    report = evaluate_paired_increment(
        old=args.old_features, augmented=args.augmented_features, output=args.output
    )
    print(json.dumps(report, indent=2))  # noqa: T201 - explicit local evaluation CLI.


if __name__ == "__main__":
    main()
