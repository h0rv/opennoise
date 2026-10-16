"""Bounded offline projection of already captured FMA historical popularity."""

from __future__ import annotations

import argparse
import os
import resource
import signal
from pathlib import Path


def main() -> None:
    """Apply the existing envelope before numerical imports or source verification."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    resource.setrlimit(resource.RLIMIT_AS, (1_000_000_000, 1_000_000_000))
    resource.setrlimit(resource.RLIMIT_CPU, (120, 120))
    signal.alarm(120)
    for name in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
        os.environ[name] = "1"
    from opennoise.ml.fma_waveform_popularity import project  # noqa: PLC0415 -- limits first.

    project(args.source, args.manifest, args.output)


if __name__ == "__main__":
    main()
