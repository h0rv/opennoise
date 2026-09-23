"""Tests for exact playlist-to-release-group identity evidence joins."""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from uuid import UUID

from opennoise.analysis.listenbrainz_playlist_release_group_overlap import (
    NativeReleaseGroupEvidence,
    PlaylistRecordingOccurrence,
    RecordingReleaseGroupIdentity,
    exact_catalog_paths,
    join_native_evidence,
    require_sha256,
)
from opennoise.ingest.musicbrainz.release_group_native_observation import (
    NativeGenreObservation,
    NativeTagObservation,
)
from scripts.audit_listenbrainz_playlist_release_group_overlap import (
    ExactOverlapReport,
    report_sha256,
)


class PlaylistReleaseGroupOverlapTests(unittest.TestCase):
    """Keep the join exact and source roles distinct."""

    def test_joins_only_the_exact_release_group_uuid_and_preserves_role(self) -> None:
        recording = UUID("520e2ef1-3775-4c54-a41b-3df1762141d0")
        group = UUID("966a02cf-fc62-3abc-8560-c60ce115efed")
        occurrences = (
            PlaylistRecordingOccurrence(
                playlist_mbid=UUID("9f591dc0-cc3f-4bcb-84f4-09a1af35989b"),
                recording_mbid=recording,
                ordinal=7,
                curator_kind="unknown",
            ),
        )
        identities = (
            RecordingReleaseGroupIdentity(
                recording_mbid=recording,
                release_group_mbid=group,
            ),
        )
        evidence = (
            NativeReleaseGroupEvidence(
                release_group_mbid=group,
                record_content_sha256="a" * 64,
                proper_genres=(
                    NativeGenreObservation(
                        genre_mbid="d4d1d1b8-6b7b-4b4d-9a01-d322af25b5de",
                        name="fixture genre",
                        vote_count=3,
                    ),
                ),
                positive_tags=(NativeTagObservation(name="fixture tag", vote_count=2),),
            ),
            NativeReleaseGroupEvidence(
                release_group_mbid=UUID("1477a3a0-ebb3-434c-8b29-5e986b85778b"),
                record_content_sha256="b" * 64,
                proper_genres=(),
                positive_tags=(NativeTagObservation(name="unrelated tag", vote_count=1),),
            ),
        )

        joined = join_native_evidence(occurrences, identities, evidence)

        self.assertEqual(len(joined), 1)
        self.assertEqual(joined[0].identity.release_group_mbid, group)
        self.assertEqual(joined[0].playlist_occurrences, occurrences)
        self.assertEqual(joined[0].playlist_occurrences[0].curator_kind, "unknown")
        self.assertEqual(joined[0].native_evidence.proper_genres[0].name, "fixture genre")
        self.assertEqual(joined[0].native_evidence.positive_tags[0].name, "fixture tag")

    def test_catalog_join_uses_type_keys_and_deduplicates_paths(self) -> None:
        recording = UUID("520e2ef1-3775-4c54-a41b-3df1762141d0")
        group = UUID("966a02cf-fc62-3abc-8560-c60ce115efed")
        wikidata_value = "3fa85f64-5717-4562-b3fc-2c963f66afa6"
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "catalog.sqlite"
            database = sqlite3.connect(database_path)
            database.executescript(
                """CREATE TABLE identifier_types (id INTEGER, type_key TEXT);
                   CREATE TABLE catalog_entities (id INTEGER, entity_kind TEXT);
                   CREATE TABLE entity_identifiers (
                       entity_id INTEGER, identifier_type_id INTEGER, value TEXT
                   );
                   CREATE TABLE tracks (medium_id INTEGER, recording_id INTEGER);
                   CREATE TABLE media (id INTEGER, release_id INTEGER);
                   CREATE TABLE releases (id INTEGER, release_group_id INTEGER);"""
            )
            database.executemany(
                "INSERT INTO identifier_types VALUES (?, ?)",
                (
                    (90, "wikidata_recording_qid"),
                    (4, "musicbrainz_release_group_id"),
                    (73, "musicbrainz_recording_id"),
                ),
            )
            database.executemany(
                "INSERT INTO catalog_entities VALUES (?, ?)",
                ((1, "recording"), (2, "release_group")),
            )
            database.executemany(
                "INSERT INTO entity_identifiers VALUES (?, ?, ?)",
                ((1, 90, wikidata_value), (1, 73, str(recording)), (2, 4, str(group))),
            )
            database.execute("INSERT INTO tracks VALUES (7, 1)")
            database.execute("INSERT INTO tracks VALUES (8, 1)")
            database.executemany("INSERT INTO media VALUES (?, ?)", ((7, 3), (8, 4)))
            database.executemany("INSERT INTO releases VALUES (?, ?)", ((3, 2), (4, 2)))
            database.commit()
            database.close()

            _, paths = exact_catalog_paths(database_path, frozenset({recording}))

        self.assertEqual(
            paths,
            (
                RecordingReleaseGroupIdentity(
                    recording_mbid=recording,
                    release_group_mbid=group,
                ),
            ),
        )

    def test_changed_source_hash_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "pinned SHA-256"):
            require_sha256("b" * 64, "a" * 64, "fixture source")

    def test_report_hash_replays_deterministically(self) -> None:
        report = ExactOverlapReport(
            playlist_bundle_sha256="a" * 64,
            playlist_count=1,
            playlist_unique_recording_count=1,
            musicbrainz_catalog_sha256="b" * 64,
            catalog_recording_count=1,
            exact_recording_overlap_count=1,
            exact_release_group_path_count=1,
            release_group_archive_sha256="e" * 64,
            release_group_archive_bytes=1,
            public_catalog_sha256="c" * 64,
            public_catalog_recording_count=1,
            public_catalog_exact_recording_overlap_count=1,
            source_cache_receipt_sha256="d" * 64,
            archive_records_seen=1,
            archive_records_malformed=0,
            archive_records_over_limit=0,
            requested_release_group_count=1,
            found_release_group_count=1,
            target_groups_with_proper_genres=1,
            target_proper_genre_observation_count=1,
            target_positive_tag_observation_count=0,
            overlaps=(),
            output_sha256="0" * 64,
        )
        hashed = report.model_copy(update={"output_sha256": report_sha256(report)})
        self.assertEqual(report_sha256(hashed), hashed.output_sha256)


if __name__ == "__main__":
    unittest.main()
