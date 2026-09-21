"""Materialize one isolated, cache-verified MusicBrainz artist-credit catalog."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from opennoise.db import Database
from opennoise.ingest.musicbrainz.artist_credit_enrichment import (
    ArtistCreditMember,
    ArtistCreditRefreshCandidateArtifact,
    CachedArtistCreditRelation,
    _parse_cached_release,
    _projection_sha256,
)
from opennoise.ingest.musicbrainz.catalog_candidate import _normalized_source_counts
from opennoise.ingest.musicbrainz.release_hydration import (
    CachedResponse,
    MusicBrainzHydrationError,
    MusicBrainzReleaseHydrationArtifact,
    materialize_hydration_catalog,
)

if TYPE_CHECKING:
    import sqlite3


CORE_HYDRATION_SHA256 = "9d2a7925eddf2cbf0260e502ca2b71d0a4ec92ac953d9e630f836adc08836ce3"
ARTIST_CREDIT_V2_SHA256 = "6454e5bfa4b4062e0bb7303629e0b5380af9997518ce386b896de69597496b7d"
_CREDIT_REVISION = "musicbrainz-artist-credit-catalog-candidate-v2"
_EXPECTED_PROVENANCE_RECORDS = 2


class _FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")


class ArtistCreditCatalogReport(_FrozenModel):
    """Receipt for a newly published, source-bound local catalog candidate."""

    revision: str = _CREDIT_REVISION
    source_hydration_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_credit_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    candidate_database_path: str
    database_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    release_relations: int = Field(ge=0)
    recording_relations: int = Field(ge=0)
    ordered_credit_members: int = Field(ge=0)
    artists: int = Field(ge=0)
    verified_cache_projections: int = Field(ge=0)
    provenance_record_count: int = Field(ge=0)
    first_core_materialization: dict[str, int]
    idempotent_core_replay: dict[str, int]
    foreign_key_violations: int = Field(ge=0)
    sealed_database_mutated: bool = False
    content_policy: str


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_file(path: Path) -> str:
    """Hash a finalized SQLite candidate without loading its full contents into memory."""
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _read_hashed(path: Path, expected_sha256: str, label: str) -> bytes:
    payload = path.read_bytes()
    if _sha256(payload) != expected_sha256:
        raise MusicBrainzHydrationError(f"{label} SHA-256 does not match the required source")
    return payload


def _fresh_staging_path(target: Path) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".staging", dir=target.parent
    )
    os.close(descriptor)
    staging = Path(name)
    staging.unlink()
    return staging


def _publish_no_replace(staging: Path, target: Path) -> None:
    try:
        os.link(staging, target)
    except FileExistsError as error:
        raise MusicBrainzHydrationError("candidate database target already exists") from error
    staging.unlink()


def write_artist_credit_catalog_report(report: ArtistCreditCatalogReport, *, output: Path) -> str:
    """Atomically publish one no-replace report bound to a finalized candidate database."""
    if output.exists() or output.is_symlink():
        raise MusicBrainzHydrationError("candidate report target already exists")
    payload = (report.model_dump_json() + "\n").encode()
    staging = _fresh_staging_path(output)
    try:
        staging.write_bytes(payload)
        _publish_no_replace(staging, output)
    finally:
        if staging.exists():
            staging.unlink()
    return _sha256(payload)


def _one_int(connection: sqlite3.Connection, query: str, values: tuple[object, ...] = ()) -> int:
    row = connection.execute(query, values).fetchone()
    if row is None:
        raise MusicBrainzHydrationError("catalog query returned no row")
    return int(row[0])


def _normalized_ids(artifact: MusicBrainzReleaseHydrationArtifact) -> tuple[set[UUID], set[UUID]]:
    release_ids: set[UUID] = set()
    recordings: set[UUID] = set()
    for release in artifact.releases:
        release_ids.add(release.release_id)
        for medium in release.media:
            for track in medium.tracks:
                recordings.add(track.recording_id)
    return release_ids, recordings


def _verified_cache_projections(
    *, cache_directory: Path, release_ids: set[UUID]
) -> dict[str, CachedResponse]:
    """Parse and rehash each selected v2 release cache before opening SQLite."""
    by_endpoint: dict[str, CachedResponse] = {}
    for path in sorted(cache_directory.glob("*.json")):
        try:
            cached = CachedResponse.model_validate_json(path.read_bytes())
        except ValueError as error:
            raise MusicBrainzHydrationError(
                f"invalid artist-credit cache entry: {path.name}"
            ) from error
        endpoint = cached.endpoint
        if not endpoint.startswith("release/"):
            continue
        release_text = endpoint.removeprefix("release/")
        try:
            release_id = UUID(release_text)
        except ValueError as error:
            raise MusicBrainzHydrationError(
                "artist-credit cache endpoint is not an exact release MBID"
            ) from error
        if release_id not in release_ids:
            raise MusicBrainzHydrationError(
                "artist-credit cache has an unselected release projection"
            )
        if cached.projection_sha256 is None:
            raise MusicBrainzHydrationError("artist-credit cache projection lacks v2 SHA-256")
        if (
            _projection_sha256(endpoint=endpoint, payload=cached.payload)
            != cached.projection_sha256
        ):
            raise MusicBrainzHydrationError("artist-credit cache projection SHA-256 mismatch")
        if endpoint in by_endpoint:
            raise MusicBrainzHydrationError("artist-credit cache repeats a release projection")
        by_endpoint[endpoint] = cached
    expected = {f"release/{release_id}" for release_id in release_ids}
    if set(by_endpoint) != expected:
        raise MusicBrainzHydrationError(
            "artist-credit cache does not exactly cover selected releases"
        )
    return by_endpoint


def _validate_credit_partition(  # noqa: C901 - explicit artifact/cache relation boundary.
    *,
    artifact: ArtistCreditRefreshCandidateArtifact,
    release_ids: set[UUID],
    recording_ids: set[UUID],
    cache: dict[str, CachedResponse],
) -> tuple[CachedArtistCreditRelation, ...]:
    """Make the artifact an exact total release/recording relation partition."""
    if len(artifact.requested_release_ids) != len(set(artifact.requested_release_ids)):
        raise MusicBrainzHydrationError("artist-credit artifact repeats requested release IDs")
    if set(artifact.requested_release_ids) != release_ids:
        raise MusicBrainzHydrationError(
            "artist-credit artifact requested releases do not match hydration"
        )
    if artifact.abstentions or artifact.failures:
        raise MusicBrainzHydrationError(
            "artist-credit artifact is not a complete verified relation partition"
        )
    expected_keys = {("release", release_id) for release_id in release_ids} | {
        ("recording", recording_id) for recording_id in recording_ids
    }
    observed_keys = {(relation.entity_kind, relation.entity_id) for relation in artifact.credits}
    if len(observed_keys) != len(artifact.credits) or observed_keys != expected_keys:
        raise MusicBrainzHydrationError(
            "artist-credit artifact relations are not an exact unique partition"
        )
    for relation in artifact.credits:
        cached = cache.get(relation.source_endpoint)
        if cached is None or (
            cached.response_sha256 != relation.observed_response_sha256
            or cached.projection_sha256 != relation.projection_sha256
        ):
            raise MusicBrainzHydrationError(
                "artist-credit relation is not bound to its verified cache projection"
            )
        if tuple(member.position for member in relation.members) != tuple(
            range(len(relation.members))
        ):
            raise MusicBrainzHydrationError("artist-credit members are not ordered from zero")
        parsed = _parse_cached_release(cached)
        if parsed.id != UUID(relation.source_endpoint.removeprefix("release/")):
            raise MusicBrainzHydrationError(
                "artist-credit cache endpoint does not match payload MBID"
            )
        if relation.entity_kind == "release":
            source_members = parsed.artist_credit
        else:
            source_members = {
                track.recording.id: track.recording.artist_credit
                for medium in parsed.media
                for track in medium.tracks
            }.get(relation.entity_id)
        if source_members is None:
            raise MusicBrainzHydrationError(
                "artist-credit relation is absent from its cache projection"
            )
        expected_members = tuple(
            ArtistCreditMember(
                position=position,
                artist_id=member.artist.id,
                artist_name=member.artist.name,
                credited_name=member.name,
                join_phrase=member.joinphrase,
            )
            for position, member in enumerate(source_members)
        )
        if relation.members != expected_members:
            raise MusicBrainzHydrationError(
                "artist-credit relation members do not match its cache projection"
            )
    return tuple(sorted(artifact.credits, key=lambda item: (item.entity_kind, str(item.entity_id))))


def _credit_provenance(
    connection: sqlite3.Connection, credit_sha256: str, hydration_sha256: str
) -> int:
    policy_id = _one_int(
        connection,
        "SELECT id FROM rights_policies WHERE policy_key = ? AND policy_version = 1",
        ("musicbrainz-core-metadata-hydration",),
    )
    source_key = "musicbrainz_public_artist_credit_refresh"
    connection.execute(
        """INSERT OR IGNORE INTO data_sources
           (source_key, name, homepage_url, license_name, license_url,
            acquisition_kind, default_policy_id)
           VALUES (?, 'MusicBrainz artist-credit refresh', 'https://musicbrainz.org/', 'CC0',
                   'https://musicbrainz.org/doc/About/Data_License', 'public_api', ?)""",
        (source_key, policy_id),
    )
    source_id = _one_int(
        connection, "SELECT id FROM data_sources WHERE source_key = ?", (source_key,)
    )
    fingerprint = _sha256(f"{_CREDIT_REVISION}\0{hydration_sha256}\0{credit_sha256}".encode())
    snapshot = f"artist-credit:{credit_sha256}"
    connection.execute(
        """INSERT OR IGNORE INTO provenance_records
           (source_id, policy_id, snapshot_ref, artifact_sha256, record_fingerprint,
            parser_release_ref, ingest_attempt_ref, observed_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, '1970-01-01T00:00:00.000Z')""",
        (source_id, policy_id, snapshot, credit_sha256, fingerprint, _CREDIT_REVISION, snapshot),
    )
    return _one_int(
        connection,
        "SELECT id FROM provenance_records WHERE source_id = ? "
        "AND snapshot_ref = ? AND record_fingerprint = ?",
        (source_id, snapshot, fingerprint),
    )


def _catalog_entity(connection: sqlite3.Connection, kind: str, mbid: UUID) -> int:
    type_key = f"musicbrainz_{kind}_id"
    row = connection.execute(
        """SELECT identifier.entity_id FROM entity_identifiers AS identifier
           JOIN identifier_types AS type ON type.id = identifier.identifier_type_id
           JOIN catalog_entities AS entity ON entity.id = identifier.entity_id
           WHERE type.type_key = ? AND identifier.namespace = 'musicbrainz'
             AND identifier.normalized_value = ? AND entity.entity_kind = ?""",
        (type_key, str(mbid), kind),
    ).fetchone()
    if row is None:
        raise MusicBrainzHydrationError(
            "artist-credit relation does not reference a hydrated entity"
        )
    return int(row[0])


def _artist(
    connection: sqlite3.Connection,
    relation: CachedArtistCreditRelation,
    position: int,
    provenance_id: int,
) -> int:
    member = relation.members[position]
    connection.execute(
        "INSERT OR IGNORE INTO identifier_types (type_key, name) "
        "VALUES ('musicbrainz_artist_id', 'MusicBrainz Artist ID')"
    )
    type_id = _one_int(
        connection, "SELECT id FROM identifier_types WHERE type_key = 'musicbrainz_artist_id'"
    )
    row = connection.execute(
        """SELECT entity_id FROM entity_identifiers WHERE identifier_type_id = ?
           AND namespace = 'musicbrainz' AND normalized_value = ?""",
        (type_id, str(member.artist_id)),
    ).fetchone()
    if row is None:
        cursor = connection.execute("INSERT INTO catalog_entities (entity_kind) VALUES ('artist')")
        if cursor.lastrowid is None:
            raise MusicBrainzHydrationError("artist entity insert returned no ID")
        artist_id = int(cursor.lastrowid)
        connection.execute("INSERT INTO artists (id) VALUES (?)", (artist_id,))
    else:
        artist_id = int(row[0])
    connection.execute(
        """INSERT OR IGNORE INTO entity_identifiers
           (entity_id, identifier_type_id, namespace, value, normalized_value, provenance_id)
           VALUES (?, ?, 'musicbrainz', ?, ?, ?)""",
        (artist_id, type_id, str(member.artist_id), str(member.artist_id), provenance_id),
    )
    connection.execute(
        """INSERT OR IGNORE INTO entity_provenance
           (entity_id, provenance_id, field_set_json, is_primary)
           VALUES (?, ?, '[\"artist_credit\"]', 0)""",
        (artist_id, provenance_id),
    )
    fingerprint = _sha256(f"{artist_id}\0primary\0{member.artist_name}".encode())
    connection.execute(
        """INSERT OR IGNORE INTO entity_names
           (entity_id, name_kind, name, language_tag, is_preferred, provenance_id, fingerprint)
           VALUES (?, 'primary', ?, 'und', 1, ?, ?)""",
        (artist_id, member.artist_name, provenance_id, fingerprint),
    )
    return artist_id


def _persist_credits(
    connection: sqlite3.Connection,
    relations: tuple[CachedArtistCreditRelation, ...],
    provenance_id: int,
) -> None:
    for relation in relations:
        entity_id = _catalog_entity(connection, relation.entity_kind, relation.entity_id)
        canonical = json.dumps(
            [member.model_dump(mode="json") for member in relation.members],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        credit_key = _sha256(f"musicbrainz\0{canonical}".encode())
        connection.execute(
            "INSERT OR IGNORE INTO artist_credits (credit_key, provenance_id) VALUES (?, ?)",
            (credit_key, provenance_id),
        )
        credit_id = _one_int(
            connection, "SELECT id FROM artist_credits WHERE credit_key = ?", (credit_key,)
        )
        for position, member in enumerate(relation.members):
            artist_id = _artist(connection, relation, position, provenance_id)
            connection.execute(
                """INSERT OR IGNORE INTO artist_credit_members
                   (artist_credit_id, position, artist_id, credited_name, join_phrase)
                   VALUES (?, ?, ?, ?, ?)""",
                (credit_id, position, artist_id, member.credited_name, member.join_phrase),
            )
        connection.execute(
            """INSERT OR IGNORE INTO entity_artist_credits
               (entity_id, credit_kind, artist_credit_id, provenance_id)
               VALUES (?, 'primary', ?, ?)""",
            (entity_id, credit_id, provenance_id),
        )


def materialize_artist_credit_candidate(  # noqa: PLR0913 - public artifact boundary has six inputs.
    *,
    hydration_artifact_path: Path,
    credit_artifact_path: Path,
    cache_directory: Path,
    candidate_database_path: Path,
    report_path: Path | None = None,
    expected_hydration_sha256: str = CORE_HYDRATION_SHA256,
    expected_credit_sha256: str = ARTIST_CREDIT_V2_SHA256,
) -> ArtistCreditCatalogReport:
    """Rehash inputs, verify cache projections, then atomically publish a fresh local catalog."""
    if candidate_database_path.exists() or candidate_database_path.is_symlink():
        raise MusicBrainzHydrationError("candidate database target already exists")
    if report_path is not None and (report_path.exists() or report_path.is_symlink()):
        raise MusicBrainzHydrationError("candidate report target already exists")
    hydration_payload = _read_hashed(
        hydration_artifact_path, expected_hydration_sha256, "hydration artifact"
    )
    credit_payload = _read_hashed(
        credit_artifact_path, expected_credit_sha256, "artist-credit artifact"
    )
    hydration = MusicBrainzReleaseHydrationArtifact.model_validate_json(hydration_payload)
    credit = ArtistCreditRefreshCandidateArtifact.model_validate_json(credit_payload)
    if credit.source_hydration_sha256 != expected_hydration_sha256:
        raise MusicBrainzHydrationError(
            "artist-credit artifact is bound to a different hydration SHA-256"
        )
    normalized_releases, _, _ = _normalized_source_counts(hydration)
    release_ids, recording_ids = _normalized_ids(hydration)
    cache = _verified_cache_projections(cache_directory=cache_directory, release_ids=release_ids)
    relations = _validate_credit_partition(
        artifact=credit, release_ids=release_ids, recording_ids=recording_ids, cache=cache
    )
    staging = _fresh_staging_path(candidate_database_path)
    try:
        first = materialize_hydration_catalog(
            hydration, database_path=staging, artifact_sha256=expected_hydration_sha256
        )
        replay = materialize_hydration_catalog(
            hydration, database_path=staging, artifact_sha256=expected_hydration_sha256
        )
        database = Database(staging)
        with database.connect() as connection:
            provenance_id = _credit_provenance(
                connection, expected_credit_sha256, expected_hydration_sha256
            )
            _persist_credits(connection, relations, provenance_id)
            _persist_credits(connection, relations, provenance_id)
            connection.commit()
            foreign_key_violations = _one_int(
                connection, "SELECT count(*) FROM pragma_foreign_key_check"
            )
            release_relations = _one_int(
                connection,
                "SELECT count(*) FROM entity_artist_credits AS link "
                "JOIN releases ON releases.id = link.entity_id "
                "WHERE link.provenance_id = ?",
                (provenance_id,),
            )
            recording_relations = _one_int(
                connection,
                "SELECT count(*) FROM entity_artist_credits AS link "
                "JOIN recordings ON recordings.id = link.entity_id "
                "WHERE link.provenance_id = ?",
                (provenance_id,),
            )
            members = _one_int(
                connection,
                "SELECT count(*) FROM entity_artist_credits AS link "
                "JOIN artist_credit_members AS member "
                "ON member.artist_credit_id = link.artist_credit_id "
                "WHERE link.provenance_id = ?",
                (provenance_id,),
            )
            artists = _one_int(
                connection,
                "SELECT count(*) FROM artists AS artist "
                "JOIN entity_provenance AS source ON source.entity_id = artist.id "
                "WHERE source.provenance_id = ?",
                (provenance_id,),
            )
            provenance_records = _one_int(connection, "SELECT count(*) FROM provenance_records")
            core_provenance_id = _one_int(
                connection,
                "SELECT id FROM provenance_records WHERE artifact_sha256 = ?",
                (expected_hydration_sha256,),
            )
            core_releases = _one_int(
                connection,
                "SELECT count(*) FROM releases AS release "
                "JOIN entity_provenance AS source ON source.entity_id = release.id "
                "WHERE source.provenance_id = ?",
                (core_provenance_id,),
            )
            core_recordings = _one_int(
                connection,
                "SELECT count(*) FROM recordings AS recording "
                "JOIN entity_provenance AS source ON source.entity_id = recording.id "
                "WHERE source.provenance_id = ?",
                (core_provenance_id,),
            )
        expected_members = sum(len(relation.members) for relation in relations)
        if (
            foreign_key_violations
            or provenance_records != _EXPECTED_PROVENANCE_RECORDS
            or (
                release_relations,
                recording_relations,
                members,
            )
            != (
                len(release_ids),
                len(recording_ids),
                expected_members,
            )
            or (core_releases, core_recordings) != (normalized_releases, len(recording_ids))
        ):
            raise MusicBrainzHydrationError(
                "artist-credit candidate coverage or foreign-key check failed"
            )
        with Database(staging).connect() as connection:
            connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            connection.execute("PRAGMA journal_mode = DELETE")
        _publish_no_replace(staging, candidate_database_path)
        database_sha256 = _sha256_file(candidate_database_path)
        report = ArtistCreditCatalogReport(
            source_hydration_sha256=expected_hydration_sha256,
            source_credit_sha256=expected_credit_sha256,
            candidate_database_path=str(candidate_database_path),
            database_sha256=database_sha256,
            release_relations=release_relations,
            recording_relations=recording_relations,
            ordered_credit_members=members,
            artists=artists,
            verified_cache_projections=len(cache),
            provenance_record_count=provenance_records,
            first_core_materialization=first.model_dump(mode="json"),
            idempotent_core_replay=replay.model_dump(mode="json"),
            foreign_key_violations=foreign_key_violations,
            content_policy=hydration.content_policy,
        )
        if report_path is not None:
            write_artist_credit_catalog_report(report, output=report_path)
        return report
    finally:
        if staging.exists():
            staging.unlink()
