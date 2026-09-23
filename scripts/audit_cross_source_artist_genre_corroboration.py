"""Write one non-overwriting local-only exact artist/seed overlap audit."""

from __future__ import annotations

import argparse
from pathlib import Path

from opennoise.checkpoints.cross_source_artist_genre_corroboration import (
    build_cross_source_artist_genre_corroboration_audit,
)


def main() -> int:
    """Build the report without reading or writing any public/static artifact."""
    parser = argparse.ArgumentParser(prog="audit-cross-source-artist-genre-corroboration")
    parser.add_argument("--musicbrainz-receipt", required=True, type=Path)
    parser.add_argument("--musicbrainz-object-store", required=True, type=Path)
    parser.add_argument("--lastfm-candidate-artifact", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args()
    report = build_cross_source_artist_genre_corroboration_audit(
        musicbrainz_receipt=arguments.musicbrainz_receipt,
        musicbrainz_object_store=arguments.musicbrainz_object_store,
        lastfm_candidate_artifact=arguments.lastfm_candidate_artifact,
    )
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    with arguments.output.open("x", encoding="utf-8") as stream:
        stream.write(report.model_dump_json(indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
