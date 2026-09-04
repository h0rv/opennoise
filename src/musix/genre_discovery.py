"""Policy-safe persistence for dated genre discovery observations."""

import hashlib
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from musix.adapters.everynoise import (
    QUINT_SOURCE,
    HistoricalAdaptationResult,
    HistoricalGenreMemberRecord,
    HistoricalGenreMembershipAdaptationResult,
    HistoricalRepresentativeRecord,
)
from musix.db import Database


class DiscoveryImportSummary(BaseModel):
    """Counts from one idempotent historical observation projection."""

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    representative_artists: int = Field(ge=0)
    representative_tracks: int = Field(ge=0)
    parser_quarantine: int = Field(ge=0)
    unmatched_genres: int = Field(ge=0)


class GenreMembershipImportSummary(BaseModel):
    """Counts from a source-scoped H3 membership import."""

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    genre_memberships: int = Field(ge=0)
    distinct_source_artists: int = Field(ge=0)
    matched_genres: int = Field(ge=0)
    unmatched_genres: int = Field(ge=0)
    discarded_preview_metadata_count: int = Field(ge=0)
    discarded_sample_metadata_count: int = Field(ge=0)
    discarded_track_identifier_count: int = Field(ge=0)
    empty_genre_rows: int = Field(ge=0)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _fingerprint(*values: str) -> str:
    digest = hashlib.sha256()
    for value in values:
        digest.update(value.encode())
        digest.update(b"\0")
    return digest.hexdigest()


def _source_context(
    connection: sqlite3.Connection,
    source_key: str,
) -> int:
    row = connection.execute(
        "SELECT id FROM data_sources WHERE source_key = ?",
        (source_key,),
    ).fetchone()
    if row is None:
        raise RuntimeError("Every Noise source must be normalized before discovery metadata")
    return int(row[0])


def _seal_local_discovery_policy(connection: sqlite3.Connection, source_sha256: str) -> int:
    policy_key = f"historical-discovery-local:{source_sha256}"
    basis = "Bounded public metadata research approved for local normalization only."
    connection.execute(
        """INSERT OR IGNORE INTO rights_policies
           (policy_key, policy_version, classification, local_only, basis, reviewed_at)
           VALUES (?, 1, 'user_authorized_local', 1, ?, ?)""",
        (policy_key, basis, _now()),
    )
    row = connection.execute(
        "SELECT id FROM rights_policies WHERE policy_key = ? AND policy_version = 1",
        (policy_key,),
    ).fetchone()
    if row is None:
        raise RuntimeError("historical discovery policy registration failed")
    policy_id = int(row[0])
    sealed = connection.execute(
        "SELECT 1 FROM rights_policy_seals WHERE policy_id = ?", (policy_id,)
    ).fetchone()
    if sealed is None:
        for use_kind in ("normalize", "local_search", "display", "embed", "train", "export"):
            decision = "allow" if use_kind == "normalize" else "deny"
            connection.execute(
                """INSERT INTO rights_policy_permissions
                   (policy_id, use_kind, decision, reason) VALUES (?, ?, ?, ?)""",
                (policy_id, use_kind, decision, "H3 discovery source is normalization-only"),
            )
        connection.execute(
            "INSERT INTO rights_policy_seals (policy_id, sealed_at) VALUES (?, ?)",
            (policy_id, _now()),
        )
    return policy_id


