import sqlite3
import tempfile
import unittest
from pathlib import Path

from musix.db import Database, UnsupportedSchemaError, fts_prefix_query


class DatabaseTests(unittest.TestCase):
    def test_initializes_the_schema_once(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "catalog.sqlite")
            database.initialize()
            database.initialize()
            with database.connect() as connection:
                version = connection.execute("PRAGMA user_version").fetchone()[0]
            self.assertEqual(version, 1)
            self.assertEqual(database.entity_count(), 0)

    def test_rejects_an_unknown_schema_version(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "catalog.sqlite"
            with sqlite3.connect(path) as connection:
                connection.execute("PRAGMA user_version = 99")
            with self.assertRaises(UnsupportedSchemaError):
                Database(path).initialize()

    def test_builds_a_bounded_literal_fts_query(self) -> None:
        self.assertEqual(fts_prefix_query("acid-jazz OR *"), '"acidjazz"* AND "OR"*')
        self.assertIsNone(fts_prefix_query("---"))
        query = fts_prefix_query("one two three four five six seven eight nine")
        self.assertIsNotNone(query)
        if query is not None:
            self.assertEqual(query.count("*"), 8)


if __name__ == "__main__":
    unittest.main()
