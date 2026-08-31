import sqlite3
import tempfile
import unittest
from pathlib import Path
from typing import override

from scripts.require_fresh_public_database import validate_public_database


class PublicDatabasePreflightTests(unittest.TestCase):
    @override
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    @override
    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_absent_database_is_fresh(self) -> None:
        validate_public_database(self.root / "absent.sqlite")

    def test_interrupted_public_database_can_resume(self) -> None:
        database = self.root / "public.sqlite"
        with sqlite3.connect(database) as connection:
            connection.execute("CREATE TABLE data_sources (source_key TEXT NOT NULL)")
            connection.execute(
                "INSERT INTO data_sources VALUES (?)", ("wikidata_music_sparql_slice",)
            )

        validate_public_database(database)

    def test_local_research_source_is_rejected(self) -> None:
        database = self.root / "mixed.sqlite"
        with sqlite3.connect(database) as connection:
            connection.execute("CREATE TABLE data_sources (source_key TEXT NOT NULL)")
            connection.execute("INSERT INTO data_sources VALUES (?)", ("musicbrainz_artist",))

        with self.assertRaisesRegex(RuntimeError, "musicbrainz_artist"):
            validate_public_database(database)
