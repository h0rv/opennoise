"""Rebuild the reviewed candidate interface from its own pinned local files."""

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
from opennoise.deployment.fma_public_candidate import rebuild_candidate  # noqa: E402

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prior", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--manifest-sha256", required=True)
    args = parser.parse_args()
    result = rebuild_candidate(args.prior, args.output, args.manifest_sha256)
    print(json.dumps({"tracks": len(result["tracks"]), "audio_bytes": result["audio_bytes"]}))  # noqa: T201
