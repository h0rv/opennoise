"""Export, verify and run an explicit frozen encoder without fitting or calibration."""

import argparse
import json
import os
import resource
import signal
import sys
from pathlib import Path

os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"
resource.setrlimit(resource.RLIMIT_AS, (1_000_000_000, 1_000_000_000))
# Only full native CSV validation uses the separately approved projection budget.
source_scan = len(sys.argv) > 1 and sys.argv[1] == "export-source-queries"
resource.setrlimit(resource.RLIMIT_CPU, (300, 300) if source_scan else (120, 120))
signal.alarm(360 if source_scan else 120)

from opennoise.ml.fma_encoder_bundle import encoded, infer, load_bundle, sha  # noqa: E402
from opennoise.ml.fma_encoder_export import (  # noqa: E402
    export_bundle,
    export_queries,
    fresh_destination,
    import_queries,
)
from opennoise.ml.fma_source_queries import export_source_queries  # noqa: E402


def main() -> None:  # noqa: C901, PLR0912, PLR0915 - fixed CLI subcommands.
    """Require external pins and fresh outputs; never follow historical paths for inference."""
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    export = commands.add_parser("export-bundle")
    for name in ("pipeline", "inputs", "output"):
        export.add_argument("--" + name, type=Path, required=True)
    for name in ("plan-sha256", "checkpoint-sha256", "arm"):
        export.add_argument("--" + name, required=True)
    export.add_argument("--fold", type=int, choices=range(5), required=True)
    for command in (
        "export-queries",
        "export-source-queries",
        "import-queries",
        "infer",
        "replay",
        "verify",
    ):
        child = commands.add_parser(command)
        child.add_argument("--bundle", type=Path, required=True)
        child.add_argument("--bundle-sha256", required=True)
        if command in {"export-queries", "export-source-queries", "import-queries", "infer"}:
            child.add_argument("--output", type=Path, required=True)
        if command == "export-queries":
            child.add_argument("--bank", type=Path, required=True)
            child.add_argument("--track-id", type=int, action="append", required=True)
        if command == "export-source-queries":
            child.add_argument("--source", type=Path, required=True)
            child.add_argument("--source-receipt-sha256", required=True)
            child.add_argument("--track-id", type=int, action="append", required=True)
        if command == "import-queries":
            child.add_argument("--source", type=Path, required=True)
            child.add_argument("--source-sha256", required=True)
        if command in {"infer", "replay"}:
            child.add_argument("--allow-unverified-neighbors", action="store_true")
            child.add_argument("--queries", type=Path, required=True)
            child.add_argument("--query-sha256", required=True)
        if command == "replay":
            child.add_argument("--result", type=Path, required=True)
            child.add_argument("--result-sha256", required=True)
    args = parser.parse_args()
    if args.command == "export-bundle":
        pin = export_bundle(
            args.pipeline,
            args.inputs,
            args.plan_sha256,
            args.checkpoint_sha256,
            args.output,
            arm=args.arm,
            fold=args.fold,
        )
    elif args.command == "export-queries":
        pin = export_queries(args.bundle, args.bundle_sha256, args.bank, args.track_id, args.output)
    elif args.command == "export-source-queries":
        pin = export_source_queries(
            args.bundle,
            args.bundle_sha256,
            args.source,
            args.source_receipt_sha256,
            args.track_id,
            args.output,
        )
    elif args.command == "import-queries":
        pin = import_queries(
            args.bundle, args.bundle_sha256, args.source, args.source_sha256, args.output
        )
    elif args.command == "verify":
        load_bundle(args.bundle, args.bundle_sha256)
        pin = args.bundle_sha256
    else:
        data = encoded(
            infer(
                args.bundle,
                args.bundle_sha256,
                args.queries,
                args.query_sha256,
                allow_unverified_neighbors=args.allow_unverified_neighbors,
            )
        )
        if args.command == "infer":
            fresh_destination(args.output, (args.bundle, args.queries))
            with args.output.open("xb") as stream:
                stream.write(data)
            pin = sha(args.output)
        else:
            if (
                any(p.is_symlink() for p in (args.result, *args.result.parents))
                or args.result.stat().st_size > 2_000_000  # noqa: PLR2004 - output contract cap.
                or sha(args.result) != args.result_sha256
                or args.result.read_bytes() != data
            ):
                raise ValueError("Replayed inference differs from pinned result")
            pin = args.result_sha256
    sys.stdout.write(json.dumps({"status": "pass", "command": args.command, "sha256": pin}) + "\n")


if __name__ == "__main__":
    main()
