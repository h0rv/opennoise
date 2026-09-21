"""Write a local-only direct MusicBrainz proper-genre frontier report."""

from __future__ import annotations

import argparse
from pathlib import Path

from opennoise.checkpoints.musicbrainz_direct_genre_frontier import (
    audit_direct_genre_frontier,
    report_json,
)


def main() -> int:
    """Parse the bounded local inputs and write one canonical report."""
    parser = argparse.ArgumentParser(prog="audit-musicbrainz-direct-genre-frontier")
    parser.add_argument("--layout", type=Path, required=True)
    parser.add_argument("--frontier", type=Path, required=True)
    parser.add_argument("--reconciliation", type=Path, required=True)
    parser.add_argument("--seed-target", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    report = audit_direct_genre_frontier(
        layout_path=arguments.layout,
        frontier_path=arguments.frontier,
        reconciliation_path=arguments.reconciliation,
        seed_target_path=arguments.seed_target,
    )
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(report_json(report), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
