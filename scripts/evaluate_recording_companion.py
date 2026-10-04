"""Freeze, run or replay component-held-out recording comparisons without network requests."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from opennoise.pipeline.recording_evaluation import Inputs, freeze, replay, run


def main() -> None:
    """Keep the explicit source and declaration paths outside all immutable source custody."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("freeze", "run", "replay"))
    parser.add_argument("--observations", required=True, type=Path)
    parser.add_argument("--sonic", required=True, type=Path)
    parser.add_argument("--companion", required=True, type=Path)
    parser.add_argument("--declaration", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--native-source", type=Path)
    parser.add_argument("--root", type=Path)
    args = parser.parse_args()
    if (args.native_source is None) != (args.root is None):
        parser.error("normalized inputs require both --native-source and --root")
    inputs = Inputs(args.observations, args.sonic, args.companion, args.native_source, args.root)
    if args.action == "freeze":
        result = freeze(inputs, args.declaration)
    else:
        if args.output is None:
            parser.error("run and replay require --output")
        result = (run if args.action == "run" else replay)(inputs, args.declaration, args.output)
    print(json.dumps(result, indent=2, sort_keys=True))  # noqa: T201 - CLI evidence.


if __name__ == "__main__":
    main()
