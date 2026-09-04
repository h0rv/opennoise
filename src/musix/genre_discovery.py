"""Policy-safe persistence for dated genre discovery observations."""

import hashlib
import sqlite3
from dataclasses import dataclass
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

type _MembershipInsertValues = tuple[int, str, str, str, str, int, int, str]

_MEMBERSHIP_INSERT_SQL = """INSERT OR IGNORE INTO historical_genre_artist_observations
    (genre_id, source_artist_id, source_artist_name, observation_role,
     source_revision_date, source_artifact_sha256, provenance_id, policy_id,
     record_fingerprint)
    VALUES (?, ?, ?, 'genre_page_member', ?, ?, ?, ?, ?)"""
_MEMBERSHIP_INSERT_BATCH_SIZE = 4_096


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
    local_display_enabled: bool
    policy_key: str = Field(min_length=1)
    source_membership_count: int = Field(ge=0)
    quarantined_membership_count: int = Field(ge=0)


class DisplayableGenreMembershipSummary(BaseModel):
    """Count only the H3 rows that the active local display policy can query."""

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    genre_memberships: int = Field(ge=0)
    matched_genres: int = Field(ge=0)
    distinct_source_artists: int = Field(ge=0)


class DerivedHistoricalArtistGenres(BaseModel):
    """One queryable reverse lookup, explicitly derived from H3 genre-to-artist rows."""

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    source_artist_id: str = Field(pattern=r"^[A-Za-z0-9]{22}$")
    source_artist_name: str = Field(min_length=1)
    genre_names: tuple[str, ...] = Field(min_length=1, max_length=10_000)
    state: str = "derived_partial"


class HistoricalGenreMember(BaseModel):
    """One direct H3 membership, never a claim that the artist is a representative."""

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    source_artist_id: str = Field(pattern=r"^[A-Za-z0-9]{22}$")
    source_artist_name: str = Field(min_length=1)
    rank: int = Field(gt=0)
    source_local_rank: int | None = Field(default=None, gt=0)
    membership_evidence_count: int = Field(default=1, ge=1, le=1)
    evidence_ref: str = Field(min_length=1, max_length=500)


class HistoricalGenreMembers(BaseModel):
    """A lazily queried and bounded display projection for one historical genre."""

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    genre_id: int = Field(gt=0)
    members: tuple[HistoricalGenreMember, ...] = Field(max_length=100)
    ranking_method: str = "direct_h3_membership_then_source_rank_then_artist"


@dataclass(frozen=True, slots=True)
class _MembershipPersistenceContext:
    """Keep one membership write's database identity and policy inseparable."""

    genre_id: int
    policy_id: int
    provenance_id: int
    policy_key: str


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


def _seal_historical_membership_policy(
    connection: sqlite3.Connection,
    source_sha256: str,
    *,
    enable_local_display: bool,
) -> tuple[int, str]:
    mode = "local-display" if enable_local_display else "discovery-only"
    policy_key = f"historical-membership:{mode}:{source_sha256}"
    basis = (
        "Bounded public metadata research approved for local normalization and display."
        if enable_local_display
        else "Bounded public metadata research approved for local normalization only."
    )
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
            decision = (
                "allow"
                if use_kind == "normalize" or (enable_local_display and use_kind == "display")
                else "deny"
            )
            connection.execute(
                """INSERT INTO rights_policy_permissions
                   (policy_id, use_kind, decision, reason) VALUES (?, ?, ?, ?)""",
                (policy_id, use_kind, decision, f"H3 source project policy is {mode}"),
            )
        connection.execute(
            "INSERT INTO rights_policy_seals (policy_id, sealed_at) VALUES (?, ?)",
            (policy_id, _now()),
        )
    return policy_id, mode


def _historical_membership_context(
    connection: sqlite3.Connection,
    adaptation: HistoricalGenreMembershipAdaptationResult,
    *,
    enable_local_display: bool,
) -> tuple[int, int, int, str]:
    """Register immutable source metadata for a local-only H3 projection."""
    source = adaptation.source
    policy_id, mode = _seal_historical_membership_policy(
        connection,
        source.sha256,
        enable_local_display=enable_local_display,
    )
    source_key = f"{source.source_id}:{mode}"
    connection.execute(
        """INSERT OR IGNORE INTO data_sources
           (source_key, name, homepage_url, acquisition_kind, default_policy_id)
           VALUES (?, ?, ?, 'public_download', ?)""",
        (source_key, "Every Noise genre artist metadata", str(source.url), policy_id),
    )
    source_id = _source_context(connection, source_key)
    manifest_sha256 = hashlib.sha256(source.model_dump_json().encode()).hexdigest()
    snapshot_ref = f"{source_key}:{source.snapshot}"
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
    fingerprint = _fingerprint(source_key, source.sha256, "genre-page-member")
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
    policy_key = f"historical-membership:{mode}:{source.sha256}"
    return source_id, policy_id, int(provenance_row[0]), policy_key


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


