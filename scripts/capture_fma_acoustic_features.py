"""Bounded FMA Librosa member capture, or full offline native CSV projection replay."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from opennoise.ingest.fma_features import capture_features, project_feature_stream


def main() -> None:
    """Use fresh outputs without modifying the retained source captures."""
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="command", required=True)
    capture = subcommands.add_parser("capture")
    capture.add_argument("--metadata-source", type=Path, required=True)
    capture.add_argument("--declaration", type=Path, required=True)
    capture.add_argument("--output", type=Path, required=True)
    replay = subcommands.add_parser("project")
    replay.add_argument("--source", type=Path, required=True)
    replay.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = (
        capture_features(args.metadata_source, args.output, args.declaration)
        if args.command == "capture"
        else project_feature_stream(args.source, args.output)
    )
    sys.stdout.write(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    main()
