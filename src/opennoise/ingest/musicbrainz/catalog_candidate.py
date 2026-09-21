"""Materialize a source-bound, local-only MusicBrainz hydration candidate."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field

from opennoise.db import Database
from opennoise.ingest.musicbrainz.release_hydration import (
    MusicBrainzHydrationError,
    MusicBrainzReleaseHydrationArtifact,
    artifact_counts,
    materialize_hydration_catalog,
)

if TYPE_CHECKING:
    import sqlite3


class _FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")


class CandidateRelationCounts(_FrozenModel):
    """Exact normalized relations retained in one local candidate database."""

    release_to_release_group: int = Field(ge=0)
    medium_to_release: int = Field(ge=0)
    track_to_medium_and_recording: int = Field(ge=0)
    artist_credit_relations: int = Field(ge=0)


class CandidateMaterializationReport(_FrozenModel):
    """Replay receipt for a separate, metadata-only candidate database."""

    revision: str = "musicbrainz-catalog-candidate-materialization-v1"
    source_artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_artifact_path: str = Field(min_length=1)
    candidate_database_path: str = Field(min_length=1)
    source_counts: dict[str, int]
    first_materialization: dict[str, int]
    idempotent_replay: dict[str, int]
    normalized_relation_counts: CandidateRelationCounts
    provenance_record_count: int = Field(ge=1)
    foreign_key_violations: int = Field(ge=0)
    artist_relation_status: str
    sealed_database_mutated: bool = False
    content_policy: str


def sha256_file(path: Path) -> str:
    """Return the content hash that is bound into candidate provenance."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_source_artifact(
    path: Path, *, expected_sha256: str
) -> tuple[MusicBrainzReleaseHydrationArtifact, str]:
    """Parse a hydration artifact only when its caller-declared hash matches."""
    payload = path.read_bytes()
    observed_sha256 = hashlib.sha256(payload).hexdigest()
    if observed_sha256 != expected_sha256:
        raise MusicBrainzHydrationError("hydration artifact SHA-256 does not match expected source")
    return MusicBrainzReleaseHydrationArtifact.model_validate_json(payload), observed_sha256


def _row_count(connection: sqlite3.Connection, query: str, values: tuple[object, ...] = ()) -> int:
    row = connection.execute(query, values).fetchone()
    if row is None:
        raise MusicBrainzHydrationError("candidate count query returned no row")
    return int(row[0])


