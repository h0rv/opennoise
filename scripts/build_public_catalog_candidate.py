"""Build or independently replay a static candidate from pinned public repository sources."""

import argparse
import json
import os
import resource
import signal
from pathlib import Path


def main() -> None:
    """Keep candidate construction bounded and separate from production deployment."""
    for name in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
        os.environ[name] = "1"
    resource.setrlimit(resource.RLIMIT_AS, (1_000_000_000, 1_000_000_000))
    resource.setrlimit(resource.RLIMIT_CPU, (120, 120))
    signal.alarm(120)
    from opennoise.pipeline import public_catalog_candidate as candidate  # noqa: PLC0415

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("build", "verify"))
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    function = candidate.build if args.command == "build" else candidate.verify
    manifest = function(args.root, args.output)
    print(  # noqa: T201 -- Candidate build receipt, never deployment.
        json.dumps(
            {
                "revision": manifest["revision"],
                "counts": manifest["counts"],
                "payload_files": len(manifest["payload"]),
                "publication_authorized": False,
            }
        )
    )


if __name__ == "__main__":
    main()
