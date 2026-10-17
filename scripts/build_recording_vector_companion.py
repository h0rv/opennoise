"""Build or replay exact recording vector observations offline."""

from __future__ import annotations

import argparse
import json
import resource
import signal
import sys
from pathlib import Path

from opennoise.ingest.acousticbrainz.vector_bank import digest
from opennoise.pipeline.recording_vector_companion import build, replay


def main() -> None:
    """Apply unchanged process caps before reading source artifacts."""
    resource.setrlimit(resource.RLIMIT_AS, (1_000_000_000, 1_000_000_000))
    resource.setrlimit(resource.RLIMIT_CPU, (120, 120))
    signal.alarm(120)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("build", "replay"))
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--observations", type=Path, required=True)
    parser.add_argument("--bank", type=Path, required=True)
    for name in ("observations", "source", "bank"):
        parser.add_argument(f"--{name}-receipt-sha256", required=True)
    args = parser.parse_args()
    for name in ("observations", "source", "bank"):
        expected = getattr(args, f"{name}_receipt_sha256")
        if digest(getattr(args, name) / "receipt.json") != expected:
            parser.error(f"{name} receipt differs from approved input pin")
    operation = build if args.action == "build" else replay
    result = operation(args.observations, args.source, args.bank, args.output)
    sys.stdout.write(json.dumps(result, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
