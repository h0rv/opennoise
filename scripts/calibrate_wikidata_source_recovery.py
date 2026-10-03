"""Run a training-only source recovery event experiment after explicit run authorization."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from opennoise.ml.wikidata_source_recovery_calibration import prepare, run


def main() -> None:
    """Require exact original source/selection pins and a new exclusive output path."""
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("prepare", "run"):
        command = commands.add_parser(name)
        command.add_argument("--source", required=True, type=Path)
        command.add_argument("--source-receipt-sha256", required=True)
        command.add_argument("--selection", required=True, type=Path)
        command.add_argument("--selection-receipt-sha256", required=True)
        command.add_argument("--output", required=True, type=Path)
        if name == "run":
            command.add_argument("--preparation", required=True, type=Path)
            command.add_argument("--preparation-receipt-sha256", required=True)
    args = parser.parse_args()
    if args.command == "prepare":
        report = prepare(
            args.source,
            args.source_receipt_sha256,
            args.selection,
            args.selection_receipt_sha256,
            args.output,
        )
    else:
        report = run(
            args.source,
            args.source_receipt_sha256,
            args.selection,
            args.selection_receipt_sha256,
            args.output,
            preparation=args.preparation,
            preparation_pin=args.preparation_receipt_sha256,
        )
    sys.stdout.write(json.dumps(report, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
