import sqlite3
import unittest
from pathlib import Path
from typing import override

ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = (
    ROOT / "migrations" / "0001_initial.sql",
    ROOT / "migrations" / "0002_album_genres.sql",
    ROOT / "migrations" / "0003_genre_discovery.sql",
    ROOT / "migrations" / "0004_artist_genre_membership.sql",
    ROOT / "migrations" / "0005_artist_co_listen_evidence.sql",
    ROOT / "migrations" / "0006_recording_genres.sql",
    ROOT / "migrations" / "0007_public_model_serving.sql",
    ROOT / "migrations" / "0008_public_model_layout_lenses.sql",
    ROOT / "migrations" / "0009_wikidata_recording_genres.sql",
)
FIXTURE = ROOT / "migrations" / "smoke" / "fixture.sql"


class SchemaTests(unittest.TestCase):
    @override
    def setUp(self) -> None:
        self.database = sqlite3.connect(":memory:")
        self.database.execute("PRAGMA foreign_keys = ON")
        for migration in MIGRATIONS:
            self.database.executescript(migration.read_text(encoding="utf-8"))

    @override
    def tearDown(self) -> None:
        self.database.close()

    def load_fixture(self) -> None:
        self.database.executescript(FIXTURE.read_text(encoding="utf-8"))

    def test_fresh_migration_is_sound(self) -> None:
        version = self.database.execute("PRAGMA user_version").fetchone()
        integrity = self.database.execute("PRAGMA integrity_check").fetchone()
        foreign_keys = self.database.execute("PRAGMA foreign_key_check").fetchall()

        self.assertEqual(version, (9,))
        self.assertEqual(integrity, ("ok",))
        self.assertEqual(foreign_keys, [])

    def test_fixture_covers_catalog_ingest_and_map(self) -> None:
        self.load_fixture()

        self.assertEqual(
            self.database.execute("SELECT count(*) FROM normalization_exports").fetchone(),
            (1,),
        )
        self.assertEqual(
            self.database.execute("SELECT count(*) FROM current_source_objects").fetchone(),
            (1,),
        )
        self.assertEqual(
            self.database.execute("SELECT count(*) FROM displayable_map_points").fetchone(),
            (1,),
        )
        self.assertEqual(
            self.database.execute(
                "SELECT count(*) FROM catalog_entity_integrity_violations"
            ).fetchone(),
            (0,),
        )

    def test_fts_uses_policy_safe_projection(self) -> None:
        self.load_fixture()
        self.database.execute(
            """
            INSERT INTO search_documents (
                entity_id, field_kind, search_text, input_fingerprint, provenance_id, policy_id
            ) VALUES (1, 'primary_name', 'Intelligent Dance Music', ?, 1, 1)
            """,
            ("3434343434343434343434343434343434343434343434343434343434343434",),
        )

        matches = self.database.execute(
            """
            SELECT document.entity_id
            FROM search_documents_fts
            JOIN searchable_documents AS document ON document.id = search_documents_fts.rowid
            WHERE search_documents_fts MATCH 'intelligent'
            """
        ).fetchall()

        self.assertEqual(matches, [(1,)])

    def test_local_only_policy_cannot_allow_export(self) -> None:
        self.load_fixture()

        with self.assertRaises(sqlite3.IntegrityError):
            self.database.execute(
                """
                INSERT INTO rights_policy_permissions (policy_id, use_kind, decision, reason)
                VALUES (2, 'export', 'allow', 'Not permitted')
                """
            )

    def test_quarantined_record_cannot_be_normalized(self) -> None:
        self.load_fixture()

        with self.assertRaises(sqlite3.IntegrityError):
            self.database.execute(
                """
                INSERT INTO normalization_exports (
                    staged_record_id, source_object_observation_id, projection_kind,
                    output_fingerprint, exported_at
                ) VALUES (2, 1, 'artist', ?, '2026-01-01T00:00:00Z')
                """,
                ("3535353535353535353535353535353535353535353535353535353535353535",),
            )


if __name__ == "__main__":
    unittest.main()
