"""Bounded research-only genre-to-human-style development; no reserved confirmation."""

import argparse
import json
import os
import resource
import signal
import sys
from pathlib import Path


def main() -> None:
    """Separate a zero-fit source census, fixed20fit producer and20fit verification."""
    for key in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
        os.environ[key] = "1"
    resource.setrlimit(resource.RLIMIT_AS, (1_000_000_000, 1_000_000_000))
    resource.setrlimit(resource.RLIMIT_CPU, (120, 120))
    signal.alarm(120)
    from opennoise.ml import jamendo_style_prediction as study  # noqa: PLC0415

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("census", "run", "replay"))
    for key in ("metadata", "human", "protocol", "output"):
        parser.add_argument("--" + key, type=Path, required=True)
    parser.add_argument("--protocol-sha256", required=True)
    parser.add_argument("--census", type=Path)
    parser.add_argument("--census-sha256")
    parser.add_argument("--result-sha256")
    args = parser.parse_args()
    if (args.census is None) != (args.census_sha256 is None) or (args.stage != "census") != bool(
        args.census and args.census_sha256
    ):
        parser.error("Only run/replay require both census path and external pin")
    if (args.stage == "replay") != bool(args.result_sha256):
        parser.error("Only replay requires external result pin")
    inputs = study.Inputs(args.metadata, args.human, args.protocol, args.protocol_sha256)
    if args.stage == "census":
        result = study.census(inputs, args.output)
    elif args.stage == "run":
        try:
            result = study.run(inputs, args.census, args.census_sha256, args.output)
        except study.LogisticContractError as error:
            sys.stderr.write(
                json.dumps(
                    {
                        "status": "stopped_logistic_contract",
                        "protocol_sha256": study.PROTOCOL,
                        "diagnostics": error.diagnostics,
                    },
                    allow_nan=False,
                )
                + "\n"
            )
            raise SystemExit(1) from None
    else:
        result = study.replay(
            inputs, args.census, args.census_sha256, args.output, args.result_sha256
        )
    sys.stdout.write(json.dumps(result) + "\n")


if __name__ == "__main__":
    main()
