"""Build or independently replay a bounded exact-version native metadata registry."""

import argparse
import json
import os
import resource
import signal
import sys
from pathlib import Path


def main() -> None:
    """Expose disjoint source-build and frozen offline verification modes."""
    resource.setrlimit(resource.RLIMIT_AS, (1_000_000_000, 1_000_000_000))
    resource.setrlimit(resource.RLIMIT_CPU, (120, 120))
    signal.alarm(120)
    for name in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
        os.environ[name] = "1"
    from opennoise.ml import ab178_version_routing as routing  # noqa: PLC0415

    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_subparsers(dest="mode", required=True)
    build = modes.add_parser("build")
    for name in ("source", "plan", "output"):
        build.add_argument(f"--{name}", type=Path, required=True)
    for name in ("source-pin", "plan-pin"):
        build.add_argument(f"--{name}", required=True)
    verify = modes.add_parser("verify")
    verify.add_argument("--registry", type=Path, required=True)
    verify.add_argument("--manifest-pin", required=True)
    args = parser.parse_args()
    if args.mode == "build":
        sys.stdout.write(
            routing.build(args.source, args.source_pin, args.plan, args.plan_pin, args.output)
            + "\n"
        )
    else:
        sys.stdout.write(
            json.dumps(routing.verify(args.registry, args.manifest_pin)["counts"], sort_keys=True)
            + "\n"
        )


if __name__ == "__main__":
    main()
