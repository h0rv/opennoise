"""Freeze or run bounded descriptor-neighbor export from existing FMA model artifacts."""

from __future__ import annotations

import argparse
import json
import os
import resource
import signal
import time
from pathlib import Path

os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"

from opennoise.ml.fma_related_tracks import (
    MAX_SECONDS,
    MEMORY_BYTES,
    build_related_tracks,
    freeze_protocol,
)


def _timeout(_signum: int, _frame: object) -> None:
    raise TimeoutError("descriptor retrieval wall-time budget exceeded")


def main() -> None:
    """Enforce fixed standalone process limits; never alter existing inference CLI guards."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("freeze", "run"))
    parser.add_argument("--pack", type=Path, required=True)
    parser.add_argument("--features", type=Path)
    parser.add_argument("--declaration", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    resource.setrlimit(resource.RLIMIT_AS, (MEMORY_BYTES, MEMORY_BYTES))
    resource.setrlimit(resource.RLIMIT_CPU, (MAX_SECONDS, MAX_SECONDS))
    signal.signal(signal.SIGALRM, _timeout)
    signal.alarm(MAX_SECONDS)
    started = time.monotonic()
    try:
        if args.action == "freeze":
            result = freeze_protocol(args.pack, args.declaration)
            print(  # noqa: T201 - compact machine-readable execution evidence.
                json.dumps(
                    {
                        "frozen_queries": len(result["query_ids"]),
                        "candidate_tracks": len(result["candidate_ids"]),
                    }
                )
            )
        else:
            if args.features is None or args.output is None:
                parser.error("run requires --features and --output")
            result = build_related_tracks(args.pack, args.features, args.declaration, args.output)
            print(  # noqa: T201 - compact machine-readable execution evidence.
                json.dumps(
                    {
                        "counts": result["counts"],
                        "elapsed_seconds": time.monotonic() - started,
                        "max_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                        "memory_limit_bytes": MEMORY_BYTES,
                        "cpu_wall_limit_seconds": MAX_SECONDS,
                    }
                )
            )
    finally:
        signal.alarm(0)


if __name__ == "__main__":
    main()
