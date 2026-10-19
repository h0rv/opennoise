"""Build the complete retained CC0 native/cultural catalog, without acquisition or fitting."""

import argparse
import json
import os
import resource
import signal
from pathlib import Path


def main() -> None:
    """Run the bounded ordinary-source end-to-end build in a fresh directory."""
    for name in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
        os.environ[name] = "1"
    resource.setrlimit(resource.RLIMIT_AS, (1_000_000_000, 1_000_000_000))
    resource.setrlimit(resource.RLIMIT_CPU, (120, 120))
    signal.alarm(120)
    from opennoise.pipeline.cultural_catalog import build  # noqa: PLC0415 -- Bound heavy imports.

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--core-source", type=Path, required=True)
    parser.add_argument("--core-source-sha256", required=True)
    parser.add_argument("--cultural-pack", type=Path, required=True)
    parser.add_argument("--cultural-receipt-sha256", required=True)
    parser.add_argument("--independent-pack", type=Path, required=True)
    parser.add_argument("--independent-receipt-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = build(
        args.core_source,
        args.core_source_sha256,
        args.cultural_pack,
        args.cultural_receipt_sha256,
        args.independent_pack,
        args.independent_receipt_sha256,
        args.output,
    )
    print(json.dumps({"source": result["source"], "files": result["files"]}, sort_keys=True))  # noqa: T201


if __name__ == "__main__":
    main()
