"""Compare a bounded Phase 3 replay candidate with a sealed SQLite database.

The comparator opens both inputs with SQLite's immutable read-only URI mode.  It
never attaches, copies, writes, or otherwise uses the sealed database as a
construction input.  Content fingerprints stream deterministic, ordered rows
instead of materializing tables in memory.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Final, Literal, Protocol
from urllib.parse import quote

if TYPE_CHECKING:
    from pathlib import Path

_MAX_ROWS_PER_TABLE: Final = 50_000
_DERIVED_TABLE_PREFIXES: Final = ("current_", "layout_", "public_")
_DERIVED_TABLES: Final = frozenset({"derivation_edges", "derived_output_events", "derived_outputs"})
_CORE_TABLES: Final = frozenset(
    {
        "album_genre_membership_observations",
        "artist_co_listen_evidence",
        "artist_co_listen_runs",
        "artist_genre_evidence",
        "data_sources",
        "genre_music_qualification_observations",
        "recording_genre_membership_observations",
        "source_artifacts",
        "source_object_observations",
        "source_objects",
        "source_snapshots",
        "staged_records",
    }
)
_SOURCE_PROJECTIONS: Final = (
    (
        "source_artifact_identities",
        "source",
        """SELECT source.source_key, artifact.sha256
             FROM data_sources AS source JOIN source_snapshots AS snapshot
               ON snapshot.source_id = source.id JOIN source_artifacts AS artifact
               ON artifact.snapshot_id = snapshot.id
             ORDER BY source.source_key, artifact.sha256""",
    ),
    (
        "source_snapshot_declarations",
        "source",
        """SELECT source.source_key, snapshot.snapshot_ref, snapshot.manifest_sha256
             FROM data_sources AS source JOIN source_snapshots AS snapshot
               ON snapshot.source_id = source.id
             ORDER BY source.source_key, snapshot.snapshot_ref, snapshot.manifest_sha256""",
    ),
    (
        "staged_raw_records",
        "source",
        """SELECT artifact.sha256, record.record_ordinal, coalesce(record.byte_offset, -1),
                  coalesce(record.byte_length, -1), record.exact_record_sha256,
                  coalesce(record.canonical_json_sha256, ''), record.parse_status
             FROM staged_records AS record JOIN source_artifacts AS artifact
               ON artifact.id = record.artifact_id
             ORDER BY artifact.sha256, record.record_ordinal, coalesce(record.byte_offset, -1),
                      coalesce(record.byte_length, -1), record.exact_record_sha256,
                      coalesce(record.canonical_json_sha256, ''), record.parse_status""",
    ),
    (
        "source_object_identities",
        "source",
        """SELECT source.source_key, object.record_kind, object.namespace, object.scope_key,
                  object.external_id
             FROM source_objects AS object JOIN data_sources AS source
               ON source.id = object.source_id
             ORDER BY source.source_key, object.record_kind, object.namespace, object.scope_key,
                      object.external_id""",
    ),
    (
        "source_object_observation_fingerprints",
        "source",
        "SELECT observation_fingerprint FROM source_object_observations ORDER BY 1",
    ),
    (
        "artist_genre_evidence_fingerprints",
        "evidence",
        "SELECT record_fingerprint FROM artist_genre_evidence ORDER BY 1",
    ),
    (
        "artist_colisten_windows",
        "evidence",
        """SELECT left_artist_source_id, right_artist_source_id, window_start, window_end,
                  distinct_user_count FROM artist_co_listen_evidence
             ORDER BY left_artist_source_id, right_artist_source_id, window_start, window_end,
                      distinct_user_count""",
    ),
    (
        "album_genre_observed_values",
        "evidence",
        """SELECT source_record_id, source_genre_name, evidence_kind, evidence_level,
                  coalesce(source_count, -1), coalesce(source_total, -1), method_key, method_version
             FROM album_genre_membership_observations
             ORDER BY source_record_id, source_genre_name, evidence_kind, evidence_level,
                      coalesce(source_count, -1), coalesce(source_total, -1), method_key,
                      method_version""",
    ),
    (
        "recording_genre_observed_values",
        "evidence",
        """SELECT source_record_id, source_genre_name, evidence_kind, coalesce(source_count, -1),
                  method_key, method_version FROM recording_genre_membership_observations
             ORDER BY source_record_id, source_genre_name, evidence_kind,
                      coalesce(source_count, -1), method_key, method_version""",
    ),
    (
        "genre_qualification_observed_values",
        "evidence",
        """SELECT root_qid, path_depth, path_spec, exclusion_profile, statement_id, statement_rank
             FROM genre_music_qualification_observations
             ORDER BY root_qid, path_depth, path_spec, exclusion_profile, statement_id,
                      statement_rank""",
    ),
)


class Phase3ReplayComparisonError(ValueError):
    """Report an invalid or unsafe Phase 3 replay comparison request."""


class _Digest(Protocol):
    """The small hashlib surface used by streamed SQLite serialization."""

    def update(self, data: bytes, /) -> None:
        """Add bytes to the digest."""


@dataclass(frozen=True, slots=True)
class TableComparison:
    """One table's deterministic, streamed comparison result."""

    table_name: str
    classification: Literal["core", "derived", "auxiliary"]
    candidate_rows: int
    sealed_rows: int
    candidate_sha256: str
    sealed_sha256: str
    candidate_without_acquired_at_sha256: str
    sealed_without_acquired_at_sha256: str

    @property
    def exact_content_equal(self) -> bool:
        """Whether every persisted cell in the table is identical."""
        return (
            self.candidate_rows == self.sealed_rows and self.candidate_sha256 == self.sealed_sha256
        )

    @property
    def content_equal_without_acquired_at(self) -> bool:
        """Whether content is equal after only excluding acquisition timestamps."""
        return (
            self.candidate_rows == self.sealed_rows
            and self.candidate_without_acquired_at_sha256 == self.sealed_without_acquired_at_sha256
        )


