"""Fail before a release task can mix public and local-research catalogs."""

import argparse
import sqlite3
from pathlib import Path

ALLOWED_SOURCE_KEYS = {
    "wikidata_music_sparql_slice",
    "wikidata_public_genres_20260831",
    "listenbrainz_joint_20260824_20260830",
    *(f"listenbrainz_incremental_202608{day:02d}" for day in range(24, 31)),
}


def validate_public_database(database: Path) -> None:
    """Reject an existing catalog containing any non-public-release source."""
    if not database.exists():
        return
    with sqlite3.connect(f"file:{database.resolve()}?mode=ro", uri=True) as connection:
        table = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'data_sources'"
        ).fetchone()
        if table is None:
            raise RuntimeError("existing release database has no OpenNoise catalog schema")
        source_keys = {
            str(row[0]) for row in connection.execute("SELECT source_key FROM data_sources")
        }
    unexpected = source_keys - ALLOWED_SOURCE_KEYS
    if unexpected:
        rendered = ", ".join(sorted(unexpected))
        raise RuntimeError(f"release database contains nonpublic sources: {rendered}")


def main() -> int:
    """Allow a fresh or interrupted public-only release database."""
    parser = argparse.ArgumentParser()
    parser.add_argument("database", type=Path)
    database = parser.parse_args().database
    validate_public_database(database)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
