"""Seal a metadata-only connected artist/album/duplicate evaluation split."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from opennoise.analysis.connected_split import seal_source_split, verify_source_split


def main() -> int:
    """Read explicit identity records and write a fresh source-bound split report."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--seed", required=True)
    parser.add_argument("--input-format", choices=("identities", "numeric"), default="identities")
    parser.add_argument(
        "--verify", action="store_true", help="replay the existing output; no write"
    )
    args = parser.parse_args()
    source = args.source.read_bytes()
    if args.verify:
        report = verify_source_split(
            source,
            json.loads(args.output.read_bytes()),
            seed=args.seed,
            source_format=args.input_format,
        )
    else:
        report = seal_source_split(source, seed=args.seed, source_format=args.input_format)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as output:
            output.write(json.dumps(report, indent=2, sort_keys=True) + "\n")
    sys.stdout.write(json.dumps({"output": str(args.output), "audit": report["audit"]}) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
