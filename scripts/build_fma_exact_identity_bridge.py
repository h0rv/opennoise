"""Capture and replay native MusicBrainz FMA URL assertions, never artist names."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from opennoise.serving.metadata.fma_identity_bridge import (
    capture,
    project,
    write,
)


def main() -> int:
    """Capture into a new directory or independently replay an existing source pack."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    if not args.verify:
        capture(args.output)
        write(args.output / "bridge.json", project(args.output, args.source))
    result = project(args.output, args.source)
    if result != json.loads((args.output / "bridge.json").read_bytes()):
        raise ValueError("bridge projection differs from original source replay")
    sys.stdout.write(
        json.dumps(
            {
                kind: {
                    "eligible": result[kind]["eligible"],
                    "resolved": len(result[kind]["resolved"]),
                    "conflicts": len(result[kind]["conflicts"]),
                    "unresolved": result[kind]["unresolved"],
                }
                for kind in ("artist", "recording")
            }
        )
        + "\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
