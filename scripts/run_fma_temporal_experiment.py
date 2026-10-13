"""Freeze, project, or fit one offline native mean+std diagnostic experiment."""

import argparse
import json
import os
import resource
import signal
from pathlib import Path

os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["OMP_NUM_THREADS"] = "1"
resource.setrlimit(resource.RLIMIT_AS, (1_000_000_000, 1_000_000_000))

from opennoise.ml.fma_temporal_experiment import (  # noqa: E402 -- resource guards before numerical imports.
    freeze,
    project,
    run,
)

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("command", choices=("freeze", "project", "run"))
parser.add_argument("--root", type=Path)
parser.add_argument("--declaration", type=Path, required=True)
parser.add_argument("--projection", type=Path)
parser.add_argument("--output", type=Path)
args = parser.parse_args()
if args.command == "run":
    resource.setrlimit(resource.RLIMIT_CPU, (120, 120))
    signal.alarm(120)
if args.command == "freeze":
    result = freeze(args.root, args.declaration)
elif args.command == "project":
    result = project(args.declaration, args.output)
else:
    result = run(args.declaration, args.projection, args.output)
print(json.dumps(result.get("comparison", result), indent=2))  # noqa: T201 -- explicit offline receipt.
