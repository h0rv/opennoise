"""Staged bounded FMA audio capture. Network stages require prior explicit user approval."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from opennoise.serving.metadata.fma_listening64 import capture, freeze, probe, verify


def main() -> None:
    """Probe/capture use network; freeze/verify only replay retained local artifacts."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("probe", "freeze", "capture", "verify"))
    parser.add_argument("--source", type=Path)
    parser.add_argument("--probe", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.stage == "probe":
        if args.output is None:
            parser.error("probe requires --output (network; prior audio approval required)")
        result = probe(args.output)
    else:
        if args.source is None:
            parser.error("--source is required")
        if args.stage == "freeze":
            if args.probe is None:
                parser.error("freeze requires --probe")
            result = freeze(args.source, args.probe)
        elif args.stage == "capture":
            if args.probe is None or args.output is None:
                parser.error(
                    "capture requires --probe and --output (network; prior approval required)"
                )
            result = capture(args.source, args.probe, args.output)
        else:
            if args.output is None:
                parser.error("verify requires --output")
            result = verify(args.output, args.source)
    print(json.dumps(result, indent=2, sort_keys=True))  # noqa: T201 - explicit acquisition/replay receipt.


if __name__ == "__main__":
    main()
