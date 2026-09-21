"""Evaluate archived Last.fm ArtistTags2007 rows against static discovery locally."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from opennoise.checkpoints.lastfm_artisttags2007_overlap import (
    build_lastfm_artisttags2007_static_overlap,
    verify_lastfm_artisttags2007_static_overlap,
)
from opennoise.common import write_atomic_bytes


def main() -> int:
    """Write a local research report without changing any discovery input."""
    parser = argparse.ArgumentParser(prog="evaluate-lastfm-artisttags2007-overlap")
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--static-discovery", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    report = build_lastfm_artisttags2007_static_overlap(
        arguments.archive, arguments.static_discovery
    )
    verify_lastfm_artisttags2007_static_overlap(report)
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    write_atomic_bytes(arguments.output, (report.model_dump_json(indent=2) + "\n").encode())
    sys.stdout.write(
        json.dumps(
            {
                "output_sha256": report.output_sha256,
                "parse_coverage": report.parse_coverage.model_dump(),
                "thresholds": [item.model_dump() for item in report.thresholds],
            }
        )
        + "\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
