"""Export bounded JSONL suggestions for explicit native FMA IDs using a frozen saved pack."""

from __future__ import annotations

import argparse
import os
import resource
import signal
import sys
from pathlib import Path

# Set before importing numerical libraries; independent of caller environment.
os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"

from opennoise.ml.fma_inference import (
    MAX_SECONDS,
    MEMORY_BYTES,
    encode_jsonl,
    infer_tracks,
)


def _timeout(_signum: int, _frame: object) -> None:
    raise TimeoutError("inference wall-time budget exceeded")


def main() -> None:
    """Write stdout only after full validation; validation failures emit no JSONL records."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack", type=Path, required=True)
    parser.add_argument("--features", type=Path, required=True)
    parser.add_argument("--track-id", type=int, action="append", required=True)
    args = parser.parse_args()
    resource.setrlimit(resource.RLIMIT_AS, (MEMORY_BYTES, MEMORY_BYTES))
    resource.setrlimit(resource.RLIMIT_CPU, (MAX_SECONDS, MAX_SECONDS))
    signal.signal(signal.SIGALRM, _timeout)
    signal.alarm(MAX_SECONDS)
    try:
        data = encode_jsonl(infer_tracks(args.pack, args.features, args.track_id))
        sys.stdout.buffer.write(data)
        sys.stdout.buffer.flush()
    except (ValueError, OSError, TimeoutError) as exc:
        parser.exit(2, f"FMA inference failed: {exc}\n")
    finally:
        signal.alarm(0)


if __name__ == "__main__":
    main()
