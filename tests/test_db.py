import sqlite3
import tempfile
import unittest
from pathlib import Path

from musix.db import Database, UnsupportedSchemaError, fts_prefix_query

ROOT = Path(__file__).resolve().parents[1]
INITIAL_MIGRATION = ROOT / "migrations" / "0001_initial.sql"
ALBUM_MIGRATION = ROOT / "migrations" / "0002_album_genres.sql"
DISCOVERY_MIGRATION = ROOT / "migrations" / "0003_genre_discovery.sql"
CURRENT_SCHEMA_VERSION = 9


class DatabaseTests(unittest.TestCase):
    def test_initializes_the_schema_once(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "catalog.sqlite")
            database.initialize()
            database.initialize()
            with database.connect() as connection:
                version = connection.execute("PRAGMA user_version").fetchone()[0]
            self.assertEqual(version, CURRENT_SCHEMA_VERSION)
            self.assertEqual(database.entity_count(), 0)

    def test_rejects_an_unknown_schema_version(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "catalog.sqlite"
            with sqlite3.connect(path) as connection:
                connection.execute("PRAGMA user_version = 99")
            with self.assertRaises(UnsupportedSchemaError):
                Database(path).initialize()

    def test_upgrades_an_existing_version_one_database(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "catalog.sqlite"
            with sqlite3.connect(path) as connection:
                connection.executescript(INITIAL_MIGRATION.read_text(encoding="utf-8"))

            database = Database(path)
            database.initialize()

            with database.connect() as connection:
                version = connection.execute("PRAGMA user_version").fetchone()[0]
                table = connection.execute(
                    """
                    SELECT name FROM sqlite_schema
                    WHERE type = 'table' AND name = 'album_genre_membership_observations'
                    """
                ).fetchone()
            self.assertEqual(version, CURRENT_SCHEMA_VERSION)
            self.assertIsNotNone(table)

    def test_upgrades_an_existing_version_two_database(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "catalog.sqlite"
            with sqlite3.connect(path) as connection:
                connection.executescript(INITIAL_MIGRATION.read_text(encoding="utf-8"))
                connection.executescript(ALBUM_MIGRATION.read_text(encoding="utf-8"))

            database = Database(path)
            database.initialize()

            with database.connect() as connection:
                version = connection.execute("PRAGMA user_version").fetchone()[0]
                table = connection.execute(
                    """SELECT name FROM sqlite_schema
                       WHERE type = 'table'
                         AND name = 'historical_genre_track_observations'"""
                ).fetchone()
            self.assertEqual(version, CURRENT_SCHEMA_VERSION)
            self.assertIsNotNone(table)

    def test_upgrades_an_existing_version_three_database(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "catalog.sqlite"
            with sqlite3.connect(path) as connection:
                connection.executescript(INITIAL_MIGRATION.read_text(encoding="utf-8"))
                connection.executescript(ALBUM_MIGRATION.read_text(encoding="utf-8"))
                connection.executescript(DISCOVERY_MIGRATION.read_text(encoding="utf-8"))

            database = Database(path)
            database.initialize()

            with database.connect() as connection:
                version = connection.execute("PRAGMA user_version").fetchone()[0]
                table = connection.execute(
                    """SELECT name FROM sqlite_schema
                       WHERE type = 'table' AND name = 'artist_genre_evidence'"""
                ).fetchone()
            self.assertEqual(version, CURRENT_SCHEMA_VERSION)
            self.assertIsNotNone(table)

    def test_builds_a_bounded_literal_fts_query(self) -> None:
        self.assertEqual(fts_prefix_query("acid-jazz OR *"), '"acidjazz"* AND "OR"*')
        self.assertIsNone(fts_prefix_query("---"))
        query = fts_prefix_query("one two three four five six seven eight nine")
        self.assertIsNotNone(query)
        if query is not None:
            self.assertEqual(query.count("*"), 8)


if __name__ == "__main__":
    unittest.main()