@dataclass(frozen=True, slots=True)
class Phase3ReplayComparison:
    """Hash-bound, read-only comparison evidence for two SQLite files."""

    candidate_path: str
    candidate_sha256: str
    sealed_path: str
    sealed_sha256: str
    candidate_user_version: int
    sealed_user_version: int
    candidate_integrity_check: str
    sealed_integrity_check: str
    candidate_foreign_key_violations: int
    sealed_foreign_key_violations: int
    schema_sha256: str
    schema_equal: bool
    byte_identical: bool
    max_rows_per_table: int
    tables: tuple[TableComparison, ...]
    source_projections: tuple[SemanticProjection, ...]

    def to_json(self) -> str:
        """Serialize a deterministic report suitable for a local evidence file."""
        payload = asdict(self)
        payload["tables"] = [
            {
                **asdict(table),
                "exact_content_equal": table.exact_content_equal,
                "content_equal_without_acquired_at": table.content_equal_without_acquired_at,
            }
            for table in self.tables
        ]
        payload["source_projections"] = [
            {**asdict(projection), "equal": projection.equal}
            for projection in self.source_projections
        ]
        return json.dumps(payload, indent=2, sort_keys=True) + "\n"


@dataclass(frozen=True, slots=True)
class SemanticProjection:
    """A bounded logical source or evidence identity projection."""

    name: str
    classification: Literal["source", "evidence"]
    candidate_rows: int
    sealed_rows: int
    candidate_sha256: str
    sealed_sha256: str

    @property
    def equal(self) -> bool:
        """Whether the two logical projections agree exactly."""
        return (
            self.candidate_rows == self.sealed_rows and self.candidate_sha256 == self.sealed_sha256
        )


