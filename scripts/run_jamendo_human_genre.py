"""Run a bounded local noncommercial nine-class human-genre metadata diagnostic."""

import argparse
import json
import os
import resource
import signal
import sys
from pathlib import Path


def main() -> None:
    """Separate identity preparation, no-fit census, evaluation and exact replay."""
    for name in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
        os.environ[name] = "1"
    resource.setrlimit(resource.RLIMIT_AS, (1_000_000_000, 1_000_000_000))
    resource.setrlimit(resource.RLIMIT_CPU, (120, 120))
    signal.alarm(120)
    from opennoise.ml import jamendo_human_genre as genre  # noqa: PLC0415

    parser = argparse.ArgumentParser(description=__doc__)
    stages = parser.add_subparsers(dest="stage", required=True)
    prepare = stages.add_parser("prepare")
    prepare.add_argument("--protocol", type=Path, required=True)
    prepare.add_argument("--receipt", type=Path, required=True)
    prepare.add_argument("--receipt-sha256", required=True)
    prepare.add_argument("--output", type=Path, required=True)
    for stage in ("census", "evaluate", "replay"):
        sub = stages.add_parser(stage)
        sub.add_argument("--prepared", type=Path, required=True)
        sub.add_argument("--seal-sha256", required=True)
        sub.add_argument("--output", type=Path, required=True)
        if stage in {"evaluate", "replay"}:
            sub.add_argument("--census", type=Path, required=True)
            sub.add_argument("--census-seal-sha256", required=True)
        if stage == "replay":
            sub.add_argument("--result-receipt-sha256", required=True)
    args = parser.parse_args()
    if args.stage == "prepare":
        result = genre.prepare(args.protocol, args.receipt, args.receipt_sha256, args.output)
    elif args.stage == "census":
        result = genre.census(args.prepared, args.seal_sha256, args.output)
    elif args.stage == "evaluate":
        result = genre.evaluate(
            args.prepared, args.seal_sha256, args.census, args.census_seal_sha256, args.output
        )
    else:
        result = genre.replay(
            args.prepared,
            args.seal_sha256,
            args.census,
            args.census_seal_sha256,
            args.output,
            args.result_receipt_sha256,
        )["counts"]
    sys.stdout.write(json.dumps(result, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