def _historical_membership_context(
    connection: sqlite3.Connection,
    adaptation: HistoricalGenreMembershipAdaptationResult,
) -> tuple[int, int, int]:
    """Register immutable source metadata for a local-only H3 projection."""
    source = adaptation.source
    policy_id = _seal_local_discovery_policy(connection, source.sha256)
    connection.execute(
        """INSERT OR IGNORE INTO data_sources
           (source_key, name, homepage_url, acquisition_kind, default_policy_id)
           VALUES (?, ?, ?, 'public_download', ?)""",
        (source.source_id, "Every Noise genre artist metadata", str(source.url), policy_id),
    )
    source_id = _source_context(connection, source.source_id)
    manifest_sha256 = hashlib.sha256(source.model_dump_json().encode()).hexdigest()
    snapshot_ref = f"{source.source_id}:{source.snapshot}"
    connection.execute(
        """INSERT OR IGNORE INTO source_snapshots
           (source_id, snapshot_ref, snapshot_kind, upstream_version, manifest_sha256,
            acquired_at, policy_id)
           VALUES (?, ?, 'full', ?, ?, ?, ?)""",
        (source_id, snapshot_ref, source.snapshot, manifest_sha256, _now(), policy_id),
    )
    snapshot_row = connection.execute(
        "SELECT id FROM source_snapshots WHERE snapshot_ref = ?", (snapshot_ref,)
    ).fetchone()
    if snapshot_row is None:
        raise RuntimeError("historical discovery snapshot registration failed")
    connection.execute(
        """INSERT OR IGNORE INTO source_artifacts
           (snapshot_id, artifact_ref, logical_name, media_type, byte_size, sha256,
            vault_key, policy_id)
           VALUES (?, ?, 'genre-artist-map.json', 'application/json', ?, ?, ?, ?)""",
        (
            int(snapshot_row[0]),
            source.sha256,
            source.expected_bytes,
            source.sha256,
            source.sha256,
            policy_id,
        ),
    )
    fingerprint = _fingerprint(source.source_id, source.sha256, "genre-page-member")
    parser_release_ref = "enao_genre_artist_map_v1"
    attempt_ref = f"historical-discovery:{source.sha256}"
    connection.execute(
        """INSERT OR IGNORE INTO provenance_records
           (source_id, policy_id, snapshot_ref, artifact_sha256, record_fingerprint,
            parser_release_ref, ingest_attempt_ref, observed_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            source_id,
            policy_id,
            snapshot_ref,
            source.sha256,
            fingerprint,
            parser_release_ref,
            attempt_ref,
            _now(),
        ),
    )
    provenance_row = connection.execute(
        """SELECT id FROM provenance_records
           WHERE source_id = ? AND snapshot_ref = ? AND record_fingerprint = ?
             AND parser_release_ref = ?""",
        (source_id, snapshot_ref, fingerprint, parser_release_ref),
    ).fetchone()
    if provenance_row is None:
        raise RuntimeError("historical discovery provenance registration failed")
    return source_id, policy_id, int(provenance_row[0])


def _genre_name_contexts(
    connection: sqlite3.Connection,
    source_key: str,
) -> dict[str, int]:
    rows = connection.execute(
        """SELECT lower(genre.name), genre.id
           FROM genres AS genre
           JOIN entity_identifiers AS identifier ON identifier.entity_id = genre.id
           JOIN provenance_records AS provenance ON provenance.id = identifier.provenance_id
           JOIN data_sources AS source ON source.id = provenance.source_id
           WHERE source.source_key = ?""",
        (source_key,),
    ).fetchall()
    return {str(row[0]): int(row[1]) for row in rows}


def _insert_genre_membership(
    connection: sqlite3.Connection,
    *,
    genre_id: int,
    policy_id: int,
    provenance_id: int,
    record: HistoricalGenreMemberRecord,
) -> None:
    fingerprint = _fingerprint(
        record.source_id,
        record.source_sha256,
        record.genre_name.casefold(),
        record.source_artist_id,
        record.source_revision_date,
    )
    connection.execute(
        """INSERT OR IGNORE INTO historical_genre_artist_observations
           (genre_id, source_artist_id, source_artist_name, observation_role,
            source_revision_date, source_artifact_sha256, provenance_id, policy_id,
            record_fingerprint)
           VALUES (?, ?, ?, 'genre_page_member', ?, ?, ?, ?, ?)""",
        (
            genre_id,
            record.source_artist_id,
            record.artist_name,
            record.source_revision_date,
            record.source_sha256,
            provenance_id,
            policy_id,
            fingerprint,
        ),
    )


def _genre_contexts(
    connection: sqlite3.Connection,
    *,
    source_id: int,
) -> dict[str, tuple[int, int, int]]:
    rows = connection.execute(
        """SELECT identifier.normalized_value, identifier.entity_id,
                  provenance.id, provenance.policy_id
           FROM entity_identifiers AS identifier
           JOIN identifier_types AS identifier_type
             ON identifier_type.id = identifier.identifier_type_id
           JOIN provenance_records AS provenance ON provenance.id = identifier.provenance_id
           WHERE provenance.source_id = ?
             AND identifier_type.type_key = 'source_id'""",
        (source_id,),
    ).fetchall()
    return {str(row[0]): (int(row[1]), int(row[2]), int(row[3])) for row in rows}


def _insert_representative(
    connection: sqlite3.Connection,
    *,
    genre_id: int,
    provenance_id: int,
    policy_id: int,
    record: HistoricalRepresentativeRecord,
) -> None:
    artist_fingerprint = _fingerprint(
        record.source_id,
        record.source_sha256,
        record.source_item_id,
        "representative-artist",
        record.artist_name,
        record.source_revision_date,
    )
    connection.execute(
        """INSERT OR IGNORE INTO historical_genre_artist_observations
           (genre_id, source_artist_name, observation_role, source_local_rank,
            source_revision_date, source_artifact_sha256, provenance_id, policy_id,
            record_fingerprint)
           VALUES (?, ?, 'representative', 1, ?, ?, ?, ?, ?)""",
        (
            genre_id,
            record.artist_name,
            record.source_revision_date,
            record.source_sha256,
            provenance_id,
            policy_id,
            artist_fingerprint,
        ),
    )
    artist_row = connection.execute(
        "SELECT id FROM historical_genre_artist_observations WHERE record_fingerprint = ?",
        (artist_fingerprint,),
    ).fetchone()
    if artist_row is None:
        raise RuntimeError("historical representative artist insert failed")
    track_fingerprint = _fingerprint(
        record.source_id,
        record.source_sha256,
        record.source_item_id,
        "representative-track",
        record.recording_provider,
        record.recording_source_id,
        record.artist_name,
        record.track_title,
        record.source_revision_date,
    )
    connection.execute(
        """INSERT OR IGNORE INTO historical_genre_track_observations
           (genre_id, artist_observation_id, source_track_title, recording_provider,
            recording_source_id, safe_external_url, legacy_preview_state,
            legacy_preview_url_sha256, source_revision_date, source_artifact_sha256,
            provenance_id, policy_id, record_fingerprint)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            genre_id,
            int(artist_row[0]),
            record.track_title,
            record.recording_provider,
            record.recording_source_id,
            str(record.safe_external_url),
            "disabled_legacy" if record.legacy_preview_present else "absent",
            record.legacy_preview_url_sha256,
            record.source_revision_date,
            record.source_sha256,
            provenance_id,
            policy_id,
            track_fingerprint,
        ),
    )


