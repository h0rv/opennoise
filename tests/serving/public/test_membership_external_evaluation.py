from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from musix.serving.public.membership_external_evaluation import (
    evaluate_public_memberships_externally,
)

_SOURCE = "musicbrainz_json_artist_research_20260829"
_HASH = "a" * 64


class PublicMembershipExternalEvaluationTests(unittest.TestCase):
    def _build_public_database(self, path: Path) -> None:
        with sqlite3.connect(path) as connection:
            connection.executescript(
                """CREATE TABLE data_sources (source_key TEXT NOT NULL);
                CREATE TABLE public_model_runs (
                    id INTEGER PRIMARY KEY, output_sha256 TEXT, artifact_sha256 TEXT,
                    published_at TEXT, export_allowed INTEGER, derived_output_id INTEGER
                );
                CREATE TABLE current_public_models (model_key TEXT, model_run_id INTEGER);
                CREATE TABLE genres (id INTEGER PRIMARY KEY, name TEXT NOT NULL);
                CREATE TABLE public_genre_profile_memberships (
                    model_run_id INTEGER, genre_id INTEGER, profile_kind TEXT,
                    source_artist_ref TEXT, score REAL
                );
                """
            )
            connection.execute(
                "INSERT INTO public_model_runs VALUES (1, ?, ?, '2026-09-04T00:00:00Z', 1, 9)",
                (_HASH, "b" * 64),
            )
            connection.execute("INSERT INTO current_public_models VALUES ('public-graph', 1)")
            connection.executemany(
                "INSERT INTO genres VALUES (?, ?)", ((1, "jazz"), (2, "rock"), (3, "missing"))
            )
            connection.executemany(
                "INSERT INTO public_genre_profile_memberships VALUES (?, ?, ?, ?, ?)",
                (
                    (1, 1, "direct", "musicbrainz:artist:a1", 0.9),
                    (1, 2, "direct", "musicbrainz:artist:a2", 0.2),
                    (1, 1, "direct", "musicbrainz:artist:absent", 0.5),
                    (1, 3, "direct", "musicbrainz:artist:a1", 0.5),
                    (1, 1, "one_hop", "musicbrainz:artist:a1", 0.7),
                ),
            )

    def _build_research_database(self, path: Path) -> None:
        with sqlite3.connect(path) as connection:
            connection.executescript(
                """CREATE TABLE artist_genre_evidence (
                    artist_id INTEGER, genre_id INTEGER, evidence_kind TEXT,
                    evidence_value REAL, source_key TEXT
                );
                CREATE TABLE entity_identifiers (
                    entity_id INTEGER, namespace TEXT, normalized_value TEXT
                );
                CREATE TABLE entity_names (entity_id INTEGER, name_kind TEXT, name TEXT);
                CREATE TABLE genres (id INTEGER PRIMARY KEY, name TEXT NOT NULL);
                """
            )
            connection.executemany(
                "INSERT INTO entity_identifiers VALUES (?, 'musicbrainz', ?)",
                ((1, "a1"), (2, "a2")),
            )
            connection.executemany(
                "INSERT INTO entity_names VALUES (?, 'primary', ?)",
                ((1, "Artist one"), (2, "Artist two")),
            )
            connection.executemany(
                "INSERT INTO genres VALUES (?, ?)", ((1, "jazz"), (2, "rock"), (3, "pop"))
            )
            connection.executemany(
                "INSERT INTO artist_genre_evidence VALUES (?, ?, 'direct_source_claim', ?, ?)",
                ((1, 1, 3.0, _SOURCE), (1, 2, 1.0, _SOURCE), (2, 3, 1.0, _SOURCE)),
            )

    def test_strict_matching_tracks_missing_genres_and_reference_only_abstentions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            public = root / "public.sqlite"
            research = root / "research.sqlite"
            self._build_public_database(public)
            self._build_research_database(research)
            report = evaluate_public_memberships_externally(public, research, thresholds=(1.0,))

        direct = report.sensitivity[0].direct
        self.assertEqual(direct.coverage.public_prediction_count, 4)
        self.assertEqual(direct.coverage.evaluated_prediction_count, 2)
        self.assertEqual(direct.coverage.unmatched_artist_prediction_count, 1)
        self.assertEqual(direct.coverage.unmatched_genre_prediction_count, 1)
        self.assertEqual(direct.micro.true_positive, 1)
        self.assertEqual(direct.micro.false_positive, 1)
        self.assertEqual(direct.micro.false_negative, 1)
        self.assertEqual(direct.micro.true_negative, 0)
        self.assertEqual(direct.micro.abstention_count, 1)
        self.assertTrue(report.prohibited_input_checks.research_source_absent_from_public_database)
        self.assertTrue(report.stability.exact_replay)

    def test_rejects_research_source_present_in_public_database(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            public = root / "public.sqlite"
            research = root / "research.sqlite"
            self._build_public_database(public)
            self._build_research_database(research)
            with sqlite3.connect(public) as connection:
                connection.execute("INSERT INTO data_sources VALUES (?)", (_SOURCE,))
            with self.assertRaisesRegex(ValueError, "research source is present"):
                evaluate_public_memberships_externally(public, research, thresholds=(1.0,))


if __name__ == "__main__":
    unittest.main()
