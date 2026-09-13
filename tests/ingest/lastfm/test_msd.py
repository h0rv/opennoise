from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from opennoise.ingest.lastfm.msd import (
    MsdLastFmError,
    MsdLastFmTarget,
    build_msd_lastfm_evidence,
    cache_msd_lastfm_sqlite_files,
    load_msd_lastfm_source_cache,
    publish_msd_lastfm_evidence,
)
from opennoise.storage import LocalObjectStore


class MsdLastFmEvidenceTests(unittest.TestCase):
    def test_streams_exact_mbid_support_reviews_similarity_conflicts_and_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            metadata, tags, similarity = self._fixture_databases(root)
            cache = cache_msd_lastfm_sqlite_files(
                metadata_db=metadata,
                tags_db=tags,
                similarity_db=similarity,
                cache_root=root / "cache",
            )
            self.assertEqual(cache.files[0].provenance, "unverified_local_input")
            self.assertFalse(cache.files[0].acquisition_attested)
            targets = (
                MsdLastFmTarget(target_id="rock", label="Rock", normalized_label="rock"),
                MsdLastFmTarget(target_id="jazz", label="Jazz", normalized_label="jazz"),
            )
            artifact = build_msd_lastfm_evidence(cache, targets)
            source_receipt = root / "cache" / "receipts" / "sha256" / f"{cache.output_sha256}.json"
            receipt = publish_msd_lastfm_evidence(
                artifact,
                source_cache_receipt=source_receipt,
                output=root / "evidence.json",
                store=LocalObjectStore(root / "objects"),
            )

            self.assertEqual(artifact.coverage.target_count, 2)
            self.assertEqual(artifact.coverage.exact_mbid_track_tag_support_count, 3)
            self.assertEqual(artifact.coverage.name_only_review_count, 1)
            self.assertEqual(artifact.coverage.similarity_support_count, 1)
            self.assertEqual(artifact.coverage.conflict_count, 1)
            self.assertEqual(artifact.coverage.abstention_count, 0)
            self.assertEqual(artifact.tag_supports[0].evidence_kind, "exact_track_tag_support")
            self.assertEqual(artifact.name_only_reviews[0].artist_name, "No MBID")
            self.assertEqual(receipt.logical_output_sha256, artifact.output_sha256)
            self.assertTrue((root / "evidence.json").is_file())

    def test_fails_closed_on_tag_output_cap(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            metadata, tags, similarity = self._fixture_databases(root)
            cache = cache_msd_lastfm_sqlite_files(
                metadata_db=metadata,
                tags_db=tags,
                similarity_db=similarity,
                cache_root=root / "cache",
            )
            targets = (MsdLastFmTarget(target_id="rock", label="Rock", normalized_label="rock"),)
            with self.assertRaisesRegex(MsdLastFmError, "maximum_tag_supports"):
                build_msd_lastfm_evidence(cache, targets, maximum_tag_supports=1)

    def test_fails_closed_on_duplicate_exact_tag_rows(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            metadata, tags, similarity = self._fixture_databases(root)
            with sqlite3.connect(tags) as connection:
                connection.execute("INSERT INTO tid_tag VALUES (1, 1, 90)")
            cache = cache_msd_lastfm_sqlite_files(
                metadata_db=metadata,
                tags_db=tags,
                similarity_db=similarity,
                cache_root=root / "cache",
            )
            targets = (MsdLastFmTarget(target_id="rock", label="Rock", normalized_label="rock"),)
            with self.assertRaisesRegex(MsdLastFmError, "duplicate exact Last.fm tag support"):
                build_msd_lastfm_evidence(cache, targets)

    def test_cache_receipt_fails_closed_when_a_raw_sqlite_file_changes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            metadata, tags, similarity = self._fixture_databases(root)
            cache = cache_msd_lastfm_sqlite_files(
                metadata_db=metadata,
                tags_db=tags,
                similarity_db=similarity,
                cache_root=root / "cache",
            )
            receipt = root / "cache" / "receipts" / "sha256" / f"{cache.output_sha256}.json"
            raw_tag_path = next(
                Path(item.cache_path) for item in cache.files if item.role == "lastfm_tags"
            )
            raw_tag_path.write_bytes(b"not sqlite")
            with self.assertRaisesRegex(MsdLastFmError, "does not match"):
                load_msd_lastfm_source_cache(receipt)

    @staticmethod
    def _fixture_databases(root: Path) -> tuple[Path, Path, Path]:
        metadata = root / "metadata.db"
        tags = root / "tags.db"
        similarity = root / "similarity.db"
        with sqlite3.connect(metadata) as connection:
            connection.executescript(
                """
                CREATE TABLE songs (track_id TEXT PRIMARY KEY, artist_mbid TEXT, artist_name TEXT);
                INSERT INTO songs VALUES
                  ('TR1', '10000000-0000-4000-8000-000000000001', 'MBID Artist'),
                  ('TR2', '10000000-0000-4000-8000-000000000001', 'MBID Artist'),
                  ('TR3', '', 'No MBID'),
                  ('TR4', '20000000-0000-4000-8000-000000000002', 'Peer Artist');
                """
            )
        with sqlite3.connect(tags) as connection:
            connection.executescript(
                """
                CREATE TABLE tids (tid TEXT);
                CREATE TABLE tags (tag TEXT);
                CREATE TABLE tid_tag (tid INTEGER, tag INTEGER, val INTEGER);
                INSERT INTO tids VALUES ('TR1'), ('TR2'), ('TR3'), ('TR4');
                INSERT INTO tags VALUES ('rock'), ('jazz');
                INSERT INTO tid_tag VALUES (1, 1, 90), (1, 2, 20), (2, 1, 80), (3, 2, 50);
                """
            )
        with sqlite3.connect(similarity) as connection:
            connection.executescript(
                """
                CREATE TABLE similars_src (tid TEXT, target TEXT);
                INSERT INTO similars_src VALUES ('TR1', '[["TR4", 0.9]]');
                """
            )
        return metadata, tags, similarity
