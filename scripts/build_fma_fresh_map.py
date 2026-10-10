"""Freeze, build or numerically replay the separate fresh-source descriptor map offline."""

from __future__ import annotations

import argparse
import json
import os
import resource
import signal
import time
from pathlib import Path


def main() -> None:
    """Enforce one BLAS thread, 120 seconds and one GB before loading numerical code."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("freeze", "build", "verify"))
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--declaration", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    for key in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
        os.environ[key] = "1"
    resource.setrlimit(resource.RLIMIT_AS, (1_000_000_000, 1_000_000_000))
    resource.setrlimit(resource.RLIMIT_CPU, (120, 120))
    signal.alarm(120)
    from opennoise.ml.fma_fresh_map import (  # noqa: PLC0415 -- set process limits before NumPy import.
        build_fresh_map,
        freeze_fresh_map,
        replay_fresh_map,
    )

    start = time.monotonic()
    if args.stage == "freeze":
        if args.declaration is None:
            parser.error("freeze requires --declaration")
        result = freeze_fresh_map(args.source_root, args.declaration)
    elif args.stage == "build":
        if args.declaration is None or args.output is None:
            parser.error("build requires --declaration and --output")
        result = build_fresh_map(args.source_root, args.declaration, args.output)
    else:
        if args.output is None:
            parser.error("verify requires --output")
        result = replay_fresh_map(args.source_root, args.output)
    signal.alarm(0)
    print(  # noqa: T201 -- execution evidence.
        json.dumps(
            {
                "result": result,
                "elapsed_seconds": time.monotonic() - start,
                "peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
