"""Query local-only direct and separately album-supported MusicBrainz evidence."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from musix.local_musicbrainz_artist_evidence import (
    LocalMusicBrainzArtistEvidenceError,
    LocalMusicBrainzEvidenceSources,
    direct_artists_for_seed,
    direct_seeds_for_artist,
    load_musicbrainz_model_adapter_report,
    load_release_group_evidence_artifact,
)
from musix.seed_reconciliation import load_seed_reconciliation


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-db", type=Path, required=True)
    parser.add_argument("--evidence-artifact", type=Path, required=True)
    parser.add_argument("--adapter-report", type=Path, required=True)
    parser.add_argument("--reconciliation", type=Path, required=True)
    query = parser.add_mutually_exclusive_group(required=True)
    query.add_argument("--seed")
    query.add_argument("--artist-mbid")
    parser.add_argument("--limit", type=int, default=25)
    return parser


def main() -> int:
    """Write one bounded local-research JSON result to standard output."""
    arguments = _parser().parse_args()
    try:
        reconciliation = load_seed_reconciliation(arguments.reconciliation)
        evidence_artifact = load_release_group_evidence_artifact(arguments.evidence_artifact)
        adapter_report = load_musicbrainz_model_adapter_report(arguments.adapter_report)
        sources = LocalMusicBrainzEvidenceSources(
            database=arguments.evidence_db,
            evidence_artifact=evidence_artifact,
            reconciliation=reconciliation,
            adapter_report=adapter_report,
        )
        if arguments.seed is not None:
            response = direct_artists_for_seed(
                sources,
                arguments.seed,
                limit=arguments.limit,
            )
        else:
            if arguments.artist_mbid is None:
                sys.stderr.write(
                    "local MusicBrainz artist evidence query failed: artist ID is missing\n"
                )
                return 2
            response = direct_seeds_for_artist(
                sources,
                arguments.artist_mbid,
                limit=arguments.limit,
            )
    except (LocalMusicBrainzArtistEvidenceError, OSError, ValueError) as error:
        sys.stderr.write(f"local MusicBrainz artist evidence query failed: {error}\n")
        return 2
    sys.stdout.write(response.model_dump_json() + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
