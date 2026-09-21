from __future__ import annotations

import hashlib
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from opennoise.pipeline.phase3_replay_comparator import (
    Phase3ReplayComparisonError,
    _bounded_query_row_count,
    _compare_table,
    compare_phase3_replay_databases,
)


class Phase3ReplayComparatorTests(unittest.TestCase):
    def _database(self, path: Path, *, acquired_at: str, public_rows: int) -> None:
        with closing(sqlite3.connect(path)) as connection, connection:
            connection.executescript(
                """
                PRAGMA user_version = 12;
                CREATE TABLE data_sources (id INTEGER PRIMARY KEY, source_key TEXT NOT NULL);
                CREATE TABLE source_snapshots (
                    id INTEGER PRIMARY KEY,
                    snapshot_ref TEXT NOT NULL,
                    acquired_at TEXT NOT NULL,
                    source_id INTEGER NOT NULL,
                    snapshot_kind TEXT NOT NULL,
                    upstream_version TEXT,
                    manifest_sha256 TEXT NOT NULL
                );
                CREATE TABLE source_artifacts (
                    id INTEGER PRIMARY KEY,
                    snapshot_id INTEGER NOT NULL,
                    artifact_ref TEXT NOT NULL,
                    logical_name TEXT NOT NULL,
                    media_type TEXT NOT NULL,
                    byte_size INTEGER NOT NULL,
                    sha256 TEXT NOT NULL,
                    vault_key TEXT NOT NULL
                );
                CREATE TABLE staged_records (
                    record_fingerprint TEXT NOT NULL,
                    artifact_id INTEGER,
                    record_ordinal INTEGER,
                    byte_offset INTEGER,
                    byte_length INTEGER,
                    exact_record_sha256 TEXT,
                    canonical_json_sha256 TEXT,
                    parse_status TEXT
                );
                CREATE TABLE source_objects (
                    id INTEGER PRIMARY KEY,
                    source_id INTEGER NOT NULL,
                    record_kind TEXT NOT NULL,
                    namespace TEXT NOT NULL,
                    scope_key TEXT NOT NULL,
                    external_id TEXT NOT NULL
                );
                CREATE TABLE source_object_observations (observation_fingerprint TEXT NOT NULL);
                CREATE TABLE artist_genre_evidence (
                    artist_id INTEGER NOT NULL,
                    genre_id INTEGER NOT NULL,
                    record_fingerprint TEXT NOT NULL
                );
                CREATE TABLE artist_co_listen_evidence (
                    evidence_fingerprint TEXT NOT NULL,
                    left_artist_source_id TEXT,
                    right_artist_source_id TEXT,
                    window_start INTEGER,
                    window_end INTEGER,
                    distinct_user_count INTEGER
                );
                CREATE TABLE album_genre_membership_observations (
                    record_fingerprint TEXT NOT NULL,
                    source_record_id TEXT,
                    source_genre_name TEXT,
                    evidence_kind TEXT,
                    evidence_level TEXT,
                    source_count INTEGER,
                    source_total INTEGER,
                    method_key TEXT,
                    method_version TEXT
                );
                CREATE TABLE recording_genre_membership_observations (
                    record_fingerprint TEXT NOT NULL,
                    source_record_id TEXT,
                    source_genre_name TEXT,
                    evidence_kind TEXT,
                    source_count INTEGER,
                    method_key TEXT,
                    method_version TEXT
                );
                CREATE TABLE genre_music_qualification_observations (
                    record_fingerprint TEXT NOT NULL,
                    root_qid TEXT,
                    path_depth INTEGER,
                    path_spec TEXT,
                    exclusion_profile TEXT,
                    statement_id TEXT,
                    statement_rank TEXT
                );
                CREATE TABLE public_model_runs (id INTEGER PRIMARY KEY, model_sha256 TEXT NOT NULL);
                """
            )
            connection.execute("INSERT INTO data_sources VALUES (?, ?)", (1, "source"))
            connection.execute(
                "INSERT INTO source_snapshots VALUES (?, ?, ?, ?, ?, ?, ?)",
                (1, "source:a", acquired_at, 1, "single_artifact", None, "a" * 64),
            )
            connection.execute(
                "INSERT INTO source_artifacts VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (1, 1, "artifact", "fixture", "application/json", 1, "b" * 64, "b" * 64),
            )
            connection.execute(
                "INSERT INTO artist_genre_evidence VALUES (?, ?, ?)", (4, 9, "c" * 64)
            )
            connection.executemany(
                "INSERT INTO public_model_runs VALUES (?, ?)",
                ((index, f"model-{index}") for index in range(public_rows)),
            )

    def test_distinguishes_timestamp_only_from_absent_materialization(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            candidate = root / "candidate.sqlite"
            sealed = root / "sealed.sqlite"
            self._database(candidate, acquired_at="2026-09-21T00:00:00Z", public_rows=0)
            self._database(sealed, acquired_at="2026-08-31T00:00:00Z", public_rows=1)
            comparison = compare_phase3_replay_databases(
                candidate,
                sealed,
                expected_candidate_sha256=_sha256(candidate),
                expected_sealed_sha256=_sha256(sealed),
            )
        tables = {table.table_name: table for table in comparison.tables}
        self.assertTrue(comparison.schema_equal)
        self.assertFalse(comparison.byte_identical)
        self.assertFalse(tables["source_snapshots"].exact_content_equal)
        self.assertTrue(tables["source_snapshots"].content_equal_without_acquired_at)
        self.assertTrue(tables["artist_genre_evidence"].exact_content_equal)
        self.assertFalse(tables["public_model_runs"].content_equal_without_acquired_at)
        self.assertEqual(tables["artist_genre_evidence"].classification, "core")
        self.assertEqual(tables["public_model_runs"].classification, "derived")
        self.assertEqual(tables["public_model_runs"].candidate_rows, 0)
        self.assertEqual(tables["public_model_runs"].sealed_rows, 1)

    def test_rejects_a_file_that_does_not_match_its_pin(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            candidate = root / "candidate.sqlite"
            sealed = root / "sealed.sqlite"
            self._database(candidate, acquired_at="candidate", public_rows=0)
            self._database(sealed, acquired_at="sealed", public_rows=0)
            with self.assertRaisesRegex(Phase3ReplayComparisonError, "SHA-256 mismatch"):
                compare_phase3_replay_databases(
                    candidate,
                    sealed,
                    expected_candidate_sha256="0" * 64,
                    expected_sealed_sha256=_sha256(sealed),
                )

    def test_checks_table_limit_before_hashing_its_rows(self) -> None:
        with closing(sqlite3.connect(":memory:")) as connection, connection:
            connection.execute("CREATE TABLE bounded (value INTEGER)")
            connection.executemany("INSERT INTO bounded VALUES (?)", ((1,), (2,)))
            with (
                patch(
                    "opennoise.pipeline.phase3_replay_comparator._table_sha256",
                    side_effect=AssertionError("table hash must not run"),
                ),
                self.assertRaisesRegex(Phase3ReplayComparisonError, "exceeding bounded limit 1"),
            ):
                _compare_table(connection, connection, "bounded", 1)

    def test_projection_limit_stops_after_maximum_plus_one_rows(self) -> None:
        with closing(sqlite3.connect(":memory:")) as connection, connection:
            connection.execute("CREATE TABLE values_for_limit (value INTEGER)")
            connection.executemany("INSERT INTO values_for_limit VALUES (?)", ((1,), (2,)))
            with self.assertRaisesRegex(Phase3ReplayComparisonError, "exceeds bounded limit 1"):
                _bounded_query_row_count(
                    connection,
                    "test-projection",
                    "SELECT value FROM values_for_limit ORDER BY value",
                    1,
                )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
