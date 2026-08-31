"""Policy-safe persistence for dated genre discovery observations."""

import hashlib
import sqlite3
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from musix.adapters.everynoise import (
    HistoricalAdaptationResult,
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
