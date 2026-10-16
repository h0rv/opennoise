"""Freeze/build a local method-blind pilot or summarize real supplied responses."""

import argparse
import json
import os
import resource
import signal
from pathlib import Path

os.environ["OPENBLAS_NUM_THREADS"] = "1"
resource.setrlimit(resource.RLIMIT_AS, (1_000_000_000, 1_000_000_000))
resource.setrlimit(resource.RLIMIT_CPU, (120, 120))
signal.alarm(120)
from opennoise.deployment.fma_listening_pilot import (  # noqa: E402
    build_pilot,
    freeze_pilot,
    summarize_files,
)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    freeze = sub.add_parser("freeze")
    build = sub.add_parser("build")
    for command in (freeze, build):
        command.add_argument("--candidate", type=Path, required=True)
        command.add_argument("--baseline", type=Path, required=True)
        command.add_argument("--output", type=Path, required=True)
    freeze.add_argument("--baseline-inventory-sha256", required=True)
    freeze.add_argument("--design", type=Path, required=True)
    build.add_argument("--seal", type=Path, required=True)
    build.add_argument("--seal-sha256", required=True)
    summary = sub.add_parser("summarize")
    summary.add_argument("--pilot", type=Path, required=True)
    summary.add_argument("--mapping-sha256", required=True)
    summary.add_argument("--response", type=Path, action="append", default=[])
    summary.add_argument("--distinct-participants-confirmed", action="store_true")
    summary.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "freeze":
        result = freeze_pilot(
            args.candidate, args.baseline, args.baseline_inventory_sha256, args.design, args.output
        )
    elif args.command == "build":
        result = build_pilot(
            args.candidate, args.baseline, args.seal, args.seal_sha256, args.output
        )
    else:
        result = summarize_files(
            args.pilot,
            args.mapping_sha256,
            args.response,
            args.output,
            distinct_participants_confirmed=args.distinct_participants_confirmed,
        )
    print(json.dumps(result, sort_keys=True))  # noqa: T201 -- explicit local CLI output.