def compare_phase3_replay_databases(
    candidate: Path,
    sealed: Path,
    *,
    expected_candidate_sha256: str,
    expected_sealed_sha256: str,
    max_rows_per_table: int = _MAX_ROWS_PER_TABLE,
) -> Phase3ReplayComparison:
    """Return bounded comparison evidence after verifying both file hashes.

    ``max_rows_per_table`` is a deliberate boundary: a larger database must be
    partitioned into another explicit comparator rather than silently consuming
    unbounded resources.
    """
    if max_rows_per_table < 1:
        raise Phase3ReplayComparisonError("max_rows_per_table must be positive")
    candidate_hash = _sha256(candidate)
    sealed_hash = _sha256(sealed)
    _require_hash(candidate, candidate_hash, expected_candidate_sha256)
    _require_hash(sealed, sealed_hash, expected_sealed_sha256)
    with (
        closing(_readonly_connection(candidate)) as candidate_db,
        closing(_readonly_connection(sealed)) as sealed_db,
    ):
        candidate_schema = _schema_rows(candidate_db)
        sealed_schema = _schema_rows(sealed_db)
        candidate_tables = _table_names(candidate_db)
        sealed_tables = _table_names(sealed_db)
        if candidate_tables != sealed_tables:
            raise Phase3ReplayComparisonError("databases do not contain the same tables")
        comparisons = tuple(
            _compare_table(candidate_db, sealed_db, table, max_rows_per_table)
            for table in candidate_tables
        )
        source_projections = tuple(
            _compare_projection(candidate_db, sealed_db, projection, max_rows_per_table)
            for projection in _SOURCE_PROJECTIONS
        )
        candidate_integrity, candidate_foreign_keys, candidate_version = _database_health(
            candidate_db
        )
        sealed_integrity, sealed_foreign_keys, sealed_version = _database_health(sealed_db)
    candidate_schema_hash = _rows_sha256(candidate_schema)
    sealed_schema_hash = _rows_sha256(sealed_schema)
    return Phase3ReplayComparison(
        candidate_path=str(candidate),
        candidate_sha256=candidate_hash,
        sealed_path=str(sealed),
        sealed_sha256=sealed_hash,
        candidate_user_version=candidate_version,
        sealed_user_version=sealed_version,
        candidate_integrity_check=candidate_integrity,
        sealed_integrity_check=sealed_integrity,
        candidate_foreign_key_violations=candidate_foreign_keys,
        sealed_foreign_key_violations=sealed_foreign_keys,
        schema_sha256=candidate_schema_hash,
        schema_equal=candidate_schema_hash == sealed_schema_hash,
        byte_identical=candidate_hash == sealed_hash,
        max_rows_per_table=max_rows_per_table,
        tables=comparisons,
        source_projections=source_projections,
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _require_hash(path: Path, actual: str, expected: str) -> None:
    if actual != expected:
        raise Phase3ReplayComparisonError(f"SHA-256 mismatch for {path}")


def _readonly_connection(path: Path) -> sqlite3.Connection:
    uri = f"file:{quote(str(path.resolve()))}?mode=ro&immutable=1"
    connection = sqlite3.connect(uri, uri=True)
    connection.execute("PRAGMA query_only = ON")
    return connection


def _schema_rows(connection: sqlite3.Connection) -> tuple[tuple[str, ...], ...]:
    return tuple(
        tuple(str(value) for value in row)
        for row in connection.execute(
            """SELECT type, name, tbl_name, coalesce(sql, '') FROM sqlite_master
               WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name"""
        )
    )


def _table_names(connection: sqlite3.Connection) -> tuple[str, ...]:
    return tuple(
        str(row[0])
        for row in connection.execute(
            """SELECT name FROM sqlite_master
               WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"""
        )
    )


def _compare_table(
    candidate: sqlite3.Connection,
    sealed: sqlite3.Connection,
    table: str,
    max_rows: int,
) -> TableComparison:
    columns = _table_columns(candidate, table)
    sealed_columns = _table_columns(sealed, table)
    if columns != sealed_columns:
        raise Phase3ReplayComparisonError(f"table columns differ for {table}")
    candidate_rows = _bounded_row_count(candidate, table, max_rows)
    sealed_rows = _bounded_row_count(sealed, table, max_rows)
    content_columns = tuple(column for column in columns if column != "acquired_at")
    candidate_hash = _table_sha256(candidate, table, columns)
    sealed_hash = _table_sha256(sealed, table, columns)
    candidate_content_hash = (
        _table_sha256(candidate, table, content_columns)
        if content_columns != columns
        else candidate_hash
    )
    sealed_content_hash = (
        _table_sha256(sealed, table, content_columns) if content_columns != columns else sealed_hash
    )
    return TableComparison(
        table_name=table,
        classification=_table_classification(table),
        candidate_rows=candidate_rows,
        sealed_rows=sealed_rows,
        candidate_sha256=candidate_hash,
        sealed_sha256=sealed_hash,
        candidate_without_acquired_at_sha256=candidate_content_hash,
        sealed_without_acquired_at_sha256=sealed_content_hash,
    )


def _compare_projection(
    candidate: sqlite3.Connection,
    sealed: sqlite3.Connection,
    definition: tuple[str, Literal["source", "evidence"], str],
    maximum: int,
) -> SemanticProjection:
    name, classification, query = definition
    candidate_rows = _bounded_query_row_count(candidate, name, query, maximum)
    sealed_rows = _bounded_query_row_count(sealed, name, query, maximum)
    return SemanticProjection(
        name=name,
        classification=classification,
        candidate_rows=candidate_rows,
        sealed_rows=sealed_rows,
        candidate_sha256=_rows_sha256(candidate.execute(query)),
        sealed_sha256=_rows_sha256(sealed.execute(query)),
    )


def _bounded_query_row_count(
    connection: sqlite3.Connection, name: str, query: str, maximum: int
) -> int:
    rows = connection.execute(query)
    count = sum(1 for _ in range(maximum + 1) if rows.fetchone() is not None)
    if count == maximum + 1:
        raise Phase3ReplayComparisonError(f"projection {name} exceeds bounded limit {maximum}")
    return count


def _table_classification(table: str) -> Literal["core", "derived", "auxiliary"]:
    if table in _CORE_TABLES:
        return "core"
    if table in _DERIVED_TABLES or table.startswith(_DERIVED_TABLE_PREFIXES):
        return "derived"
    return "auxiliary"


def _table_columns(connection: sqlite3.Connection, table: str) -> tuple[str, ...]:
    quoted = _quote_identifier(table)
    return tuple(str(row[1]) for row in connection.execute(f"PRAGMA table_info({quoted})"))


def _bounded_row_count(connection: sqlite3.Connection, table: str, maximum: int) -> int:
    quoted = _quote_identifier(table)
    count = int(connection.execute(f"SELECT count(*) FROM {quoted}").fetchone()[0])  # noqa: S608
    if count > maximum:
        raise Phase3ReplayComparisonError(
            f"table {table} has {count} rows, exceeding bounded limit {maximum}"
        )
    return count


def _table_sha256(connection: sqlite3.Connection, table: str, columns: tuple[str, ...]) -> str:
    quoted_table = _quote_identifier(table)
    if not columns:
        return _rows_sha256(())
    projection = ", ".join(_quote_identifier(column) for column in columns)
    order = ", ".join(_quote_identifier(column) for column in columns)
    query = f"SELECT {projection} FROM {quoted_table} ORDER BY {order}"  # noqa: S608
    return _rows_sha256(connection.execute(query))


def _rows_sha256(rows: sqlite3.Cursor | tuple[tuple[str, ...], ...]) -> str:
    digest = hashlib.sha256()
    for row in rows:
        for value in row:
            _update_value(digest, value)
        digest.update(b"\x1e")
    return digest.hexdigest()


def _update_value(digest: _Digest, value: object) -> None:
    if value is None:
        payload = b"n"
    elif isinstance(value, bytes):
        payload = b"b" + value
    elif isinstance(value, str):
        payload = b"s" + value.encode("utf-8")
    elif isinstance(value, int):
        payload = b"i" + str(value).encode("ascii")
    elif isinstance(value, float):
        payload = b"f" + value.hex().encode("ascii")
    else:
        raise Phase3ReplayComparisonError(f"unsupported SQLite value type {type(value).__name__}")
    digest.update(len(payload).to_bytes(8, "big"))
    digest.update(payload)


def _database_health(connection: sqlite3.Connection) -> tuple[str, int, int]:
    integrity = connection.execute("PRAGMA integrity_check").fetchone()
    version = connection.execute("PRAGMA user_version").fetchone()
    if integrity is None or version is None:
        raise Phase3ReplayComparisonError("SQLite health query returned no result")
    return (
        str(integrity[0]),
        len(tuple(connection.execute("PRAGMA foreign_key_check"))),
        int(version[0]),
    )


def _quote_identifier(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'
