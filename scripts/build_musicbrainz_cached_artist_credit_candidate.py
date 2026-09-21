"""Build an offline-only MusicBrainz artist-credit candidate from retained cache entries."""

from __future__ import annotations

import argparse
from pathlib import Path

from opennoise.ingest.musicbrainz.artist_credit_enrichment import (
    build_cached_artist_credit_enrichment,
    write_cached_artist_credit_enrichment,
)


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hydration-artifact", required=True, type=Path)
    parser.add_argument("--cache-directory", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args()


def main() -> int:
    """Write a candidate ledger; this command has no network client or network options."""
    arguments = _arguments()
    enrichment = build_cached_artist_credit_enrichment(
        source_hydration_artifact_path=arguments.hydration_artifact,
        cache_directory=arguments.cache_directory,
    )
    print(write_cached_artist_credit_enrichment(enrichment, output=arguments.output))  # noqa: T201
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
