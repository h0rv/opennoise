"""Build, replay or look up a bounded native AcousticBrainz recording bank offline."""

from __future__ import annotations

import argparse
import json
import resource
import signal
import sys
from pathlib import Path

from opennoise.ingest.acousticbrainz.vector_bank import build, lookup, verify


def main() -> None:
    """Apply unchanged process caps before reading source artifacts."""
    resource.setrlimit(resource.RLIMIT_AS, (1_000_000_000, 1_000_000_000))
    resource.setrlimit(resource.RLIMIT_CPU, (120, 120))
    signal.alarm(120)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("build", "verify", "lookup"))
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--recording-mbid")
    args = parser.parse_args()
    if args.action == "build":
        result = build(args.source, args.output)
    elif args.action == "verify":
        bank = verify(args.source, args.output)
        result = {"status": "pass", "counts": bank["counts"], "columns": len(bank["columns"])}
    else:
        if not args.recording_mbid:
            parser.error("lookup requires --recording-mbid")
        result = lookup(args.source, args.output, args.recording_mbid)
    sys.stdout.write(json.dumps(result, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
