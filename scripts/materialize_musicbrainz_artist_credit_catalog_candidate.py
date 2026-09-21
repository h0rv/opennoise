"""Materialize one new isolated MusicBrainz artist-credit SQLite candidate."""

from __future__ import annotations

import argparse
from pathlib import Path

from opennoise.ingest.musicbrainz.artist_credit_catalog_candidate import (
    ARTIST_CREDIT_V2_SHA256,
    CORE_HYDRATION_SHA256,
    materialize_artist_credit_candidate,
)


def main() -> int:
    """Run the offline-only, no-replace candidate materialization boundary."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hydration-artifact", required=True, type=Path)
    parser.add_argument("--credit-artifact", required=True, type=Path)
    parser.add_argument("--cache-directory", required=True, type=Path)
    parser.add_argument("--database", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--hydration-sha256", default=CORE_HYDRATION_SHA256)
    parser.add_argument("--credit-sha256", default=ARTIST_CREDIT_V2_SHA256)
    arguments = parser.parse_args()
    report = materialize_artist_credit_candidate(
        hydration_artifact_path=arguments.hydration_artifact,
        credit_artifact_path=arguments.credit_artifact,
        cache_directory=arguments.cache_directory,
        candidate_database_path=arguments.database,
        report_path=arguments.report,
        expected_hydration_sha256=arguments.hydration_sha256,
        expected_credit_sha256=arguments.credit_sha256,
    )
    print(report.model_dump_json())  # noqa: T201
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
