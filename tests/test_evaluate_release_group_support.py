from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from scripts.evaluate_release_group_support import (
    ReleaseGroupSupportEvaluationError,
    evaluate_release_group_support,
)


class ReleaseGroupSupportEvaluationTests(unittest.TestCase):
    def test_deduplicates_same_release_group_across_facets_for_independent_support(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "completed.sqlite"
            _completed_fixture(database)

            report = evaluate_release_group_support(database)

        self.assertFalse(report["historical_inputs_present"])
        self.assertFalse(report["artifact_receipt_binding_verified_by_this_evaluator"])
        self.assertEqual(
            report["independent_release_group_corroboration"],
            [
                {
                    "distinct_release_group_support": 1,
                    "support_membership_count": 1,
                    "direct_corroborated_membership_count": 0,
                    "direct_corroboration_rate": 0.0,
                },
                {
                    "distinct_release_group_support": 2,
                    "support_membership_count": 1,
                    "direct_corroborated_membership_count": 1,
                    "direct_corroboration_rate": 1.0,
                },
            ],
        )
        self.assertIn("not precision", str(report["corroboration_interpretation"]))

    def test_rejects_incomplete_staging_database(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "staging.sqlite"
            _completed_fixture(database)
            with closing(sqlite3.connect(database)) as connection, connection:
                connection.execute("CREATE TABLE build_checkpoint (singleton INTEGER PRIMARY KEY)")

            with self.assertRaisesRegex(ReleaseGroupSupportEvaluationError, "active staging"):
                evaluate_release_group_support(database)


def _completed_fixture(path: Path) -> None:
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.executescript(
            """CREATE TABLE direct_anchor (
                   genre_id TEXT, artist_id TEXT, facet TEXT, evidence_ref TEXT
               );
               CREATE TABLE release_group_support (
                   genre_id TEXT, artist_id TEXT, facet TEXT,
                   release_group_id TEXT, evidence_ref TEXT
               );
               CREATE TABLE typed_evidence (evidence_kind TEXT);"""
        )
        connection.execute(
            "INSERT INTO direct_anchor VALUES ('g', 'artist-a', 'musicbrainz_genre', 'd')"
        )
        connection.executemany(
            "INSERT INTO release_group_support VALUES (?, ?, ?, ?, 'support')",
            [
                ("g", "artist-a", "musicbrainz_genre", "release-1"),
                ("g", "artist-a", "musicbrainz_tag", "release-1"),
                ("g", "artist-a", "musicbrainz_tag", "release-2"),
                ("g", "artist-b", "musicbrainz_tag", "release-1"),
            ],
        )
        connection.executemany(
            "INSERT INTO typed_evidence VALUES (?)",
            [
                ("artist_direct",),
                ("release_group_support",),
                ("release_group_support",),
                ("release_group_support",),
                ("release_group_support",),
            ],
        )


if __name__ == "__main__":
    unittest.main()
