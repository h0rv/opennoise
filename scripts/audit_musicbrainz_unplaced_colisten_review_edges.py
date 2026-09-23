"""Measure local-only review proposals from retained MusicBrainz and Last.fm caches."""

from __future__ import annotations

import argparse
from pathlib import Path

from opennoise.analysis.musicbrainz_unplaced_colisten_edges import (
    evaluate_musicbrainz_unplaced_colisten_edges,
    write_report_no_replace,
)


def main() -> int:
    """Run the receipt-bound local experiment and create one report."""
    parser = argparse.ArgumentParser(prog="audit-musicbrainz-unplaced-colisten-review-edges")
    parser.add_argument("--layout", type=Path, required=True)
    parser.add_argument("--source-tag-artifact", type=Path, required=True)
    parser.add_argument("--lastfm-artifact", type=Path, required=True)
    parser.add_argument("--lastfm-companion-receipt", type=Path, required=True)
    parser.add_argument("--lastfm-database", type=Path, required=True)
    parser.add_argument("--review-candidate", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    report = evaluate_musicbrainz_unplaced_colisten_edges(
        layout_path=arguments.layout,
        source_tag_artifact_path=arguments.source_tag_artifact,
        lastfm_artifact_path=arguments.lastfm_artifact,
        lastfm_companion_receipt_path=arguments.lastfm_companion_receipt,
        lastfm_database_path=arguments.lastfm_database,
        review_candidate_path=arguments.review_candidate,
    )
    write_report_no_replace(arguments.output, report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
