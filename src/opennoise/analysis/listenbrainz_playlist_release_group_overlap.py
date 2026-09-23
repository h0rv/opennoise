"""Exact local identity joins from playlist tracks to native release-group evidence."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from typing import TYPE_CHECKING, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from opennoise.ingest.listenbrainz.playlists import (
    CuratorKind,
    PublicPlaylistSnapshotBundle,
    _verify_raw_playlist_object,
)
from opennoise.ingest.musicbrainz.release_group_native_observation import (
    NativeGenreObservation,  # noqa: TC001
    NativeTagObservation,  # noqa: TC001
)

if TYPE_CHECKING:
    from pathlib import Path


class _FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")


class PlaylistRecordingOccurrence(_FrozenModel):
    """One retained recording UUID occurrence and its source playlist role."""

    playlist_mbid: UUID
    recording_mbid: UUID
    ordinal: int = Field(ge=0)
    membership_source_role: Literal["listenbrainz_playlist_track"] = "listenbrainz_playlist_track"
    curator_kind: CuratorKind


class RecordingReleaseGroupIdentity(_FrozenModel):
    """One exact recording-to-release-group path from the local MusicBrainz catalog."""

    recording_mbid: UUID
    release_group_mbid: UUID


class NativeReleaseGroupEvidence(_FrozenModel):
    """Native MusicBrainz proper genres and positive tags for one exact group."""

    release_group_mbid: UUID
    record_content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    proper_genres: tuple[NativeGenreObservation, ...]
    positive_tags: tuple[NativeTagObservation, ...]


class PlaylistReleaseGroupOverlap(_FrozenModel):
    """An exact UUID path with its original playlist and native evidence roles."""

    identity: RecordingReleaseGroupIdentity
    playlist_occurrences: tuple[PlaylistRecordingOccurrence, ...]
    native_evidence: NativeReleaseGroupEvidence


class ExactPlaylistReleaseGroupOverlapReport(_FrozenModel):
    """Local-only receipt for exact playlist recording-to-release-group evidence."""

    revision: Literal["listenbrainz-playlist-release-group-overlap-v1"] = (
        "listenbrainz-playlist-release-group-overlap-v1"
    )
    local_only: Literal[True] = True
    export_allowed: Literal[False] = False
    serving_allowed: Literal[False] = False
    model_input_allowed: Literal[False] = False
    artist_membership_asserted: Literal[False] = False
    genre_membership_inferred_from_playlist: Literal[False] = False
    playlist_bundle_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    playlist_count: int = Field(ge=1)
    playlist_unique_recording_count: int = Field(ge=1)
    curator_status: Literal["unknown"] = "unknown"
    membership_source_role: Literal["listenbrainz_playlist_track"] = "listenbrainz_playlist_track"
    musicbrainz_catalog_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    catalog_recording_count: int = Field(ge=0)
    exact_recording_overlap_count: int = Field(ge=0)
    exact_release_group_path_count: int = Field(ge=0)
    public_catalog_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    public_catalog_recording_count: int = Field(ge=0)
    public_catalog_exact_recording_overlap_count: int = Field(ge=0)
    release_group_archive_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    release_group_archive_bytes: int = Field(gt=0)
    source_cache_receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    archive_records_seen: int = Field(ge=0)
    archive_records_malformed: int = Field(ge=0)
    archive_records_over_limit: int = Field(ge=0)
    requested_release_group_count: int = Field(ge=0)
    found_release_group_count: int = Field(ge=0)
    target_groups_with_proper_genres: int = Field(ge=0)
    target_proper_genre_observation_count: int = Field(ge=0)
    target_positive_tag_observation_count: int = Field(ge=0)
    overlaps: tuple[PlaylistReleaseGroupOverlap, ...]
    output_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


def overlap_report_sha256(report: ExactPlaylistReleaseGroupOverlapReport) -> str:
    """Return the deterministic report hash excluding its self-reference."""
    payload = json.dumps(
        report.model_dump(mode="json", exclude={"output_sha256"}),
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    """Hash a regular local artifact without changing it."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def require_sha256(actual: str, expected: str, input_name: str) -> None:
    """Reject changed source artifacts before a report can be built."""
    if actual != expected:
        raise ValueError(f"{input_name} differs from its pinned SHA-256")


