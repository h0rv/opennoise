"""Freeze or execute the recording-profile discovery artifact."""

from __future__ import annotations

import argparse
import json
import os
import resource
import signal
import time
from pathlib import Path


def main() -> None:
    """Apply the unchanged resource envelope before numerical imports."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("freeze", "run", "verify"))
    for name in ("source", "candidate-manifest", "protocol", "declaration", "output"):
        parser.add_argument(f"--{name}", type=Path)
    parser.add_argument("--inventory-sha256")
    args = parser.parse_args()
    resource.setrlimit(resource.RLIMIT_AS, (1_000_000_000, 1_000_000_000))
    resource.setrlimit(resource.RLIMIT_CPU, (120, 120))
    signal.alarm(120)
    for name in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
        os.environ[name] = "1"
    started = time.monotonic()
    from opennoise.ml import (  # noqa: PLC0415 -- limits before numeric imports.
        fma_recording_profiles as profiles,
    )

    if args.operation == "freeze":
        result = profiles.freeze(
            args.source, args.candidate_manifest, args.protocol, args.declaration
        )
    elif args.operation == "run":
        result = profiles.run(args.declaration, args.output)
    else:
        result = profiles.validate_discovery_pack(
            args.output, args.candidate_manifest, args.source, args.inventory_sha256
        )
    print(  # noqa: T201 -- CLI resource evidence.
        json.dumps(
            {
                "revision": result["revision"],
                "elapsed_seconds": time.monotonic() - started,
                "peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
            }
        )
    )


if __name__ == "__main__":
    main()
