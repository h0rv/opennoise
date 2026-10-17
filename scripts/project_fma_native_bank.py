"""Project the sealed full-statistics native FMA bank without network access."""

from __future__ import annotations

import argparse
import json
import resource
import signal
import sys
import time
from pathlib import Path

from opennoise.common import sha256_file
from opennoise.ingest.fma_native_bank import STAGE_LIMITS, project_native_bank


def main() -> None:
    """Require retained native custody and an explicit separate output declaration."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--declaration", type=Path, required=True)
    parser.add_argument("--declaration-sha256", required=True)
    args = parser.parse_args()
    resource.setrlimit(
        resource.RLIMIT_AS, (STAGE_LIMITS["memory_bytes"], STAGE_LIMITS["memory_bytes"])
    )
    resource.setrlimit(
        resource.RLIMIT_CPU, (STAGE_LIMITS["cpu_seconds"], STAGE_LIMITS["cpu_seconds"])
    )
    signal.alarm(STAGE_LIMITS["wall_seconds"])
    started = time.monotonic()
    if sha256_file(args.declaration)[0] != args.declaration_sha256:
        raise ValueError("native bank declaration hash differs")
    result = project_native_bank(args.source, args.output, args.declaration)
    result["execution"] = {
        "wall_seconds": time.monotonic() - started,
        "peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
    }
    sys.stdout.write(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    main()
