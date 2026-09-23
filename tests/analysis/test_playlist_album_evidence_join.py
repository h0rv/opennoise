"""Tests for the bounded, role-preserving playlist and album context join."""

from __future__ import annotations

import hashlib
import io
import json
import sqlite3
import tarfile
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch
from uuid import UUID

from opennoise.analysis.listenbrainz_playlist_release_group_overlap import (
    NativeReleaseGroupEvidence,
    PlaylistRecordingOccurrence,
    PlaylistReleaseGroupOverlap,
    RecordingReleaseGroupIdentity,
)
from opennoise.analysis.playlist_album_evidence_join import (
    PlaylistAlbumEvidenceJoinError,
    ReleaseGroupCreditedArtistEvidence,
    join_playlist_album_evidence,
    read_exact_release_group_artist_credits,
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
                artist_credits=_credits(),
                artist_credit_archive_sha256="e" * 64,
                artist_credit_archive_bytes=1,
            )

        self.assertEqual(report.requested_release_group_count, 2)
        self.assertEqual(report.revision, "playlist-album-evidence-join-v2")
        self.assertEqual(report.release_groups_with_native_proper_genres, 1)
        self.assertEqual(report.release_groups_with_credited_artist_evidence, 1)
        self.assertEqual(report.credited_artists_with_direct_evidence, 2)
        self.assertEqual(len(report.contexts), 2)
        context = report.contexts[0]
        self.assertEqual(context.release_group_mbid, _GROUP_A)
        self.assertEqual(context.playlist_role, "listenbrainz_playlist_track")
        self.assertEqual(context.native_release_group_role, "native_release_group_proper_genre")
        self.assertEqual(
            context.credited_artists[0].role, "musicbrainz_release_group_artist_credit"
        )
        self.assertEqual(context.credited_artists[0].artist_mbid, _ARTIST_A)
        self.assertEqual(context.credited_artists[0].credit_position, 0)
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
                    artist_credits=_credits(),
                    artist_credit_archive_sha256="e" * 64,
                    artist_credit_archive_bytes=1,
                )

    def test_reads_ordered_artist_credits_only_when_the_raw_record_replays(self) -> None:
        body = json.dumps(
            {
                "id": _GROUP_A,
                "title": "Fixture album",
                "artist-credit": [
                    {
                        "artist": {"id": _ARTIST_A, "name": "Artist A"},
                        "name": "A credited",
                        "joinphrase": " & ",
                    },
                    {
                        "artist": {"id": _ARTIST_B, "name": "Artist B"},
                        "name": "B credited",
                    },
                ],
            },
            separators=(",", ":"),
        ).encode()
        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary) / "release-group.tar.xz"
            _archive(archive, body)
            overlap = _overlaps()[0].model_copy(
                update={
                    "native_evidence": _overlaps()[0].native_evidence.model_copy(
                        update={"record_content_sha256": hashlib.sha256(body).hexdigest()}
                    )
                }
            )
            artist_credits = read_exact_release_group_artist_credits(archive, (overlap,))

        self.assertEqual(
            [item.artist_mbid for item in artist_credits[_GROUP_A]], [_ARTIST_A, _ARTIST_B]
        )
        self.assertEqual(artist_credits[_GROUP_A][0].credited_name, "A credited")
        self.assertEqual(artist_credits[_GROUP_A][1].credit_position, 1)

    def test_skips_irrelevant_records_before_decode_and_rejects_duplicate_target(self) -> None:
        target = _credit_record(_GROUP_A)
        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary) / "release-group.tar.xz"
            _archive(
                archive,
                *(
                    _credit_record(f"00000000-0000-4000-8000-000000000{index:03d}")
                    for index in range(100, 110)
                ),
                target,
                target,
            )
            overlap = _overlaps()[0].model_copy(
                update={
                    "native_evidence": _overlaps()[0].native_evidence.model_copy(
                        update={"record_content_sha256": hashlib.sha256(target).hexdigest()}
                    )
                }
            )
            with (
                patch(
                    "opennoise.analysis.playlist_album_evidence_join.json.loads",
                    wraps=json.loads,
                ) as loads,
                self.assertRaisesRegex(PlaylistAlbumEvidenceJoinError, "repeats"),
            ):
                read_exact_release_group_artist_credits(archive, (overlap,))

        self.assertEqual(loads.call_count, 2)


def _database(path: Path) -> Path:
    with closing(sqlite3.connect(path)) as database, database:
        database.executescript(
            """CREATE TABLE direct_anchor (
                   genre_id TEXT, artist_id TEXT, facet TEXT, evidence_ref TEXT
               );
               """
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


def _credits() -> dict[str, tuple[ReleaseGroupCreditedArtistEvidence, ...]]:
    return {
        _GROUP_A: (
            ReleaseGroupCreditedArtistEvidence(
                artist_mbid=_ARTIST_A,
                artist_name="Artist A",
                credited_name="Artist A",
                credit_position=0,
                joinphrase=" & ",
                record_content_sha256="d" * 64,
            ),
            ReleaseGroupCreditedArtistEvidence(
                artist_mbid=_ARTIST_B,
                artist_name="Artist B",
                credited_name="Artist B",
                credit_position=1,
                joinphrase="",
                record_content_sha256="d" * 64,
            ),
        ),
        _GROUP_B: (),
    }


def _credit_record(release_group: str) -> bytes:
    return json.dumps(
        {
            "id": release_group,
            "title": "Fixture album",
            "artist-credit": [
                {
                    "artist": {"id": _ARTIST_A, "name": "Artist A"},
                    "name": "Artist A",
                }
            ],
        },
        separators=(",", ":"),
    ).encode()


def _archive(path: Path, *bodies: bytes) -> None:
    with tarfile.open(path, "w:xz") as archive:
        schema = tarfile.TarInfo("JSON_DUMPS_SCHEMA_NUMBER")
        schema.size = 2
        archive.addfile(schema, io.BytesIO(b"1\n"))
        member = tarfile.TarInfo("mbdump/release-group")
        payload = b"\n".join(bodies) + b"\n"
        member.size = len(payload)
        archive.addfile(member, io.BytesIO(payload))


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
