"""Replay an untuned unconditional prior beside the preserved source experiment."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from opennoise.ml.wikidata_unconditional_prior import diagnose


def main() -> None:
    """Create separately named post-inspection diagnostic evidence."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    sys.stdout.write(json.dumps(diagnose(args.model, args.output), indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
