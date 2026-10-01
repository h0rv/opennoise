"""Query exact local album, artist, and optional playlist discovery context."""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

from opennoise.serving.local.musicbrainz_album_context import (
    load_playlist_context_report,
    query_album_context,
    response_json,
)
from opennoise.serving.local.musicbrainz_album_discovery import load_album_examples_report
from opennoise.serving.local.musicbrainz_artist_evidence import (
    LocalMusicBrainzArtistEvidenceStore,
    LocalMusicBrainzEvidenceSources,
    load_musicbrainz_model_adapter_report,
    load_release_group_evidence_artifact,
)
from opennoise.taxonomy.seeds.reconciliation import load_seed_reconciliation


def main() -> int:
    """Print a deterministic, bounded research response from verified local files."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--album-report", type=Path, required=True)
    parser.add_argument("--evidence-db", type=Path, required=True)
    parser.add_argument("--evidence-artifact", type=Path, required=True)
    parser.add_argument("--adapter-report", type=Path, required=True)
    parser.add_argument("--reconciliation", type=Path, required=True)
    parser.add_argument("--playlist-report", type=Path)
    parser.add_argument("--limit", type=int, default=10)
    query = parser.add_mutually_exclusive_group(required=True)
    query.add_argument("--genre-name")
    query.add_argument("--artist-mbid")
    arguments = parser.parse_args()
    try:
        report = load_album_examples_report(arguments.album_report)
        if hashlib.sha256(arguments.reconciliation.read_bytes()).hexdigest() != (
            report.seed_reconciliation_sha256
        ):
            raise ValueError("album reconciliation file differs from its source pin")  # noqa: TRY301 -- Source pin boundary.
        store = LocalMusicBrainzArtistEvidenceStore(
            LocalMusicBrainzEvidenceSources(
                database=arguments.evidence_db,
                evidence_artifact=load_release_group_evidence_artifact(arguments.evidence_artifact),
                reconciliation=load_seed_reconciliation(arguments.reconciliation),
                adapter_report=load_musicbrainz_model_adapter_report(arguments.adapter_report),
            )
        )
        store.start()
        response = query_album_context(
            report,
            store,
            genre_name=arguments.genre_name,
            artist_mbid=arguments.artist_mbid,
            playlist_report=(
                load_playlist_context_report(arguments.playlist_report)
                if arguments.playlist_report is not None
                else None
            ),
            limit=arguments.limit,
        )
    except (OSError, ValueError) as error:
        sys.stderr.write(f"local album context query failed: {error}\n")
        return 2
    sys.stdout.write(response_json(response) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
