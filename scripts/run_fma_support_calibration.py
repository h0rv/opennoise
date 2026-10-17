"""Run one sealed original-training CV stage, without changing inherited guards."""

import argparse
import json
import os
import resource
import signal
from pathlib import Path

os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"
resource.setrlimit(resource.RLIMIT_AS, (1000000000, 1000000000))
resource.setrlimit(resource.RLIMIT_CPU, (120, 120))
signal.alarm(120)

from opennoise.ml.fma_support_experiment import (  # noqa: E402
    ARMS,
    calibrate,
    fit,
    freeze,
    score,
)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="stage", required=True)
    freezing = sub.add_parser("freeze")
    for name in ("protocol", "input-seal", "output"):
        freezing.add_argument("--" + name, type=Path, required=True)
    for stage in ("fit", "calibrate", "score"):
        child = sub.add_parser(stage)
        child.add_argument("--seal", type=Path, required=True)
        child.add_argument("--output", type=Path, required=True)
        if stage == "fit":
            child.add_argument("--arm", choices=ARMS, required=True)
    args = parser.parse_args()
    if args.stage == "freeze":
        freeze(args.protocol, args.input_seal, args.output)
    elif args.stage == "fit":
        fit(args.seal, args.output, args.arm)
    elif args.stage == "calibrate":
        calibrate(args.seal, args.output)
    else:
        score(args.seal, args.output)
    print(json.dumps({"status": "pass", "stage": args.stage, "output": str(args.output)}))  # noqa: T201