def _membership_insert_values(
    *,
    context: _MembershipPersistenceContext,
    record: HistoricalGenreMemberRecord,
) -> _MembershipInsertValues:
    """Prepare one idempotent SQLite row without retaining discarded media fields."""
    fingerprint = _fingerprint(
        context.policy_key,
        record.source_id,
        record.source_sha256,
        record.genre_name.casefold(),
        record.source_artist_id,
        record.source_revision_date,
    )
    return (
        context.genre_id,
        record.source_artist_id,
        record.artist_name,
        record.source_revision_date,
        record.source_sha256,
        context.provenance_id,
        context.policy_id,
        fingerprint,
    )


def _insert_genre_membership_batch(
    connection: sqlite3.Connection,
    rows: list[_MembershipInsertValues],
) -> None:
    """Use bounded batches while retaining one enclosing atomic import transaction."""
    connection.executemany(_MEMBERSHIP_INSERT_SQL, rows)


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
    enable_local_display: bool = False,
) -> GenreMembershipImportSummary:
    """Project local-only H3 evidence onto genres from a sealed base map.

    Discovery-only is the default. Explicit local display permits a private
    SQLite projection, but the observations remain source-scoped, noncanonical,
    and denied export from every public model or UI publication.
    """
    database = Database(database_path)
    database.initialize()
    matched_source_artists: set[str] = set()
    matched_genres: set[str] = set()
    unmatched_genres: set[str] = set()
    with database.connect() as connection, connection:
        _, policy_id, provenance_id, policy_key = _historical_membership_context(
            connection,
            adaptation,
            enable_local_display=enable_local_display,
        )
        contexts = _genre_name_contexts(connection, base_source_key)
        matched_records: list[tuple[int, HistoricalGenreMemberRecord]] = []
        for record in adaptation.records:
            normalized_name = record.genre_name.casefold()
            genre_id = contexts.get(normalized_name)
            if genre_id is None:
                unmatched_genres.add(normalized_name)
                continue
            matched_genres.add(normalized_name)
            matched_source_artists.add(record.source_artist_id)
            matched_records.append((genre_id, record))
        existing_membership_row = connection.execute(
            """SELECT count(*) FROM historical_genre_artist_observations
               WHERE provenance_id = ? AND observation_role = 'genre_page_member'""",
            (provenance_id,),
        ).fetchone()
        if existing_membership_row is None:
            raise RuntimeError("historical genre membership count failed")
        existing_memberships = int(existing_membership_row[0])
        if existing_memberships != len(matched_records):
            pending_rows: list[_MembershipInsertValues] = []
            for genre_id, record in matched_records:
                pending_rows.append(
                    _membership_insert_values(
                        context=_MembershipPersistenceContext(
                            genre_id=genre_id,
                            policy_id=policy_id,
                            provenance_id=provenance_id,
                            policy_key=policy_key,
                        ),
                        record=record,
                    )
                )
                if len(pending_rows) == _MEMBERSHIP_INSERT_BATCH_SIZE:
                    _insert_genre_membership_batch(connection, pending_rows)
                    pending_rows.clear()
            if pending_rows:
                _insert_genre_membership_batch(connection, pending_rows)
        membership_row = connection.execute(
            """SELECT count(*) FROM historical_genre_artist_observations
               WHERE provenance_id = ? AND observation_role = 'genre_page_member'""",
            (provenance_id,),
        ).fetchone()
    if membership_row is None:
        raise RuntimeError("historical genre membership count failed")
    return GenreMembershipImportSummary(
        genre_memberships=int(membership_row[0]),
        distinct_source_artists=len(matched_source_artists),
        matched_genres=len(matched_genres),
        unmatched_genres=len(unmatched_genres),
        discarded_preview_metadata_count=adaptation.discarded_preview_metadata_count,
        discarded_sample_metadata_count=adaptation.discarded_sample_metadata_count,
        discarded_track_identifier_count=adaptation.discarded_track_identifier_count,
        empty_genre_rows=adaptation.empty_genre_rows,
        local_display_enabled=enable_local_display,
        policy_key=policy_key,
        source_membership_count=adaptation.source_membership_count,
        quarantined_membership_count=adaptation.quarantined_membership_count,
    )