def load_playlist_occurrences(
    bundle_path: Path, raw_object_directory: Path
) -> tuple[str, PublicPlaylistSnapshotBundle, tuple[PlaylistRecordingOccurrence, ...]]:
    """Validate a retained bundle and every referenced raw JSPF object."""
    payload = bundle_path.read_bytes()
    bundle = PublicPlaylistSnapshotBundle.model_validate_json(payload)
    for snapshot in bundle.snapshots:
        _verify_raw_playlist_object(snapshot.receipt, raw_object_directory)
    occurrences = tuple(
        PlaylistRecordingOccurrence(
            playlist_mbid=snapshot.playlist_mbid,
            recording_mbid=recording.recording_mbid,
            ordinal=recording.ordinal,
            curator_kind=snapshot.curator_kind,
        )
        for snapshot in bundle.snapshots
        for recording in snapshot.recordings
    )
    return hashlib.sha256(payload).hexdigest(), bundle, occurrences


def exact_recording_ids(database_path: Path) -> tuple[str, frozenset[UUID]]:
    """Read MusicBrainz recording UUIDs through the database-local type key."""
    digest = sha256_file(database_path)
    database = sqlite3.connect(f"file:{database_path}?mode=ro", uri=True)
    try:
        rows = database.execute(
            """SELECT DISTINCT identifier.value
               FROM entity_identifiers AS identifier
               JOIN identifier_types AS identifier_type
                 ON identifier_type.id = identifier.identifier_type_id
               JOIN catalog_entities AS entity ON entity.id = identifier.entity_id
               WHERE entity.entity_kind = 'recording'
                 AND identifier_type.type_key = 'musicbrainz_recording_id'
               ORDER BY identifier.value"""
        ).fetchall()
    finally:
        database.close()
    return digest, frozenset(UUID(row[0]) for row in rows)


def exact_catalog_paths(
    database_path: Path, recording_ids: frozenset[UUID]
) -> tuple[str, tuple[RecordingReleaseGroupIdentity, ...]]:
    """Join exact MusicBrainz recording and release-group UUIDs using the local catalog."""
    digest = sha256_file(database_path)
    database = sqlite3.connect(f"file:{database_path}?mode=ro", uri=True)
    database.row_factory = sqlite3.Row
    try:
        rows = database.execute(
            """SELECT DISTINCT recording_identifier.value AS recording_mbid,
                      release_group_identifier.value AS release_group_mbid
               FROM tracks AS track
               JOIN media AS medium ON medium.id = track.medium_id
               JOIN releases AS release ON release.id = medium.release_id
               JOIN entity_identifiers AS recording_identifier
                 ON recording_identifier.entity_id = track.recording_id
               JOIN identifier_types AS recording_identifier_type
                 ON recording_identifier_type.id = recording_identifier.identifier_type_id
                AND recording_identifier_type.type_key = 'musicbrainz_recording_id'
               JOIN entity_identifiers AS release_group_identifier
                 ON release_group_identifier.entity_id = release.release_group_id
               JOIN identifier_types AS release_group_identifier_type
                 ON release_group_identifier_type.id = release_group_identifier.identifier_type_id
                AND release_group_identifier_type.type_key = 'musicbrainz_release_group_id'
               JOIN catalog_entities AS recording_entity
                 ON recording_entity.id = recording_identifier.entity_id
                AND recording_entity.entity_kind = 'recording'
               JOIN catalog_entities AS release_group_entity
                 ON release_group_entity.id = release_group_identifier.entity_id
                AND release_group_entity.entity_kind = 'release_group'
               ORDER BY recording_identifier.value, release_group_identifier.value"""
        ).fetchall()
    finally:
        database.close()
    identities = tuple(
        RecordingReleaseGroupIdentity(
            recording_mbid=UUID(row["recording_mbid"]),
            release_group_mbid=UUID(row["release_group_mbid"]),
        )
        for row in rows
        if UUID(row["recording_mbid"]) in recording_ids
    )
    return digest, identities


def join_native_evidence(
    occurrences: tuple[PlaylistRecordingOccurrence, ...],
    identities: tuple[RecordingReleaseGroupIdentity, ...],
    evidence: tuple[NativeReleaseGroupEvidence, ...],
) -> tuple[PlaylistReleaseGroupOverlap, ...]:
    """Join source roles only on exact UUIDs, preserving multiple-group paths."""
    occurrence_index: dict[UUID, list[PlaylistRecordingOccurrence]] = {}
    for occurrence in occurrences:
        occurrence_index.setdefault(occurrence.recording_mbid, []).append(occurrence)
    evidence_index = {item.release_group_mbid: item for item in evidence}
    result = []
    for identity in identities:
        group_evidence = evidence_index.get(identity.release_group_mbid)
        matching_occurrences = occurrence_index.get(identity.recording_mbid)
        if group_evidence is None or matching_occurrences is None:
            continue
        result.append(
            PlaylistReleaseGroupOverlap(
                identity=identity,
                playlist_occurrences=tuple(matching_occurrences),
                native_evidence=group_evidence,
            )
        )
    return tuple(result)
