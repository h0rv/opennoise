"""Staged bounded fma_large capture. Probe/capture require approved source access."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from opennoise.serving.metadata import fma_large32


def main() -> None:
    """Keep each network stage explicit and offline freeze/verify separately callable."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("probe", "freeze", "capture", "verify"))
    for name in ("source", "baseline", "probe", "output"):
        parser.add_argument(f"--{name}", type=Path)
    args = parser.parse_args()
    if args.stage == "probe":
        if args.output is None:
            parser.error("probe requires --output")
        result = fma_large32.probe(args.output)
    else:
        if args.source is None or args.baseline is None:
            parser.error("offline source and --baseline required")
        if args.stage == "freeze":
            if args.probe is None:
                parser.error("freeze requires --probe")
            result = fma_large32.freeze(args.source, args.baseline, args.probe)
        elif args.stage == "capture":
            if args.probe is None or args.output is None:
                parser.error("capture requires --probe and --output")
            result = fma_large32.capture(args.source, args.baseline, args.probe, args.output)
        else:
            if args.output is None:
                parser.error("verify requires --output")
            result = fma_large32.verify(args.output, args.source, args.baseline)
    print(  # noqa: T201 -- compact execution evidence.
        json.dumps(
            {
                "revision": result["revision"],
                "requests": len(result.get("captures", [])),
                "clips": len(result.get("tracks", [])),
                "new_genres": result.get("new_genres", []),
                "response_bytes": sum(row["bytes"] for row in result.get("captures", [])),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
