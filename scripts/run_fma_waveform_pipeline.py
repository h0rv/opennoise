"""Freeze, run or verify the permitted55 offline waveform pipeline."""

from __future__ import annotations

import argparse
import json
import os
import resource
import signal
import time
from pathlib import Path


def main() -> None:
    """Apply the unchanged process envelope before importing numeric code."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("freeze", "run", "verify"))
    for name in ("site", "folds", "protocol", "declaration", "output"):
        parser.add_argument(f"--{name}", type=Path)
    args = parser.parse_args()
    resource.setrlimit(resource.RLIMIT_AS, (1_000_000_000, 1_000_000_000))
    resource.setrlimit(resource.RLIMIT_CPU, (120, 120))
    signal.alarm(120)
    for name in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
        os.environ[name] = "1"
    started = time.monotonic()
    from opennoise.ml import (  # noqa: PLC0415 -- limits before numerical imports.
        fma_waveform_pipeline as pipeline,
    )

    if args.operation == "freeze":
        result = pipeline.freeze(args.site, args.folds, args.protocol, args.declaration)
    elif args.operation == "run":
        result = pipeline.run(args.declaration, args.output)
    else:
        result = pipeline.validate_waveform_pack(args.output, args.site / "manifest.json")
    print(  # noqa: T201 -- CLI evidence summary.
        json.dumps(
            {
                "revision": result["revision"],
                "elapsed_seconds": time.monotonic() - started,
                "peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
            }
        )
    )


if __name__ == "__main__":
    main()
