"""Freeze a review candidate or build its separately approved bounded audio extension."""

from __future__ import annotations

import argparse
import json
import resource
import signal
import time
from pathlib import Path


def main() -> None:
    """Read local retained sources only; recipe generation does not authorize output."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("freeze", "build"))
    for name in ("original-audio", "parent-audio", "capture", "proposal", "output"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--recipe", type=Path)
    args = parser.parse_args()
    resource.setrlimit(resource.RLIMIT_AS, (1_000_000_000, 1_000_000_000))
    resource.setrlimit(resource.RLIMIT_CPU, (120, 120))
    signal.alarm(120)
    started = time.monotonic()
    from opennoise.deployment import (  # noqa: PLC0415 -- limits before source imports.
        fma_bounded_extension as extension,
    )

    inputs = (args.original_audio, args.parent_audio, args.capture, args.proposal)
    if args.operation == "freeze":
        result = extension.freeze(*inputs, args.output)
    else:
        if args.recipe is None:
            parser.error("build requires --recipe")
        result = extension.build(*inputs, args.recipe, args.output)
    signal.alarm(0)
    print(  # noqa: T201 -- bounded execution evidence.
        json.dumps(
            {
                "revision": result["revision"],
                "clips": len(result.get("tracks", {})),
                "audio_bytes": result.get("audio_bytes"),
                "elapsed_seconds": time.monotonic() - started,
                "peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
            }
        )
    )


if __name__ == "__main__":
    main()
