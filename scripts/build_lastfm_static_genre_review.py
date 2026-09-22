"""Build a bounded, unreviewed Last.fm packet for literal static-v2 genre candidates."""

from __future__ import annotations

import argparse
from pathlib import Path

from opennoise.common import write_atomic_bytes
from opennoise.evidence.lastfm_static_genre_review import build_lastfm_static_genre_review


def main() -> int:
    """Write one deterministic local review packet without touching public output."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--static-discovery", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--sample-size", type=int, default=100)
    arguments = parser.parse_args()
    packet = build_lastfm_static_genre_review(
        arguments.archive, arguments.static_discovery, sample_size=arguments.sample_size
    )
    write_atomic_bytes(arguments.output, (packet.model_dump_json(indent=2) + "\n").encode())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
