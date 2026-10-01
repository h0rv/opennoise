"""Build local overlapping music communities from source-bound feature JSONL."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from opennoise.ml.emergent_topics import build_emergent_topics


def main() -> int:
    """Construct auditable broad, sub, and micro topic candidates offline."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--features", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = build_emergent_topics(features_path=args.features, output=args.output)
    sys.stdout.write(json.dumps(report["coverage"], indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