def _canonical_structure(value: object) -> str:
    """Compare repeated selected rows while deliberately excluding selection evidence."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _normalized_source_counts(
    artifact: MusicBrainzReleaseHydrationArtifact,
) -> tuple[int, int, int]:
    """Count catalog identities and reject conflicting duplicate selections."""
    releases: dict[str, str] = {}
    media: dict[tuple[str, int], str] = {}
    tracks: dict[str, str] = {}
    for release in artifact.releases:
        release_id = str(release.release_id)
        release_structure = release.model_dump(mode="json", exclude={"evidence"})
        previous_release = releases.setdefault(release_id, _canonical_structure(release_structure))
        if previous_release != _canonical_structure(release_structure):
            raise MusicBrainzHydrationError(
                "source artifact repeats a release with conflicting metadata"
            )
        for medium in release.media:
            medium_key = (release_id, medium.position)
            medium_structure = medium.model_dump(mode="json")
            previous_medium = media.setdefault(medium_key, _canonical_structure(medium_structure))
            if previous_medium != _canonical_structure(medium_structure):
                raise MusicBrainzHydrationError(
                    "source artifact repeats a medium with conflicting metadata"
                )
            for track in medium.tracks:
                track_id = str(track.track_id)
                track_structure = {
                    "release_id": release_id,
                    "medium_position": medium.position,
                    **track.model_dump(mode="json"),
                }
                previous_track = tracks.setdefault(track_id, _canonical_structure(track_structure))
                if previous_track != _canonical_structure(track_structure):
                    raise MusicBrainzHydrationError(
                        "source artifact repeats a track with conflicting metadata"
                    )
    return len(releases), len(media), len(tracks)


def _fresh_staging_path(candidate_database_path: Path) -> Path:
    """Reserve a same-directory staging name without creating a candidate target."""
    candidate_database_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, staging_name = tempfile.mkstemp(
        prefix=f".{candidate_database_path.name}.",
        suffix=".staging",
        dir=candidate_database_path.parent,
    )
    os.close(descriptor)
    staging_path = Path(staging_name)
    staging_path.unlink()
    return staging_path


def _publish_fresh_database(*, staging_path: Path, candidate_database_path: Path) -> None:
    """Publish a staged database only if no target name exists at publication time."""
    try:
        # link(2) is an atomic no-replace publication primitive when both paths share a directory.
        os.link(staging_path, candidate_database_path)
    except FileExistsError as error:
        raise MusicBrainzHydrationError("candidate database target already exists") from error
    staging_path.unlink()


def _seal_staged_database(staging_path: Path) -> None:
    """Checkpoint WAL contents into the single database file before publication."""
    database = Database(staging_path)
    with database.connect() as connection:
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        connection.execute("PRAGMA journal_mode = DELETE")


def materialize_candidate(
    *, source_artifact_path: Path, candidate_database_path: Path
) -> CandidateMaterializationReport:
    """Build a freshly published candidate database from the source artifact bytes on disk."""
    if candidate_database_path.exists() or candidate_database_path.is_symlink():
        raise MusicBrainzHydrationError("candidate database target already exists")
    artifact_payload = source_artifact_path.read_bytes()
    source_artifact_sha256 = hashlib.sha256(artifact_payload).hexdigest()
    artifact = MusicBrainzReleaseHydrationArtifact.model_validate_json(artifact_payload)
    staging_path = _fresh_staging_path(candidate_database_path)
    try:
        first = materialize_hydration_catalog(
            artifact, database_path=staging_path, artifact_sha256=source_artifact_sha256
        )
        replay = materialize_hydration_catalog(
            artifact, database_path=staging_path, artifact_sha256=source_artifact_sha256
        )
        _seal_staged_database(staging_path)
        database = Database(staging_path, read_only=True)
        with database.connect() as connection:
            foreign_key_violations = _row_count(
                connection, "SELECT count(*) FROM pragma_foreign_key_check"
            )
            provenance_records = _row_count(
                connection,
                "SELECT count(*) FROM provenance_records WHERE artifact_sha256 = ?",
                (source_artifact_sha256,),
            )
            total_provenance_records = _row_count(
                connection, "SELECT count(*) FROM provenance_records"
            )
            provenance_id = _row_count(
                connection,
                "SELECT id FROM provenance_records WHERE artifact_sha256 = ?",
                (source_artifact_sha256,),
            )
            relations = CandidateRelationCounts(
                release_to_release_group=_row_count(
                    connection,
                    "SELECT count(*) FROM releases AS release "
                    "JOIN release_groups AS group_row ON group_row.id = release.release_group_id",
                ),
                medium_to_release=_row_count(
                    connection,
                    "SELECT count(*) FROM media AS medium "
                    "JOIN releases AS release ON release.id = medium.release_id",
                ),
                track_to_medium_and_recording=_row_count(
                    connection,
                    "SELECT count(*) FROM tracks AS track "
                    "JOIN media AS medium ON medium.id = track.medium_id "
                    "JOIN recordings AS recording ON recording.id = track.recording_id",
                ),
                artist_credit_relations=_row_count(
                    connection, "SELECT count(*) FROM entity_artist_credits"
                ),
            )
            source_scoped_counts = (
                _row_count(
                    connection,
                    "SELECT count(*) FROM releases AS release "
                    "JOIN entity_provenance AS source ON source.entity_id = release.id "
                    "WHERE source.provenance_id = ?",
                    (provenance_id,),
                ),
                _row_count(
                    connection,
                    "SELECT count(*) FROM media AS medium "
                    "JOIN entity_provenance AS source ON source.entity_id = medium.id "
                    "WHERE source.provenance_id = ?",
                    (provenance_id,),
                ),
                _row_count(
                    connection,
                    "SELECT count(*) FROM tracks AS track "
                    "JOIN entity_provenance AS source ON source.entity_id = track.id "
                    "WHERE source.provenance_id = ?",
                    (provenance_id,),
                ),
            )
        if foreign_key_violations:
            raise MusicBrainzHydrationError("candidate database has foreign-key violations")
        if provenance_records != 1 or total_provenance_records != 1:
            raise MusicBrainzHydrationError(
                "candidate database must contain exactly one provenance row"
            )
        source_releases, source_media, source_tracks = artifact_counts(artifact)
        releases, media, tracks = _normalized_source_counts(artifact)
        actual_relation_counts = (
            relations.release_to_release_group,
            relations.medium_to_release,
            relations.track_to_medium_and_recording,
        )
        if actual_relation_counts != (
            releases,
            media,
            tracks,
        ):
            raise MusicBrainzHydrationError(
                "candidate database does not preserve hydration relations"
            )
        if source_scoped_counts != (releases, media, tracks):
            raise MusicBrainzHydrationError(
                "candidate database source-scoped counts do not match artifact"
            )
        _publish_fresh_database(
            staging_path=staging_path, candidate_database_path=candidate_database_path
        )
        return CandidateMaterializationReport(
            source_artifact_sha256=source_artifact_sha256,
            source_artifact_path=str(source_artifact_path),
            candidate_database_path=str(candidate_database_path),
            source_counts={
                "release_entries": source_releases,
                "medium_entries": source_media,
                "track_entries": source_tracks,
                "normalized_releases": releases,
                "normalized_media": media,
                "normalized_tracks": tracks,
            },
            first_materialization=first.model_dump(mode="json"),
            idempotent_replay=replay.model_dump(mode="json"),
            normalized_relation_counts=relations,
            provenance_record_count=provenance_records,
            foreign_key_violations=foreign_key_violations,
            artist_relation_status=(
                "abstained_no_artist_credits_in_source_hydration_artifact"
                if relations.artist_credit_relations == 0
                else "preserved_from_source_hydration_artifact"
            ),
            content_policy=artifact.content_policy,
        )
    finally:
        if staging_path.exists():
            staging_path.unlink()
