"""Run the frozen local nested multiclass temperature diagnostic without acquisition."""

import argparse
import json
import os
import resource
import signal
import sys
from pathlib import Path


def main() -> None:
    """Bound resources before importing the numerical runtime."""
    for name in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
        os.environ[name] = "1"
    resource.setrlimit(resource.RLIMIT_AS, (1_000_000_000, 1_000_000_000))
    resource.setrlimit(resource.RLIMIT_CPU, (240, 240))
    signal.alarm(240)
    from opennoise.ml import jamendo_genre_temperature as study  # noqa: PLC0415

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("census", "evaluate", "replay"))
    for name in ("protocol", "prepared", "census", "baseline", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    for name in ("protocol", "identity", "census", "baseline"):
        parser.add_argument(f"--{name}-sha256", required=True)
    parser.add_argument("--inner-census", type=Path)
    parser.add_argument("--inner-census-sha256")
    parser.add_argument("--result-sha256")
    args = parser.parse_args()
    if (args.inner_census is None) != (args.inner_census_sha256 is None):
        parser.error("Inner census path and pin must be supplied together")
    if (args.stage != "census") != bool(args.inner_census and args.inner_census_sha256):
        parser.error(
            "evaluate/replay require an inner census and external pin; census forbids both"
        )
    if (args.stage == "replay") != bool(args.result_sha256):
        parser.error("Only replay requires --result-sha256")
    inputs = study.Inputs(
        args.protocol,
        args.protocol_sha256,
        args.prepared,
        args.identity_sha256,
        args.census,
        args.census_sha256,
        args.baseline,
        args.baseline_sha256,
    )
    if args.stage == "census":
        result = study.census(inputs, args.output)
    elif args.stage == "evaluate":
        result = study.evaluate(inputs, args.inner_census, args.inner_census_sha256, args.output)
    else:
        result = study.replay(
            inputs, args.inner_census, args.inner_census_sha256, args.output, args.result_sha256
        )["counts"]
    sys.stdout.write(json.dumps(result, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
