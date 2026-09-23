import hashlib
import io
import json
import sqlite3
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pydantic import ValidationError

from opennoise.analysis.lastfm_360k import (
    LastFm360kAggregateArtifact,
    LastFm360kProbeError,
    LastFm360kSettings,
    audit_lastfm_360k_source_order,
    load_lastfm_360k_sealed_v1_envelope,
    run_lastfm_360k_full_aggregate,
)

_ARTIST_A = "00000000-0000-4000-8000-000000000001"
_ARTIST_B = "00000000-0000-4000-8000-000000000002"


def _archive(path: Path, rows: list[bytes]) -> tuple[str, str]:
    plays = b"".join(rows)
    with tarfile.open(path, "w:gz") as archive:
        plays_info = tarfile.TarInfo("lastfm-dataset-360K/usersha1-artmbid-artname-plays.tsv")
        plays_info.size = len(plays)
        archive.addfile(plays_info, io.BytesIO(plays))
        profile = b"secret-user-hash\tprivate-demographic\n"
        profile_info = tarfile.TarInfo("lastfm-dataset-360K/usersha1-profile.tsv")
        profile_info.size = len(profile)
        archive.addfile(profile_info, io.BytesIO(profile))
    return hashlib.md5(path.read_bytes(), usedforsecurity=False).hexdigest(), hashlib.md5(
        plays, usedforsecurity=False
    ).hexdigest()


def _catalog(path: Path) -> None:
    with sqlite3.connect(path) as database:
        database.executescript(
            """CREATE TABLE identifier_types (id INTEGER PRIMARY KEY, type_key TEXT);
               CREATE TABLE entity_identifiers (identifier_type_id INTEGER, normalized_value TEXT);
               INSERT INTO identifier_types VALUES (1, 'musicbrainz_artist_id');"""
        )
        database.execute("INSERT INTO entity_identifiers VALUES (1, ?)", (_ARTIST_A,))


def _row(user: str, artist: str, play_count: int = 1) -> bytes:
    return f"{user}\t{artist}\tdiscarded artist name\t{play_count}\n".encode()


