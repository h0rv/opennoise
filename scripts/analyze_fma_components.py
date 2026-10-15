"""Run a declared fixed-ranking diagnostic under inherited resource limits."""

import argparse
import json
import os
import resource
import signal
from pathlib import Path

os.environ["OPENBLAS_NUM_THREADS"] = "1"
resource.setrlimit(resource.RLIMIT_AS, (1000000000, 1000000000))
resource.setrlimit(resource.RLIMIT_CPU, (120, 120))
signal.alarm(120)

from opennoise.ml.fma_component_diagnostics import run  # noqa: E402

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("declaration", "baseline", "metadata", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    print(  # noqa: T201
        json.dumps(run(args.declaration, args.baseline, args.metadata, args.output), indent=2)
    )