def query_displayable_historical_genre_memberships(
    database_path: Path,
    *,
    source_sha256: str,
    policy_key: str,
) -> DisplayableGenreMembershipSummary:
    """Read only H3 rows that remain visible through the active local display policy."""
    database = Database(database_path)
    database.initialize()
    with database.connect() as connection:
        connection.execute("PRAGMA optimize")
        row = connection.execute(
            """SELECT count(*), count(DISTINCT observation.genre_id),
                      count(DISTINCT observation.source_artist_id)
               FROM displayable_historical_genre_artists AS observation
               JOIN rights_policies AS policy ON policy.id = observation.policy_id
               WHERE observation.observation_role = 'genre_page_member'
                 AND observation.source_artifact_sha256 = ?
                 AND policy.policy_key = ?""",
            (source_sha256, policy_key),
        ).fetchone()
    if row is None:
        raise RuntimeError("displayable historical membership count failed")
    return DisplayableGenreMembershipSummary(
        genre_memberships=int(row[0]),
        matched_genres=int(row[1]),
        distinct_source_artists=int(row[2]),
    )


def query_displayable_historical_artist_genres(
    database_path: Path,
    *,
    source_sha256: str,
    policy_key: str,
    source_artist_id: str,
) -> DerivedHistoricalArtistGenres | None:
    """Reverse visible H3 rows for one artist without claiming an observed artist page."""
    database = Database(database_path)
    database.initialize()
    with database.connect() as connection:
        rows = connection.execute(
            """SELECT observation.source_artist_name, genre.name
               FROM displayable_historical_genre_artists AS observation
               JOIN rights_policies AS policy ON policy.id = observation.policy_id
               JOIN genres AS genre ON genre.id = observation.genre_id
               WHERE observation.observation_role = 'genre_page_member'
                 AND observation.source_artifact_sha256 = ?
                 AND policy.policy_key = ?
                 AND observation.source_artist_id = ?
               ORDER BY genre.name""",
            (source_sha256, policy_key, source_artist_id),
        ).fetchall()
    if not rows:
        return None
    return DerivedHistoricalArtistGenres(
        source_artist_id=source_artist_id,
        source_artist_name=str(rows[0][0]),
        genre_names=tuple(str(row[1]) for row in rows),
    )


def query_displayable_historical_genre_members(
    database_path: Path,
    *,
    source_sha256: str,
    policy_key: str,
    genre_id: int,
    limit: int = 6,
) -> HistoricalGenreMembers:
    """Lazily read direct H3 members without placing them in a map payload.

    H3 retains one membership observation per artist and does not retain a
    source popularity score.  A nullable source-local rank is honored when a
    future source supplies it; otherwise this is only a stable display order,
    not a popularity or representative claim.
    """
    bounded_limit = min(max(limit, 1), 100)
    database = Database(database_path)
    database.initialize()
    with database.connect() as connection:
        rows = connection.execute(
            """SELECT observation.id, observation.source_artist_id,
                      observation.source_artist_name, observation.source_local_rank
               FROM displayable_historical_genre_artists AS observation
               JOIN rights_policies AS policy ON policy.id = observation.policy_id
               WHERE observation.observation_role = 'genre_page_member'
                 AND observation.source_artifact_sha256 = ?
                 AND policy.policy_key = ?
                 AND observation.genre_id = ?
               ORDER BY observation.source_local_rank IS NULL,
                        observation.source_local_rank,
                        observation.source_artist_name COLLATE NOCASE,
                        observation.source_artist_id,
                        observation.id
               LIMIT ?""",
            (source_sha256, policy_key, genre_id, bounded_limit),
        ).fetchall()
    return HistoricalGenreMembers(
        genre_id=genre_id,
        members=tuple(
            HistoricalGenreMember(
                source_artist_id=str(row[1]),
                source_artist_name=str(row[2]),
                rank=rank,
                source_local_rank=None if row[3] is None else int(row[3]),
                evidence_ref=f"historical:genre-artist:{int(row[0])}",
            )
            for rank, row in enumerate(rows, start=1)
        ),
    )
