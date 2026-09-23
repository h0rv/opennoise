"""Tests for the counts-only AcousticBrainz Discogs exact-ID audit."""

from __future__ import annotations

import bz2
import hashlib
import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from opennoise.analysis.acousticbrainz_discogs_overlap import (
    AcousticBrainzDiscogsOverlapError,
    audit_acousticbrainz_discogs_validation_overlap,
)

RECORDING_A = "00000000-0000-4000-8000-000000000001"
RECORDING_B = "00000000-0000-4000-8000-000000000002"
GROUP_A = "10000000-0000-4000-8000-000000000001"
GROUP_B = "10000000-0000-4000-8000-000000000002"


def _write_catalog(path: Path) -> None:
    with sqlite3.connect(path) as database:
        database.executescript(
            """
            CREATE TABLE recordings (id INTEGER PRIMARY KEY);
            CREATE TABLE identifier_types (id INTEGER PRIMARY KEY, type_key TEXT);
            CREATE TABLE entity_identifiers (
                entity_id INTEGER, identifier_type_id INTEGER, normalized_value TEXT
            );
            CREATE TABLE tracks (recording_id INTEGER, medium_id INTEGER);
            CREATE TABLE media (id INTEGER PRIMARY KEY, release_id INTEGER);
            CREATE TABLE releases (id INTEGER PRIMARY KEY, release_group_id INTEGER);
            CREATE TABLE release_groups (id INTEGER PRIMARY KEY);
            CREATE TABLE entity_artist_credits (
                entity_id INTEGER, credit_kind TEXT, artist_credit_id INTEGER
            );
            CREATE TABLE artist_credit_members (
                artist_credit_id INTEGER, artist_id INTEGER, position INTEGER
            );
            INSERT INTO recordings VALUES (1), (2), (3);
            INSERT INTO identifier_types VALUES
                (1, 'musicbrainz_recording_id'), (2, 'musicbrainz_release_group_id');
            INSERT INTO entity_identifiers VALUES
                (1, 1, '00000000-0000-4000-8000-000000000001'),
                (2, 1, '00000000-0000-4000-8000-000000000002'),
                (3, 1, '00000000-0000-4000-8000-000000000003'),
                (11, 2, '10000000-0000-4000-8000-000000000001'),
                (12, 2, '10000000-0000-4000-8000-000000000002');
            INSERT INTO tracks VALUES (1, 21), (2, 22), (3, 23);
            INSERT INTO media VALUES (21, 31), (22, 32), (23, 33);
            INSERT INTO releases VALUES (31, 11), (32, 12), (33, 11);
            INSERT INTO release_groups VALUES (11), (12);
            INSERT INTO entity_artist_credits VALUES
                (1, 'primary', 41), (2, 'primary', 42),
                (3, 'primary', 43), (3, 'primary', 44);
            INSERT INTO artist_credit_members VALUES
                (41, 51, 0), (42, 52, 0), (42, 53, 1),
                (43, 54, 0), (44, 54, 0);
            """
        )


class AcousticBrainzDiscogsOverlapTests(TestCase):
    def test_counts_exact_ids_without_retaining_or_reading_labels(self) -> None:
        with TemporaryDirectory() as temporary:
            directory = Path(temporary)
            source = directory / "discogs.tsv.bz2"
            source_bytes = (
                "recordingmbid\treleasegroupmbid\tgenre1\n"
                f"{RECORDING_A}\t{GROUP_A}\tlabel-that-must-not-appear\n"
                f"{RECORDING_B}\t{GROUP_A}\tanother-label\n"
                "00000000-0000-4000-8000-000000000003\t"
                "10000000-0000-4000-8000-000000000001\tthird-label\n"
            ).encode()
            source.write_bytes(bz2.compress(source_bytes))
            catalog = directory / "catalog.sqlite"
            _write_catalog(catalog)

            with patch(
                "opennoise.analysis.acousticbrainz_discogs_overlap._PUBLISHED_MD5",
                hashlib.md5(source.read_bytes(), usedforsecurity=False).hexdigest(),
            ):
                report = audit_acousticbrainz_discogs_validation_overlap(source, catalog)

        self.assertEqual(report.source_data_rows, 3)
        self.assertEqual(report.exact_recording_mbid_overlap_count, 3)
        self.assertEqual(report.exact_release_group_consistent_overlap_count, 2)
        self.assertEqual(report.release_group_mismatch_overlap_count, 1)
        self.assertEqual(report.one_primary_artist_overlap_count, 1)
        self.assertEqual(report.one_primary_artist_release_group_consistent_overlap_count, 1)
        self.assertFalse(report.label_columns_read)
        self.assertNotIn("label-that-must-not-appear", report.model_dump_json())

    def test_rejects_unverified_source_bytes(self) -> None:
        with TemporaryDirectory() as temporary:
            directory = Path(temporary)
            source = directory / "discogs.tsv.bz2"
            source.write_bytes(bz2.compress(b"recordingmbid\treleasegroupmbid\n"))
            catalog = directory / "catalog.sqlite"
            _write_catalog(catalog)

            with self.assertRaises(AcousticBrainzDiscogsOverlapError):
                audit_acousticbrainz_discogs_validation_overlap(
                    source,
                    catalog,
                )
