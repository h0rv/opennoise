"""Build a local minimized matching-declaration candidate, without public deployment."""

import argparse
import json
import os
import resource
import signal
from pathlib import Path

os.environ["OPENBLAS_NUM_THREADS"] = "1"
resource.setrlimit(resource.RLIMIT_AS, (1_000_000_000, 1_000_000_000))
resource.setrlimit(resource.RLIMIT_CPU, (120, 120))
signal.alarm(120)
from opennoise.deployment.fma_public_candidate import build_candidate  # noqa: E402

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("site", "audit-directory", "decisions", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--decision-sha256", required=True)
    args = parser.parse_args()
    result = build_candidate(
        args.site, args.audit_directory, args.decisions, args.output, args.decision_sha256
    )
    print(  # noqa: T201
        json.dumps(
            {
                "tracks": len(result["tracks"]),
                "audio_bytes": result["audio_bytes"],
                "public_deployment_authorized": False,
            }
        )
    )
