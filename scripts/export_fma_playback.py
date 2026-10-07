"""Export an already captured and verified FMA listening pack; strictly offline."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from opennoise.deployment.fma_playback import export_fma_playback


def main() -> None:
    """Write a fresh sibling audio directory without downloading or transcoding."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack", type=Path, required=True)
    parser.add_argument("--metadata-source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = export_fma_playback(args.pack, args.metadata_source, args.output)
    print(json.dumps(result, sort_keys=True, indent=2))  # noqa: T201 -- explicit export receipt.


if __name__ == "__main__":
    main()
