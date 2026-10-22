"""Replay public source packs into the local OpenNoise catalog/map demonstration."""

import argparse
import json
import os
import resource
import signal
from pathlib import Path


def main() -> None:
    """Build a fresh local-only artifact without acquisition or deployment."""
    for name in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
        os.environ[name] = "1"
    resource.setrlimit(resource.RLIMIT_AS, (1_000_000_000, 1_000_000_000))
    resource.setrlimit(resource.RLIMIT_CPU, (120, 120))
    signal.alarm(120)
    from opennoise.pipeline.catalog_demo import build  # noqa: PLC0415 -- Bound heavy imports.

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.root, args.output), indent=2))  # noqa: T201


if __name__ == "__main__":
    main()
