"""Build or verify a bounded standalone audio-free HTML from pinned local artifacts."""

import argparse
import json
import os
import resource
import signal
from pathlib import Path

os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["OMP_NUM_THREADS"] = "1"
resource.setrlimit(resource.RLIMIT_AS, (1073741824, 1073741824))
resource.setrlimit(resource.RLIMIT_CPU, (120, 120))
signal.alarm(120)

from opennoise.deployment.fma_audio_free_standalone import (  # noqa: E402
    build_standalone,
    verify_standalone,
)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("build", "verify"))
    for name in ("source", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    for name in ("model-pin", "discovery-pin"):
        parser.add_argument("--" + name, required=True)
    args = parser.parse_args()
    action = build_standalone if args.stage == "build" else verify_standalone
    result = action(args.source, args.output, args.model_pin, args.discovery_pin)
    print(json.dumps(result))  # noqa: T201 - machine-readable local artifact receipt.
