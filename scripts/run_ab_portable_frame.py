"""Export and replay a pinned AB178 metadata frame without audio or source acquisition."""

import argparse
import hashlib
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
resource.setrlimit(resource.RLIMIT_CPU, (120, 120))
signal.alarm(120)

from opennoise.ml import ab178_portable as portable  # noqa: E402
from opennoise.ml.ab178_artist_export import export_artists  # noqa: E402


def main() -> None:  # noqa: C901, PLR0912 - fixed explicit subcommands.
    """Require external input pins and fresh outputs for every portable stage."""
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    export = commands.add_parser("export-bundle")
    for name in ("source", "bank", "contract"):
        export.add_argument("--" + name, type=Path, required=True)
        suffix = "-sha256" if name == "contract" else "-receipt-sha256"
        export.add_argument("--" + name + suffix, required=True)
    export.add_argument("--fold", type=int, choices=range(3), required=True)
    export.add_argument("--output", type=Path, required=True)
    for name in ("export-artists", "export-queries", "infer", "replay", "verify"):
        child = commands.add_parser(name)
        child.add_argument("--bundle", type=Path, required=True)
        child.add_argument("--bundle-sha256", required=True)
        if name in {"export-artists", "export-queries", "infer"}:
            child.add_argument("--output", type=Path, required=True)
        if name in {"export-artists", "export-queries"}:
            child.add_argument("--source", type=Path, required=True)
            child.add_argument("--source-receipt-sha256", required=True)
            if name == "export-queries":
                child.add_argument("--recording-mbid", action="append", required=True)
        if name in {"infer", "replay"}:
            child.add_argument("--queries", type=Path, required=True)
            child.add_argument("--query-sha256", required=True)
        if name == "replay":
            child.add_argument("--result", type=Path, required=True)
            child.add_argument("--result-sha256", required=True)
    args = parser.parse_args()
    if args.command == "export-bundle":
        pin = portable.export_bundle(
            args.source,
            args.source_receipt_sha256,
            args.bank,
            args.bank_receipt_sha256,
            args.contract,
            args.contract_sha256,
            args.fold,
            args.output,
        )
    elif args.command == "export-artists":
        pin = export_artists(
            args.source, args.source_receipt_sha256, args.bundle, args.bundle_sha256, args.output
        )
    elif args.command == "export-queries":
        pin = portable.export_queries(
            args.bundle,
            args.bundle_sha256,
            args.source,
            args.source_receipt_sha256,
            args.recording_mbid,
            args.output,
        )
    elif args.command == "verify":
        portable.bundle(args.bundle, args.bundle_sha256)
        pin = args.bundle_sha256
    else:
        result = portable.infer(args.bundle, args.bundle_sha256, args.queries, args.query_sha256)
        raw = portable.encoded(result)
        pin = hashlib.sha256(raw).hexdigest()
        if args.command == "infer":
            portable.destination(args.output, (args.bundle, args.queries))
            if len(raw) > portable.MAX_FILE_BYTES:
                raise ValueError("Inference output exceeds byte cap")
            with args.output.open("xb") as stream:
                stream.write(raw)
        elif portable.read(args.result, args.result_sha256) != result:
            raise ValueError("Replayed result differs from external pinned artifact")
    sys.stdout.write(json.dumps({"status": "pass", "command": args.command, "sha256": pin}) + "\n")


if __name__ == "__main__":
    main()
