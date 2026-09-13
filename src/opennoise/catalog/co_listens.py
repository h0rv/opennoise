"""Direct-SQL repository for aggregate ListenBrainz co-listen evidence."""

import hashlib
import sqlite3

from opennoise.models.catalog import (
    ArtistCoListenProjection,
    ArtistCoListenRunProjection,
    CatalogProjection,
    ProjectionResult,
)


def _hash_parts(*parts: str) -> str:
    digest = hashlib.sha256()
    for part in parts:
        digest.update(part.encode())
        digest.update(b"\0")
    return digest.hexdigest()


def _lastrowid(cursor: sqlite3.Cursor) -> int:
    row_id = cursor.lastrowid
    if row_id is None:
        raise RuntimeError("SQLite insert returned no row ID")
    return row_id


def _record_context(
    connection: sqlite3.Connection,
    provenance_id: int,
) -> tuple[int, int, int, str]:
    row = connection.execute(
        """SELECT record.id, record.ingest_attempt_id, record.artifact_id,
                  attempt.attempt_ref
           FROM provenance_records AS provenance
           JOIN ingest_attempts AS attempt
             ON attempt.attempt_ref = provenance.ingest_attempt_ref
           JOIN staged_records AS record
             ON record.ingest_attempt_id = attempt.id
            AND record.record_fingerprint = provenance.record_fingerprint
           WHERE provenance.id = ?""",
        (provenance_id,),
    ).fetchone()
    if row is None:
        raise RuntimeError("co-listen projection has no matching staged record")
    return int(row[0]), int(row[1]), int(row[2]), str(row[3])


def _require_normalize_policy(connection: sqlite3.Connection, policy_id: int) -> None:
    allowed = connection.execute(
        """SELECT 1 FROM active_rights_policy_permissions
           WHERE policy_id = ? AND use_kind = 'normalize' AND decision = 'allow'""",
        (policy_id,),
    ).fetchone()
    if allowed is None:
        raise PermissionError("co-listen projection requires normalization permission")


class ArtistCoListenProjector:
    """Persist privacy-thresholded pairs and their complete coverage record."""

    @property
    def key(self) -> str:
        """Return the accepted evidence projection discriminant."""
        return "artist_co_listen"

    def persist(
        self,
        connection: sqlite3.Connection,
        projection: CatalogProjection,
        *,
        provenance_id: int,
        policy_id: int,
    ) -> ProjectionResult:
        """Persist one aggregate pair without choosing a similarity function."""
        if not isinstance(projection, ArtistCoListenProjection):
            raise TypeError("artist co-listen projector received the wrong projection")
        _require_normalize_policy(connection, policy_id)
        staged_id, attempt_id, _artifact_id, _attempt_ref = _record_context(
            connection, provenance_id
        )
        fingerprint = _hash_parts(
            str(attempt_id),
            projection.left_artist_source_id,
            projection.right_artist_source_id,
            str(projection.window_start),
            str(projection.distinct_user_count),
        )
        existing = connection.execute(
            "SELECT id FROM artist_co_listen_evidence WHERE evidence_fingerprint = ?",
            (fingerprint,),
        ).fetchone()
        if existing is not None:
            return ProjectionResult(
                projection_kind=self.key,
                target_id=int(existing[0]),
                duplicate=True,
            )
        cursor = connection.execute(
            """INSERT INTO artist_co_listen_evidence
               (ingest_attempt_id, staged_record_id, left_artist_source_id,
                right_artist_source_id, window_start, window_end,
                distinct_user_count, evidence_fingerprint)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                attempt_id,
                staged_id,
                projection.left_artist_source_id,
                projection.right_artist_source_id,
                projection.window_start,
                projection.window_end,
                projection.distinct_user_count,
                fingerprint,
            ),
        )
        return ProjectionResult(
            projection_kind=self.key,
            target_id=_lastrowid(cursor),
            duplicate=False,
        )


class ArtistCoListenRunProjector:
    """Persist aggregate coverage only after the adapter consumed the artifact."""

    @property
    def key(self) -> str:
        """Return the accepted run projection discriminant."""
        return "artist_co_listen_run"

    def persist(
        self,
        connection: sqlite3.Connection,
        projection: CatalogProjection,
        *,
        provenance_id: int,
        policy_id: int,
    ) -> ProjectionResult:
        """Seal one complete, source-qualified co-listen aggregation run."""
        if not isinstance(projection, ArtistCoListenRunProjection):
            raise TypeError("artist co-listen run projector received the wrong projection")
        _require_normalize_policy(connection, policy_id)
        _staged_id, attempt_id, artifact_id, attempt_ref = _record_context(
            connection, provenance_id
        )
        run_ref = f"co-listen:{attempt_ref}"
        existing = connection.execute(
            "SELECT id FROM artist_co_listen_runs WHERE run_ref = ?",
            (run_ref,),
        ).fetchone()
        if existing is not None:
            return ProjectionResult(
                projection_kind=self.key,
                target_id=int(existing[0]),
                duplicate=True,
            )
        cursor = connection.execute(
            """INSERT INTO artist_co_listen_runs
               (run_ref, ingest_attempt_id, artifact_id, adapter_key, adapter_version,
                adapter_build_sha256, aggregation_version, configuration_sha256,
                window_seconds, minimum_distinct_users, listens_seen,
                listens_with_artist_mbid, distinct_artists, user_windows,
                candidate_pairs, emitted_pairs, quarantined_records,
                minimum_listened_at, maximum_listened_at, elapsed_ms, peak_rss_bytes,
                completed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                       strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))""",
            (
                run_ref,
                attempt_id,
                artifact_id,
                projection.adapter_key,
                projection.adapter_version,
                projection.adapter_build_sha256,
                projection.aggregation_version,
                projection.configuration_sha256,
                projection.window_seconds,
                projection.minimum_distinct_users,
                projection.listens_seen,
                projection.listens_with_artist_mbid,
                projection.distinct_artists,
                projection.user_windows,
                projection.candidate_pairs,
                projection.emitted_pairs,
                projection.quarantined_records,
                projection.minimum_listened_at,
                projection.maximum_listened_at,
                projection.elapsed_ms,
                projection.peak_rss_bytes,
            ),
        )
        return ProjectionResult(
            projection_kind=self.key,
            target_id=_lastrowid(cursor),
            duplicate=False,
        )
