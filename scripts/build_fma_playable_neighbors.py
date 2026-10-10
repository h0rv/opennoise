"""Freeze/build/replay neighbors solely among already attached native audio, offline."""

from __future__ import annotations

import argparse
import json
import os
import resource
import signal
import time
from pathlib import Path


def main() -> None:
    """Enforce unchanged 120s/one-GB bounds before importing numerical libraries."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("freeze", "build", "verify"))
    for flag in ("audio", "pack", "features"):
        parser.add_argument(f"--{flag}", type=Path, required=True)
    parser.add_argument("--declaration", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    for key in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
        os.environ[key] = "1"
    resource.setrlimit(resource.RLIMIT_AS, (1_000_000_000, 1_000_000_000))
    resource.setrlimit(resource.RLIMIT_CPU, (120, 120))
    signal.alarm(120)
    from opennoise.ml.fma_playable_neighbors import (  # noqa: PLC0415 -- limits before NumPy import.
        build,
        freeze_protocol,
        replay,
    )

    started = time.monotonic()
    if args.stage == "freeze":
        if args.declaration is None:
            parser.error("freeze requires --declaration")
        result = freeze_protocol(args.audio, args.pack, args.features, args.declaration)
    elif args.stage == "build":
        if args.declaration is None or args.output is None:
            parser.error("build requires --declaration and --output")
        result = build(args.audio, args.pack, args.features, args.declaration, args.output)
    else:
        if args.output is None:
            parser.error("verify requires --output")
        result = replay(args.audio, args.pack, args.features, args.output)
    signal.alarm(0)
    print(  # noqa: T201 -- execution evidence.
        json.dumps(
            {
                "revision": result.get("revision"),
                "counts": result.get("counts"),
                "elapsed_seconds": time.monotonic() - started,
                "peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
