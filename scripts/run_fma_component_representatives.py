"""Run bounded, fixed second-representative stages without refitting normalization."""

import argparse
import json
import os
import resource
import signal
import time
from pathlib import Path

os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"
resource.setrlimit(resource.RLIMIT_AS, (1_000_000_000, 1_000_000_000))
resource.setrlimit(resource.RLIMIT_CPU, (120, 120))
signal.alarm(120)

from opennoise.ml.fma_component_representatives import (  # noqa: E402
    replay_fold,
    replay_summary,
    run_fold,
    summarize_run,
)
from opennoise.ml.fma_component_representatives_custody import freeze  # noqa: E402

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="stage", required=True)
    freezing = commands.add_parser("freeze")
    for name in ("protocol", "original-seal", "source", "run", "output"):
        freezing.add_argument("--" + name, type=Path, required=True)
    for name in ("fold", "summary", "replay-fold", "replay-summary"):
        command = commands.add_parser(name)
        command.add_argument("--seal", type=Path, required=True)
        command.add_argument("--output", type=Path, required=True)
        if name in {"fold", "replay-fold"}:
            command.add_argument("--fold", type=int, choices=range(5), required=True)
    args = parser.parse_args()
    started = time.monotonic()
    if args.stage == "freeze":
        freeze(args.protocol, args.original_seal, args.source, args.run, args.output)
    elif args.stage == "fold":
        run_fold(args.seal, args.output, args.fold)
    elif args.stage == "summary":
        summarize_run(args.seal, args.output)
    elif args.stage == "replay-fold":
        replay_fold(args.seal, args.output, args.fold)
    else:
        replay_summary(args.seal, args.output)

    print(  # noqa: T201 - machine-readable bounded-stage evidence.
        json.dumps(
            {
                "stage": args.stage,
                "status": "pass",
                "elapsed_seconds": time.monotonic() - started,
                "peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
            }
        )
    )
