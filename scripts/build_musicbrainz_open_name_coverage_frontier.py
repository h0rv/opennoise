"""Write the local-only MusicBrainz open-name coverage frontier."""

from __future__ import annotations

import argparse
from pathlib import Path

from opennoise.checkpoints.musicbrainz_open_name_coverage_frontier import (
    build_open_name_coverage_frontier,
    verify_open_name_coverage_frontier,
)


def main() -> int:
    """Parse explicit local custody inputs and write a local-only report."""
    parser = argparse.ArgumentParser(prog="build-musicbrainz-open-name-coverage-frontier")
    parser.add_argument("--reconciliation", type=Path, required=True)
    parser.add_argument("--custody-receipt", type=Path, required=True)
    parser.add_argument("--custody-object-store", type=Path, required=True)
    parser.add_argument("--native-census", type=Path, required=True)
    parser.add_argument("--tag-census", type=Path, required=True)
    parser.add_argument("--hierarchy", type=Path, required=True)
    parser.add_argument("--source-anchor-frontier", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    report = build_open_name_coverage_frontier(
        reconciliation_path=arguments.reconciliation,
        custody_receipt_path=arguments.custody_receipt,
        custody_object_store=arguments.custody_object_store,
        native_census_path=arguments.native_census,
        tag_census_path=arguments.tag_census,
        hierarchy_path=arguments.hierarchy,
        source_anchor_frontier_path=arguments.source_anchor_frontier,
    )
    verify_open_name_coverage_frontier(report)
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