def import_historical_representatives(
    database_path: Path,
    adaptation: HistoricalAdaptationResult,
) -> DiscoveryImportSummary:
    """Project verified source observations without creating canonical artist claims."""
    database = Database(database_path)
    database.initialize()
    unmatched = 0
    with database.connect() as connection, connection:
        source_id = _source_context(connection, adaptation.source.source_id)
        contexts = _genre_contexts(connection, source_id=source_id)
        for record in adaptation.records:
            context = contexts.get(record.genre_external_id)
            if context is None:
                unmatched += 1
                continue
            genre_id, provenance_id, policy_id = context
            _insert_representative(
                connection,
                genre_id=genre_id,
                provenance_id=provenance_id,
                policy_id=policy_id,
                record=record,
            )
        artist_count = int(
            connection.execute(
                """SELECT count(*) FROM historical_genre_artist_observations AS observation
                   JOIN provenance_records AS provenance
                     ON provenance.id = observation.provenance_id
                   WHERE provenance.source_id = ?""",
                (source_id,),
            ).fetchone()[0]
        )
        track_count = int(
            connection.execute(
                """SELECT count(*) FROM historical_genre_track_observations AS observation
                   JOIN provenance_records AS provenance
                     ON provenance.id = observation.provenance_id
                   WHERE provenance.source_id = ?""",
                (source_id,),
            ).fetchone()[0]
        )
    return DiscoveryImportSummary(
        representative_artists=artist_count,
        representative_tracks=track_count,
        parser_quarantine=len(adaptation.quarantine),
        unmatched_genres=unmatched,
    )


def import_historical_genre_memberships(
    database_path: Path,
    adaptation: HistoricalGenreMembershipAdaptationResult,
    *,
    base_source_key: str = QUINT_SOURCE.source_id,
) -> GenreMembershipImportSummary:
    """Project local-only H3 evidence onto genres from a sealed base map.

    The source policy permits normalization only. The observations are never
    canonical artist facts and cannot enter a public model or UI publication.
    """
    database = Database(database_path)
    database.initialize()
    source_artists = {record.source_artist_id for record in adaptation.records}
    matched_genres: set[str] = set()
    unmatched_genres: set[str] = set()
    with database.connect() as connection, connection:
        _, policy_id, provenance_id = _historical_membership_context(connection, adaptation)
        contexts = _genre_name_contexts(connection, base_source_key)
        for record in adaptation.records:
            normalized_name = record.genre_name.casefold()
            genre_id = contexts.get(normalized_name)
            if genre_id is None:
                unmatched_genres.add(normalized_name)
                continue
            matched_genres.add(normalized_name)
            _insert_genre_membership(
                connection,
                genre_id=genre_id,
                policy_id=policy_id,
                provenance_id=provenance_id,
                record=record,
            )
        membership_row = connection.execute(
            """SELECT count(*) FROM historical_genre_artist_observations
               WHERE provenance_id = ? AND observation_role = 'genre_page_member'""",
            (provenance_id,),
        ).fetchone()
    if membership_row is None:
        raise RuntimeError("historical genre membership count failed")
    return GenreMembershipImportSummary(
        genre_memberships=int(membership_row[0]),
        distinct_source_artists=len(source_artists),
        matched_genres=len(matched_genres),
        unmatched_genres=len(unmatched_genres),
        discarded_preview_metadata_count=adaptation.discarded_preview_metadata_count,
        discarded_sample_metadata_count=adaptation.discarded_sample_metadata_count,
        discarded_track_identifier_count=adaptation.discarded_track_identifier_count,
        empty_genre_rows=adaptation.empty_genre_rows,
    )
