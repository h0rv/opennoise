"""Capture or replay the three licensed native FMA metadata CSV members."""

import argparse
import json
import sys
from pathlib import Path

from opennoise.ingest.fma.corpus import capture_sources, project_corpus


def main() -> None:
    """Require new destinations and keep network capture explicit."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--capture",
        action="store_true",
        help="Fetch bounded official compressed ranges; otherwise replay offline",
    )
    args = parser.parse_args()
    if args.output.exists() or args.output.is_symlink():
        raise FileExistsError("refusing to replace projected corpus")
    if args.capture:
        capture_sources(args.source)
    sys.stdout.write(json.dumps(project_corpus(args.source, args.output), indent=2) + "\n")


if __name__ == "__main__":
    main()
