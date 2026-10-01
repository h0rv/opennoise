"""Capture a bounded exact-recording AcousticBrainz metadata pilot, or verify it offline."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

import httpx

from opennoise.ingest.acousticbrainz.capture import (
    capture_benchmarks,
    reproject_benchmarks,
    verify_benchmarks,
    verify_reprojection,
)


async def _capture(args: argparse.Namespace) -> dict[str, object]:
    async with httpx.AsyncClient(timeout=20.0, follow_redirects=False) as client:
        return await capture_benchmarks(
            benchmark_source=args.benchmark_source, directory=args.output, client=client
        )


def main() -> int:
    """Require a fresh local capture destination or replay the existing bytes without HTTP."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--benchmark-source",
        type=Path,
        default=Path(".cache/emergent-topics/bulk-adaptive-postfit-audit-20260930-v1.json"),
    )
    parser.add_argument("--output", required=True, type=Path)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--verify-only", action="store_true")
    mode.add_argument("--verify-projection", action="store_true")
    mode.add_argument("--reproject-from", type=Path)
    args = parser.parse_args()
    if args.verify_only:
        result = verify_benchmarks(directory=args.output)
    elif args.verify_projection:
        result = verify_reprojection(directory=args.output)
    elif args.reproject_from:
        result = reproject_benchmarks(source_directory=args.reproject_from, directory=args.output)
    else:
        result = asyncio.run(_capture(args))
    sys.stdout.write(json.dumps(result, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
