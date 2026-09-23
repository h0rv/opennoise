"""Tests for the bounded, role-preserving playlist and album context join."""

from __future__ import annotations

import hashlib
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from uuid import UUID

from opennoise.analysis.listenbrainz_playlist_release_group_overlap import (
    NativeReleaseGroupEvidence,
    PlaylistRecordingOccurrence,
    PlaylistReleaseGroupOverlap,
    RecordingReleaseGroupIdentity,
)
from opennoise.analysis.playlist_album_evidence_join import (
    PlaylistAlbumEvidenceJoinError,
    join_playlist_album_evidence,
    report_sha256,
)
from opennoise.ingest.musicbrainz.release_group_evidence import ReleaseGroupEvidenceArtifact
from opennoise.ingest.musicbrainz.release_group_native_observation import NativeGenreObservation

_ARTIST_A = "00000000-0000-4000-8000-000000000001"
_ARTIST_B = "00000000-0000-4000-8000-000000000002"
_GROUP_A = "00000000-0000-4000-8000-000000000010"
_GROUP_B = "00000000-0000-4000-8000-000000000011"


class PlaylistAlbumEvidenceJoinTests(unittest.TestCase):
    def test_exact_join_preserves_independent_roles_and_abstains_without_native_genre(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            database = _database(Path(temporary) / "evidence.sqlite")
            report = join_playlist_album_evidence(
                _overlaps(),
                playlist_overlap_report_sha256="a" * 64,
                evidence_database=database,
                evidence_artifact=_artifact(database),
            )

        self.assertEqual(report.requested_release_group_count, 2)
        self.assertEqual(report.release_groups_with_native_proper_genres, 1)
        self.assertEqual(report.release_groups_with_credited_artist_evidence, 1)
        self.assertEqual(report.credited_artists_with_direct_evidence, 2)
        self.assertEqual(len(report.contexts), 2)
        context = report.contexts[0]
        self.assertEqual(context.release_group_mbid, _GROUP_A)
        self.assertEqual(context.playlist_role, "listenbrainz_playlist_track")
        self.assertEqual(context.native_release_group_role, "native_release_group_proper_genre")
        self.assertEqual(context.credited_artists[0].role, "release_group_credited_artist")
        self.assertEqual(context.credited_artists[0].artist_mbid, _ARTIST_A)
        self.assertEqual(
            context.direct_anchor_artist_seed_evidence[0].role,
            "musicbrainz_direct_anchor_artist_seed",
        )
        self.assertEqual(context.direct_anchor_artist_seed_evidence[0].artist_mbid, _ARTIST_A)
        self.assertEqual(context.direct_anchor_artist_seed_evidence[0].seed_id, "seed-direct-a")
        self.assertEqual(context.direct_anchor_artist_seed_evidence[1].artist_mbid, _ARTIST_B)
        self.assertEqual(context.direct_anchor_artist_seed_evidence[1].seed_id, "seed-direct-b")
        self.assertFalse(context.artist_membership_asserted)
        self.assertFalse(context.genre_membership_inferred_from_context)
        abstention = report.contexts[1]
        self.assertEqual(abstention.native_proper_genre_status, "no_native_proper_genre")
        self.assertEqual(abstention.native_release_group_evidence[0].proper_genres, ())
        self.assertEqual(abstention.credited_artists, ())
        self.assertEqual(abstention.direct_anchor_artist_seed_evidence, ())
        self.assertEqual(report_sha256(report), report.output_sha256)

    def test_rejects_a_database_that_does_not_match_the_evidence_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            database = _database(Path(temporary) / "evidence.sqlite")
            artifact = _artifact(database).model_copy(update={"evidence_database_sha256": "b" * 64})
            with self.assertRaisesRegex(PlaylistAlbumEvidenceJoinError, "does not match"):
                join_playlist_album_evidence(
                    _overlaps(),
                    playlist_overlap_report_sha256="a" * 64,
                    evidence_database=database,
                    evidence_artifact=artifact,
                )


def _database(path: Path) -> Path:
    with closing(sqlite3.connect(path)) as database, database:
        database.executescript(
            """CREATE TABLE direct_anchor (
                   genre_id TEXT, artist_id TEXT, facet TEXT, evidence_ref TEXT
               );
               CREATE TABLE release_group_support (
                   genre_id TEXT, artist_id TEXT, facet TEXT,
                   release_group_id TEXT, evidence_ref TEXT
               );"""
        )
        database.executemany(
            "INSERT INTO release_group_support VALUES (?, ?, ?, ?, ?)",
            (
                ("seed-context", _ARTIST_A, "musicbrainz_genre", _GROUP_A, "album:a"),
                ("seed-context", _ARTIST_B, "musicbrainz_tag", _GROUP_A, "album:b"),
            ),
        )
        database.execute(
            "INSERT INTO direct_anchor VALUES (?, ?, 'musicbrainz_genre', ?)",
            ("seed-direct-a", _ARTIST_A, "direct:a"),
        )
        database.execute(
            "INSERT INTO direct_anchor VALUES (?, ?, 'musicbrainz_tag', ?)",
            ("seed-direct-b", _ARTIST_B, "direct:b"),
        )
    return path


def _artifact(database: Path) -> ReleaseGroupEvidenceArtifact:
    content = database.read_bytes()
    return ReleaseGroupEvidenceArtifact.model_construct(
        evidence_database_sha256=hashlib.sha256(content).hexdigest(),
        evidence_database_bytes=len(content),
        output_sha256="c" * 64,
    )


def _overlaps() -> tuple[PlaylistReleaseGroupOverlap, ...]:
    playlist = UUID("00000000-0000-4000-8000-000000000020")
    recording_a = UUID("00000000-0000-4000-8000-000000000030")
    recording_b = UUID("00000000-0000-4000-8000-000000000031")
    return (
        _overlap(playlist, recording_a, _GROUP_A, include_proper_genre=True),
        _overlap(playlist, recording_b, _GROUP_B, include_proper_genre=False),
    )


def _overlap(
    playlist: UUID, recording: UUID, release_group: str, *, include_proper_genre: bool
) -> PlaylistReleaseGroupOverlap:
    group = UUID(release_group)
    return PlaylistReleaseGroupOverlap(
        identity=RecordingReleaseGroupIdentity(recording_mbid=recording, release_group_mbid=group),
        playlist_occurrences=(
            PlaylistRecordingOccurrence(
                playlist_mbid=playlist,
                recording_mbid=recording,
                ordinal=0,
                curator_kind="unknown",
            ),
        ),
        native_evidence=NativeReleaseGroupEvidence(
            release_group_mbid=group,
            record_content_sha256="d" * 64,
            proper_genres=(
                NativeGenreObservation(
                    genre_mbid="00000000-0000-4000-8000-000000000040",
                    name="fixture genre",
                    vote_count=1,
                ),
            )
            if include_proper_genre
            else (),
            positive_tags=(),
        ),
    )