class LastFm360kTests(unittest.TestCase):
    def test_source_order_audit_counts_ties_and_user_blocks(self) -> None:
        rows = [
            _row("first", _ARTIST_A, 10),
            _row("first", _ARTIST_B, 10),
            _row("first", _ARTIST_A, 4),
            _row("second", _ARTIST_A, 2),
        ]
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "source.tar.gz"
            archive_md5, plays_md5 = _archive(archive, rows)
            with (
                patch("opennoise.analysis.lastfm_360k._ARCHIVE_MD5", archive_md5),
                patch("opennoise.analysis.lastfm_360k._PLAYS_MD5", plays_md5),
            ):
                audit = audit_lastfm_360k_source_order(
                    archive_path=archive,
                    settings=LastFm360kSettings(maximum_rows=len(rows)),
                )
            expected_archive_sha256 = hashlib.sha256(archive.read_bytes()).hexdigest()
        self.assertEqual(audit.contiguous_user_block_count, 2)
        self.assertEqual(audit.source_archive_sha256, expected_archive_sha256)
        self.assertEqual(audit.within_user_adjacent_comparison_count, 2)
        self.assertEqual(audit.adjacent_play_count_decrease_count, 1)
        self.assertEqual(audit.adjacent_play_count_tie_count, 1)
        self.assertEqual(
            audit.selection_strategy,
            "first_ten_unique_valid_exact_artist_mbids_by_nonincreasing_source_play_count",
        )

    def test_source_order_audit_rejects_a_late_increase(self) -> None:
        rows = [_row("first", _ARTIST_A, 4), _row("first", _ARTIST_B, 5)]
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "source.tar.gz"
            archive_md5, plays_md5 = _archive(archive, rows)
            with (
                patch("opennoise.analysis.lastfm_360k._ARCHIVE_MD5", archive_md5),
                patch("opennoise.analysis.lastfm_360k._PLAYS_MD5", plays_md5),
                self.assertRaisesRegex(LastFm360kProbeError, "not non-increasing"),
            ):
                audit_lastfm_360k_source_order(
                    archive_path=archive,
                    settings=LastFm360kSettings(maximum_rows=len(rows)),
                )

    def test_emits_aggregate_only_after_five_distinct_user_blocks(self) -> None:
        rows = [
            _row(f"user-{index}", artist) for index in range(5) for artist in (_ARTIST_A, _ARTIST_B)
        ]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "source.tar.gz"
            catalog = root / "catalog.sqlite"
            working = root / "working.sqlite"
            archive_md5, plays_md5 = _archive(archive, rows)
            _catalog(catalog)
            with (
                patch("opennoise.analysis.lastfm_360k._ARCHIVE_MD5", archive_md5),
                patch("opennoise.analysis.lastfm_360k._PLAYS_MD5", plays_md5),
            ):
                artifact = run_lastfm_360k_full_aggregate(
                    archive_path=archive,
                    catalog_path=catalog,
                    working_database_path=working,
                    settings=LastFm360kSettings(maximum_rows=len(rows)),
                )
            with sqlite3.connect(working) as database:
                self.assertEqual(
                    database.execute(
                        "SELECT MIN(distinct_user_count) FROM pair_support"
                    ).fetchone()[0],
                    5,
                )
        self.assertEqual(artifact.completed_user_block_count, 5)
        self.assertEqual(artifact.catalog_exact_artist_overlap_count, 1)
        self.assertEqual(artifact.privacy_filtered_pair_count, 1)
        self.assertTrue(artifact.working_database_local_aggregate_custody)
        self.assertTrue(artifact.working_database_has_no_user_ids)
        self.assertEqual(artifact.working_database_pair_floor, 5)
        serialized = artifact.model_dump_json()
        self.assertNotIn("user-0", serialized)
        self.assertNotIn(_ARTIST_A, serialized)
        self.assertNotIn("private-demographic", serialized)

    def test_rejects_reappearing_user_block(self) -> None:
        rows = [_row("first", _ARTIST_A), _row("second", _ARTIST_B), _row("first", _ARTIST_B)]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "source.tar.gz"
            catalog = root / "catalog.sqlite"
            archive_md5, plays_md5 = _archive(archive, rows)
            _catalog(catalog)
            with (
                patch("opennoise.analysis.lastfm_360k._ARCHIVE_MD5", archive_md5),
                patch("opennoise.analysis.lastfm_360k._PLAYS_MD5", plays_md5),
                self.assertRaisesRegex(LastFm360kProbeError, "not grouped"),
            ):
                run_lastfm_360k_full_aggregate(
                    archive_path=archive,
                    catalog_path=catalog,
                    working_database_path=root / "working.sqlite",
                    settings=LastFm360kSettings(maximum_rows=len(rows)),
                )
            self.assertFalse((root / "working.sqlite").exists())

    def test_binds_completed_v1_artifact_to_separate_custody_receipt(self) -> None:
        rows = [
            _row(f"user-{index}", artist) for index in range(5) for artist in (_ARTIST_A, _ARTIST_B)
        ]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "source.tar.gz"
            catalog = root / "catalog.sqlite"
            working = root / "working.sqlite"
            artifact_path = root / "original-v1.json"
            receipt_path = root / "receipt.json"
            archive_md5, plays_md5 = _archive(archive, rows)
            _catalog(catalog)
            with (
                patch("opennoise.analysis.lastfm_360k._ARCHIVE_MD5", archive_md5),
                patch("opennoise.analysis.lastfm_360k._PLAYS_MD5", plays_md5),
            ):
                current = run_lastfm_360k_full_aggregate(
                    archive_path=archive,
                    catalog_path=catalog,
                    working_database_path=working,
                    settings=LastFm360kSettings(maximum_rows=len(rows)),
                )
            original_payload = current.model_dump()
            for field in (
                "working_database_local_aggregate_custody",
                "working_database_has_no_user_ids",
                "working_database_pair_floor",
                "working_database_byte_size",
                "working_database_sha256",
                "elapsed_seconds",
            ):
                original_payload.pop(field)
            original_bytes = json.dumps(original_payload, separators=(",", ":")).encode()
            artifact_path.write_bytes(original_bytes)
            with self.assertRaises(ValidationError):
                LastFm360kAggregateArtifact.model_validate_json(original_bytes)
            receipt_path.write_text(
                json.dumps(
                    {
                        "revision": "lastfm-360k-full-aggregate-receipt-v1",
                        "local_only": True,
                        "export_allowed": False,
                        "serving_allowed": False,
                        "model_input_allowed": False,
                        "independent_genre_gold": False,
                        "source_aggregate_artifact_logical_sha256": hashlib.sha256(
                            original_bytes
                        ).hexdigest(),
                        "working_database_local_aggregate_custody": True,
                        "working_database_has_no_user_ids": True,
                        "working_database_pair_floor": 5,
                        "working_database_byte_size": working.stat().st_size,
                        "working_database_sha256": hashlib.sha256(working.read_bytes()).hexdigest(),
                        "privacy_filtered_pair_count": 1,
                        "minimum_retained_pair_distinct_user_count": 5,
                        "maximum_retained_pair_distinct_user_count": 5,
                        "retained_pair_rows_below_privacy_floor": 0,
                        "notes": "local aggregate custody only",
                    }
                ),
                encoding="utf-8",
            )
            envelope = load_lastfm_360k_sealed_v1_envelope(
                artifact_path=artifact_path,
                companion_receipt_path=receipt_path,
                database_path=working,
            )
            with working.open("r+b") as stream:
                stream.seek(0)
                stream.write(b"!")
            with self.assertRaisesRegex(LastFm360kProbeError, "hash"):
                load_lastfm_360k_sealed_v1_envelope(
                    artifact_path=artifact_path,
                    companion_receipt_path=receipt_path,
                    database_path=working,
                )
        self.assertEqual(
            envelope.original_artifact_sha256, hashlib.sha256(original_bytes).hexdigest()
        )
        self.assertEqual(envelope.companion_receipt.working_database_pair_floor, 5)
