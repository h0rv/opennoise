"""Replay the prespecified native FMA acoustic arm; all source artifacts are read-only."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from opennoise.ml.fma_acoustic_baseline import evaluate_native_corpus


def main() -> None:
    """Require explicit captured source projections, declaration and fresh output directory."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--features", type=Path, required=True)
    parser.add_argument("--declaration", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = evaluate_native_corpus(args.metadata, args.features, args.declaration, args.output)
    sys.stdout.write(
        json.dumps(
            {
                "output": str(args.output),
                "elapsed_seconds": report["elapsed_seconds"],
                "coverage": report["coverage"],
                "test": {
                    name: {k: value for k, value in arm.items() if k != "per_label"}
                    for name, arm in report["evaluation"]["test"].items()
                },
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
