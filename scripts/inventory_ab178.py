"""Audit pinned native AB178 compatibility before selecting a cohort or fitting."""

import argparse
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

from opennoise.ml.ab178_inventory import inventory  # noqa: E402
from opennoise.ml.ab178_portable import destination, encoded, publish  # noqa: E402


def main() -> None:
    """Require externally pinned source/contract inputs and a fresh output directory."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--source-receipt-sha256", required=True)
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--contract-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    destination(args.output, (args.source, args.contract))
    report = inventory(args.source, args.source_receipt_sha256, args.contract, args.contract_sha256)
    pin = publish(args.output, "inventory.json", report)
    sys.stdout.buffer.write(encoded({"sha256": pin, "state_counts": report["state_counts"]}))


if __name__ == "__main__":
    main()
