"""Acquire or offline-replay exact CC0 artist evidence via Wikidata entity API."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from opennoise.ingest.wikidata.entity_evidence import acquire, finish, verify


def main() -> None:
    """Acquire or replay without changing existing packs."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--core", type=Path, required=True)
    parser.add_argument("--scan", type=Path)
    parser.add_argument("--max-artists", type=int, default=10000)
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--finish", action="store_true")
    args = parser.parse_args()
    if args.verify:
        result = verify(args.output, args.core)
    elif args.finish:
        result = finish(args.output, args.core)
    else:
        if args.scan is None:
            parser.error("--scan is required for acquisition")
        result = acquire(args.output, args.scan, args.core, args.max_artists)
    sys.stdout.write(json.dumps(result, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
