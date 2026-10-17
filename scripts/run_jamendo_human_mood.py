"""Offline research-only human-vote diagnostic; no acquisition or serving."""

import argparse
import os
import resource
import signal
from pathlib import Path

os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"
resource.setrlimit(resource.RLIMIT_AS, (1073741824, 1073741824))
resource.setrlimit(resource.RLIMIT_CPU, (120, 120))
signal.alarm(120)

from opennoise.ml.jamendo_human_mood import evaluate, prepare, replay  # noqa: E402

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    stages = parser.add_subparsers(dest="stage", required=True)
    first = stages.add_parser("prepare")
    for name in ("protocol", "receipt", "output"):
        first.add_argument("--" + name, type=Path, required=True)
    first.add_argument("--receipt-sha256", required=True)
    for name in ("evaluate", "replay"):
        child = stages.add_parser(name)
        child.add_argument("--prepared", type=Path, required=True)
        child.add_argument("--seal-sha256", required=True)
        child.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.stage == "prepare":
        prepare(args.protocol, args.receipt, args.receipt_sha256, args.output)
    elif args.stage == "evaluate":
        evaluate(args.prepared, args.seal_sha256, args.output)
    else:
        replay(args.prepared, args.seal_sha256, args.output)
