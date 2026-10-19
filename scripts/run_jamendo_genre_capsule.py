"""Build a local research capsule or infer from new caller-supplied tag profiles."""

import argparse
import json
import os
import resource
import signal
import sys
from pathlib import Path


def main() -> None:
    """Enforce process bounds before importing any numerical or builder modules."""
    for name in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
        os.environ[name] = "1"
    resource.setrlimit(resource.RLIMIT_AS, (1_000_000_000, 1_000_000_000))
    resource.setrlimit(resource.RLIMIT_CPU, (120, 120))
    signal.alarm(120)
    parser = argparse.ArgumentParser(description=__doc__)
    stages = parser.add_subparsers(dest="stage", required=True)
    build = stages.add_parser("build")
    for name in (
        "metadata",
        "outer-models",
        "selected-models",
        "study-receipt",
        "protocol",
        "output",
    ):
        build.add_argument("--" + name, type=Path, required=True)
    for name in ("study-receipt", "protocol"):
        build.add_argument(f"--{name}-sha256", required=True)
    infer = stages.add_parser("infer")
    for name in ("capsule", "queries", "output"):
        infer.add_argument("--" + name, type=Path, required=True)
    for name in ("capsule", "queries"):
        infer.add_argument(f"--{name}-sha256", required=True)
    args = parser.parse_args()
    if args.stage == "build":
        from opennoise.ml import jamendo_genre_capsule as builder  # noqa: PLC0415

        pin = builder.build(
            args.metadata,
            args.outer_models,
            args.selected_models,
            args.study_receipt,
            args.study_receipt_sha256,
            args.protocol,
            args.protocol_sha256,
            args.output,
        )
    else:
        from opennoise.ml import jamendo_genre_inference as pure  # noqa: PLC0415

        pin = pure.infer_file(
            args.capsule, args.capsule_sha256, args.queries, args.queries_sha256, args.output
        )
    sys.stdout.write(json.dumps({"sha256": pin}) + "\n")


if __name__ == "__main__":
    main()
