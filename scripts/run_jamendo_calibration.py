"""Bounded offline research calibration; never acquisition or serving."""

import argparse
import os
import resource
import signal
from pathlib import Path

for variable in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ[variable] = "1"
resource.setrlimit(resource.RLIMIT_AS, (1_000_000_000, 1_000_000_000))
resource.setrlimit(resource.RLIMIT_CPU, (120, 120))
signal.alarm(120)
from opennoise.ml.jamendo_calibration import evaluate, freeze, replay  # noqa: E402

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    stages = parser.add_subparsers(dest="stage", required=True)
    first = stages.add_parser("freeze")
    for name in ("prepared", "protocol", "output"):
        first.add_argument("--" + name, type=Path, required=True)
    for name in ("evaluate", "replay"):
        child = stages.add_parser(name)
        for key in ("sealed", "output"):
            child.add_argument("--" + key, type=Path, required=True)
        child.add_argument("--seal-sha256", required=True)
    args = parser.parse_args()
    if args.stage == "freeze":
        freeze(args.prepared, args.protocol, args.output)
    elif args.stage == "evaluate":
        evaluate(args.sealed, args.seal_sha256, args.output)
    else:
        replay(args.sealed, args.seal_sha256, args.output)
