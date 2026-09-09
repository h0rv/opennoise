"""Bounded, idempotent ingestion of user supplied local JSONL metadata."""

import asyncio
import hashlib
import json
import os
import sqlite3
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import BinaryIO, NamedTuple

from pydantic import BaseModel, ConfigDict, model_validator

from musix.db import Database

PIPELINE_VERSION = "musix-jsonl-v1"
PARSER_KEY = "musix-project-jsonl"
PARSER_VERSION = "1"
USE_KINDS = ("normalize", "local_search", "display", "embed", "train", "export")
LOCAL_ALLOWED_USES = frozenset({"normalize", "local_search", "display", "embed", "train"})


class RecordParseError(ValueError):
    """Report a record that cannot be parsed into a catalog type."""


class _FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True)


class Limits(_FrozenModel):
    """Bound memory, input volume, nesting, and execution time."""

    max_artifact_bytes: int = 64 * 1024 * 1024
    max_record_bytes: int = 1024 * 1024
    max_records: int = 100_000
    max_nesting_depth: int = 64
    timeout_seconds: float = 300.0

    @model_validator(mode="after")
    def positive_limits(self) -> "Limits":
        """Reject nonpositive safety limits at construction."""
        values = (
            self.max_artifact_bytes,
            self.max_record_bytes,
            self.max_records,
            self.max_nesting_depth,
        )
        if any(value <= 0 for value in values) or self.timeout_seconds <= 0:
            raise ValueError("ingest limits must be positive")
        return self


class Identifier(_FrozenModel):
    """A typed external identifier from one namespace."""

    type_key: str
    namespace: str
    value: str


class CatalogRecord(_FrozenModel):
    """A parsed artist or genre record."""

    kind: str
    external_id: str
    name: str
    slug: str | None
    aliases: tuple[str, ...]
    identifiers: tuple[Identifier, ...]


class ImportOptions(_FrozenModel):
    """Paths, source identity, and limits for one local import."""

    input_path: Path
    database_path: Path
    vault_path: Path
    source_key: str
    source_name: str
    limits: Limits = Limits()

    @model_validator(mode="after")
    def source_identity(self) -> "ImportOptions":
        """Reject missing source identity at construction."""
        if not self.source_key.strip() or not self.source_name.strip():
            raise ValueError("source key and source name are required")
        return self


class ImportSummary(_FrozenModel):
    """Stable counters and identity for one import attempt."""

    artifact_sha256: str
    attempt_ref: str
    accepted: int
    quarantined: int
    catalog_entities: int
    reused_attempt: bool


class _BoundedLine(_FrozenModel):
    captured: bytes
    byte_length: int
    consumed: int
    sha256: str
    oversized: bool


class _NormalizeContext(NamedTuple):
    source_id: int
    policy_id: int
    artifact_sha256: str
    attempt_ref: str
    staged_record_id: int
    observation_id: int
    record_fingerprint: str
    parser_ref: str


class _ImportContext(NamedTuple):
    source_id: int
    policy_id: int
    artifact_id: int
    artifact_sha256: str
    attempt_ref: str
    attempt_id: int
    started: float
    parser_ref: str


class _RecordContext(NamedTuple):
    line: _BoundedLine
    ordinal: int
    byte_offset: int
    fingerprint: str


class _DecodedRecord(NamedTuple):
    record: CatalogRecord
    canonical: str
    canonical_sha: str


def _required_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RecordParseError(f"{field} must be a nonempty string")
    return value


def _optional_strings(value: object, field: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise RecordParseError(f"{field} must be an array")
    return tuple(_required_string(item, f"{field} entry") for item in value)


def parse_catalog_record(value: object) -> CatalogRecord:
    """Parse one decoded JSON value into a catalog record."""
    if not isinstance(value, dict):
        raise RecordParseError("a record must be a JSON object")
    kind_value = value.get("type", value.get("record_kind"))
    kind = _required_string(kind_value, "type")
    if kind not in {"artist", "genre"}:
        raise RecordParseError("type must be artist or genre")
    external_id = _required_string(value.get("external_id"), "external_id")
    name = _required_string(value.get("name"), "name")
    slug = _required_string(value.get("slug"), "slug") if kind == "genre" else None
    aliases = _optional_strings(value.get("aliases"), "aliases")
    raw_identifiers = value.get("identifiers")
    identifiers: list[Identifier] = []
    if raw_identifiers is not None:
        if not isinstance(raw_identifiers, list):
            raise RecordParseError("identifiers must be an array")
        for raw_identifier in raw_identifiers:
            if not isinstance(raw_identifier, dict):
                raise RecordParseError("identifier entries must be objects")
            namespace_value = raw_identifier.get("namespace", "")
            if not isinstance(namespace_value, str):
                raise RecordParseError("identifier.namespace must be a string")
            identifiers.append(
                Identifier(
                    type_key=_required_string(raw_identifier.get("type"), "identifier.type"),
                    namespace=namespace_value,
                    value=_required_string(raw_identifier.get("value"), "identifier.value"),
                )
            )
    return CatalogRecord(
        kind=kind,
        external_id=external_id,
        name=name,
        slug=slug,
        aliases=aliases,
        identifiers=tuple(identifiers),
    )


def _json_depth(value: object) -> int:
    maximum = 1
    pending: list[tuple[object, int]] = [(value, 1)]
    while pending:
        item, depth = pending.pop()
        maximum = max(maximum, depth)
        if isinstance(item, dict):
            pending.extend((child, depth + 1) for child in item.values())
        elif isinstance(item, list):
            pending.extend((child, depth + 1) for child in item)
    return maximum


def _read_bounded_line(stream: BinaryIO, maximum: int) -> _BoundedLine | None:
    first = stream.readline(maximum + 2)
    if not first:
        return None
    captured = bytearray(first[:maximum])
    digest = hashlib.sha256()
    byte_length = 0
    consumed = 0
    chunk = first
    while True:
        has_newline = chunk.endswith(b"\n")
        record_chunk = chunk[:-1] if has_newline else chunk
        digest.update(record_chunk)
        byte_length += len(record_chunk)
        consumed += len(chunk)
        if has_newline or len(chunk) <= maximum + 1:
            break
        chunk = stream.readline(64 * 1024)
        if not chunk:
            break
    return _BoundedLine(
        captured=bytes(captured),
        byte_length=byte_length,
        consumed=consumed,
        sha256=digest.hexdigest(),
        oversized=byte_length > maximum,
    )


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _hash_parts(*parts: str) -> str:
    digest = hashlib.sha256()
    for part in parts:
        digest.update(part.encode())
        digest.update(b"\0")
    return digest.hexdigest()


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(64 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _lastrowid(cursor: sqlite3.Cursor) -> int:
    row_id = cursor.lastrowid
    if row_id is None:
        raise RuntimeError("SQLite insert returned no row ID")
    return row_id


def _store_in_vault(input_path: Path, vault_path: Path, sha256: str) -> None:
    vault_path.mkdir(parents=True, exist_ok=True)
    destination = vault_path / sha256
    if destination.exists():
        if _hash_file(destination) != sha256:
            raise RuntimeError(f"vault object failed its hash check: {destination}")
        return
    temporary = vault_path / f".{sha256}.{os.getpid()}.tmp"
    try:
        with input_path.open("rb") as source, temporary.open("xb") as target:
            while chunk := source.read(64 * 1024):
                target.write(chunk)
        if _hash_file(temporary) != sha256:
            raise RuntimeError("vault copy failed its hash check")
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)


def _register_policy(connection: sqlite3.Connection) -> int:
    key = "user-authorized-local"
    basis = "The user supplied this data for local use. Redistribution is not allowed."
    connection.execute(
        """INSERT OR IGNORE INTO rights_policies
           (policy_key, policy_version, classification, local_only, basis, reviewed_at)
           VALUES (?, 1, 'user_authorized_local', 1, ?, ?)""",
        (key, basis, _now()),
    )
    row = connection.execute(
        """SELECT id, classification, local_only, basis FROM rights_policies
           WHERE policy_key = ? AND policy_version = 1""",
        (key,),
    ).fetchone()
    if row is None or (row[1], row[2], row[3]) != ("user_authorized_local", 1, basis):
        raise RuntimeError("stored local rights policy has different terms")
    policy_id = int(row[0])
    sealed = connection.execute(
        "SELECT 1 FROM rights_policy_seals WHERE policy_id = ?", (policy_id,)
    ).fetchone()
    if sealed is None:
        for use_kind in USE_KINDS:
            decision = "allow" if use_kind in LOCAL_ALLOWED_USES else "deny"
            connection.execute(
                """INSERT INTO rights_policy_permissions
                   (policy_id, use_kind, decision, reason) VALUES (?, ?, ?, ?)""",
                (policy_id, use_kind, decision, f"Local user policy sets {use_kind} to {decision}"),
            )
        connection.execute(
            "INSERT INTO rights_policy_seals (policy_id, sealed_at) VALUES (?, ?)",
            (policy_id, _now()),
        )
    return policy_id


def _register_import(
    connection: sqlite3.Connection,
    options: ImportOptions,
    artifact_sha256: str,
    artifact_size: int,
) -> tuple[int, int, int, str, bool]:
    policy_id = _register_policy(connection)
    connection.execute(
        """INSERT OR IGNORE INTO data_sources
           (source_key, name, acquisition_kind, default_policy_id)
           VALUES (?, ?, 'user_supplied_local', ?)""",
        (options.source_key, options.source_name, policy_id),
    )
    source_row = connection.execute(
        "SELECT id FROM data_sources WHERE source_key = ?", (options.source_key,)
    ).fetchone()
    if source_row is None:
        raise RuntimeError("source registration failed")
    source_id = int(source_row[0])
    snapshot_ref = f"local-jsonl:{artifact_sha256}"
    connection.execute(
        """INSERT OR IGNORE INTO source_snapshots
           (source_id, snapshot_ref, snapshot_kind, manifest_sha256, acquired_at, policy_id)
           VALUES (?, ?, 'single_artifact', ?, ?, ?)""",
        (source_id, snapshot_ref, artifact_sha256, _now(), policy_id),
    )
    snapshot_row = connection.execute(
        "SELECT id FROM source_snapshots WHERE snapshot_ref = ?", (snapshot_ref,)
    ).fetchone()
    if snapshot_row is None:
        raise RuntimeError("snapshot registration failed")
    snapshot_id = int(snapshot_row[0])
    connection.execute(
        """INSERT OR IGNORE INTO source_artifacts
           (snapshot_id, artifact_ref, logical_name, media_type, byte_size, sha256,
            vault_key, policy_id)
           VALUES (?, ?, ?, 'application/x-ndjson', ?, ?, ?, ?)""",
        (
            snapshot_id,
            artifact_sha256,
            options.input_path.name,
            artifact_size,
            artifact_sha256,
            artifact_sha256,
            policy_id,
        ),
    )
    artifact_row = connection.execute(
        "SELECT id FROM source_artifacts WHERE snapshot_id = ? AND artifact_ref = ?",
        (snapshot_id, artifact_sha256),
    ).fetchone()
    if artifact_row is None:
        raise RuntimeError("artifact registration failed")
    artifact_id = int(artifact_row[0])
    parser_sha = _hash_file(Path(__file__))
    connection.execute(
        """INSERT OR IGNORE INTO parser_releases
           (parser_key, parser_version, build_sha256, media_type, released_at)
           VALUES (?, ?, ?, 'application/x-ndjson', ?)""",
        (PARSER_KEY, PARSER_VERSION, parser_sha, _now()),
    )
    parser_row = connection.execute(
        """SELECT id FROM parser_releases
           WHERE parser_key = ? AND parser_version = ? AND build_sha256 = ?""",
        (PARSER_KEY, PARSER_VERSION, parser_sha),
    ).fetchone()
    if parser_row is None:
        raise RuntimeError("parser registration failed")
    config_sha = _hash_parts(
        PIPELINE_VERSION,
        str(options.limits.max_artifact_bytes),
        str(options.limits.max_record_bytes),
        str(options.limits.max_records),
        str(options.limits.max_nesting_depth),
        str(options.limits.timeout_seconds),
    )
    fingerprint = _hash_parts(
        snapshot_ref, parser_sha, config_sha, PIPELINE_VERSION, str(policy_id)
    )
    attempt_ref = f"attempt:{fingerprint}"
    connection.execute(
        """INSERT OR IGNORE INTO ingest_attempts
           (attempt_ref, snapshot_id, parser_release_id, config_sha256, pipeline_version,
            policy_id, attempt_fingerprint, max_artifact_bytes, max_record_bytes, max_records,
            max_nesting_depth, max_decompression_ratio, timeout_ms, started_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1.0, ?, ?)""",
        (
            attempt_ref,
            snapshot_id,
            int(parser_row[0]),
            config_sha,
            PIPELINE_VERSION,
            policy_id,
            fingerprint,
            options.limits.max_artifact_bytes,
            options.limits.max_record_bytes,
            options.limits.max_records,
            options.limits.max_nesting_depth,
            int(options.limits.timeout_seconds * 1000),
            _now(),
        ),
    )
    attempt_row = connection.execute(
        "SELECT id FROM ingest_attempts WHERE attempt_fingerprint = ?", (fingerprint,)
    ).fetchone()
    if attempt_row is None:
        raise RuntimeError("attempt registration failed")
    attempt_id = int(attempt_row[0])
    reused = (
        connection.execute(
            """SELECT 1 FROM ingest_attempt_events
           WHERE ingest_attempt_id = ? AND stage = 'complete' AND event_kind = 'succeeded'""",
            (attempt_id,),
        ).fetchone()
        is not None
    )
    return source_id, policy_id, artifact_id, attempt_ref, reused


def _event(
    connection: sqlite3.Connection,
    attempt_id: int,
    stage: str,
    event_kind: str,
    counters: dict[str, int] | None = None,
) -> None:
    connection.execute(
        """INSERT INTO ingest_attempt_events
           (ingest_attempt_id, stage, event_kind, event_at, counters_json)
           VALUES (?, ?, ?, ?, ?)""",
        (attempt_id, stage, event_kind, _now(), json.dumps(counters or {})),
    )


def _normalize(
    connection: sqlite3.Connection,
    record: CatalogRecord,
    context: _NormalizeContext,
) -> None:
    snapshot_ref = f"local-jsonl:{context.artifact_sha256}"
    connection.execute(
        """INSERT OR IGNORE INTO provenance_records
           (source_id, policy_id, snapshot_ref, artifact_sha256, record_fingerprint,
            parser_release_ref, ingest_attempt_ref, observed_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            context.source_id,
            context.policy_id,
            snapshot_ref,
            context.artifact_sha256,
            context.record_fingerprint,
            context.parser_ref,
            context.attempt_ref,
            _now(),
        ),
    )
    provenance_row = connection.execute(
        """SELECT id FROM provenance_records
           WHERE source_id = ? AND snapshot_ref = ? AND record_fingerprint = ?
             AND parser_release_ref = ?""",
        (context.source_id, snapshot_ref, context.record_fingerprint, context.parser_ref),
    ).fetchone()
    if provenance_row is None:
        raise RuntimeError("provenance registration failed")
    provenance_id = int(provenance_row[0])
    connection.execute(
        "INSERT OR IGNORE INTO identifier_types (type_key, name) VALUES ('source_id', 'Source ID')"
    )
    identifier_row = connection.execute(
        "SELECT id FROM identifier_types WHERE type_key = 'source_id'"
    ).fetchone()
    if identifier_row is None:
        raise RuntimeError("identifier type registration failed")
    identifier_type_id = int(identifier_row[0])
    entity_row = connection.execute(
        """SELECT entity_id FROM entity_identifiers
           WHERE identifier_type_id = ? AND namespace = ? AND normalized_value = ?
           ORDER BY id LIMIT 1""",
        (
            identifier_type_id,
            source_id_namespace := str(context.source_id),
            record.external_id.strip(),
        ),
    ).fetchone()
    if entity_row is None:
        cursor = connection.execute(
            "INSERT INTO catalog_entities (entity_kind) VALUES (?)", (record.kind,)
        )
        entity_id = _lastrowid(cursor)
        if record.kind == "genre":
            connection.execute(
                "INSERT INTO genres (id, slug, name) VALUES (?, ?, ?)",
                (entity_id, record.slug, record.name),
            )
        else:
            connection.execute("INSERT INTO artists (id) VALUES (?)", (entity_id,))
    else:
        entity_id = int(entity_row[0])
    connection.execute(
        """INSERT OR IGNORE INTO entity_provenance
           (entity_id, provenance_id, field_set_json, is_primary) VALUES (?, ?, ?, 0)""",
        (entity_id, provenance_id, '["name","identifiers"]'),
    )
    all_identifiers = (
        Identifier(type_key="source_id", namespace=source_id_namespace, value=record.external_id),
        *record.identifiers,
    )
    for identifier in all_identifiers:
        connection.execute(
            "INSERT OR IGNORE INTO identifier_types (type_key, name) VALUES (?, ?)",
            (identifier.type_key, identifier.type_key.replace("_", " ").title()),
        )
        type_row = connection.execute(
            "SELECT id FROM identifier_types WHERE type_key = ?", (identifier.type_key,)
        ).fetchone()
        if type_row is None:
            raise RuntimeError("identifier type lookup failed")
        connection.execute(
            """INSERT OR IGNORE INTO entity_identifiers
               (entity_id, identifier_type_id, namespace, value, normalized_value, provenance_id)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                entity_id,
                int(type_row[0]),
                identifier.namespace,
                identifier.value,
                identifier.value.strip(),
                provenance_id,
            ),
        )
    for kind, name, preferred in (
        ("primary", record.name, 1),
        *[("alias", item, 0) for item in record.aliases],
    ):
        name_fingerprint = _hash_parts(str(entity_id), kind, name, context.record_fingerprint)
        connection.execute(
            """INSERT OR IGNORE INTO entity_names
               (entity_id, name_kind, name, language_tag, is_preferred, provenance_id, fingerprint)
               VALUES (?, ?, ?, 'und', ?, ?, ?)""",
            (entity_id, kind, name, preferred, provenance_id, name_fingerprint),
        )
    search_text = " ".join((record.name, *record.aliases))
    connection.execute(
        """INSERT OR IGNORE INTO search_documents
           (entity_id, language_tag, field_kind, search_text, input_fingerprint,
            provenance_id, policy_id)
           VALUES (?, 'und', 'name', ?, ?, ?, ?)""",
        (
            entity_id,
            search_text,
            _hash_parts(search_text, context.record_fingerprint),
            provenance_id,
            context.policy_id,
        ),
    )
    connection.execute(
        """INSERT OR IGNORE INTO normalization_exports
           (staged_record_id, source_object_observation_id, provenance_id, projection_kind,
            output_fingerprint, exported_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (
            context.staged_record_id,
            context.observation_id,
            provenance_id,
            record.kind,
            _hash_parts(str(context.staged_record_id), str(entity_id), context.record_fingerprint),
            _now(),
        ),
    )


def _summary(
    connection: sqlite3.Connection,
    artifact_sha256: str,
    attempt_ref: str,
    *,
    reused: bool,
) -> ImportSummary:
    attempt_id = int(
        connection.execute(
            "SELECT id FROM ingest_attempts WHERE attempt_ref = ?", (attempt_ref,)
        ).fetchone()[0]
    )
    accepted = int(
        connection.execute(
            """SELECT count(*) FROM staged_records
               WHERE ingest_attempt_id = ? AND parse_status = 'accepted'""",
            (attempt_id,),
        ).fetchone()[0]
    )
    quarantined = int(
        connection.execute(
            """SELECT count(*) FROM quarantine_events AS event
               LEFT JOIN staged_records AS record ON record.id = event.staged_record_id
               LEFT JOIN source_artifacts AS artifact ON artifact.id = event.artifact_id
               LEFT JOIN ingest_attempts AS attempt ON attempt.snapshot_id = artifact.snapshot_id
               WHERE record.ingest_attempt_id = ? OR (record.id IS NULL AND attempt.id = ?)""",
            (attempt_id, attempt_id),
        ).fetchone()[0]
    )
    entities = int(connection.execute("SELECT count(*) FROM catalog_entities").fetchone()[0])
    return ImportSummary(
        artifact_sha256=artifact_sha256,
        attempt_ref=attempt_ref,
        accepted=accepted,
        quarantined=quarantined,
        catalog_entities=entities,
        reused_attempt=reused,
    )


def _decode_record(line: _BoundedLine, maximum_depth: int) -> tuple[CatalogRecord, str, str]:
    decoded: object = json.loads(line.captured)
    if _json_depth(decoded) > maximum_depth:
        raise RecordParseError("record exceeds the nesting limit")
    record = parse_catalog_record(decoded)
    canonical = json.dumps(decoded, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return record, canonical, hashlib.sha256(canonical.encode()).hexdigest()


def _reject_record(
    connection: sqlite3.Connection,
    context: _ImportContext,
    record_context: _RecordContext,
    error: Exception,
) -> None:
    cursor = connection.execute(
        """INSERT INTO staged_records
           (ingest_attempt_id, artifact_id, record_ordinal, byte_offset, byte_length,
            exact_record_sha256, parse_status, record_fingerprint)
           VALUES (?, ?, ?, ?, ?, ?, 'rejected', ?)""",
        (
            context.attempt_id,
            context.artifact_id,
            record_context.ordinal,
            record_context.byte_offset,
            record_context.line.byte_length,
            record_context.line.sha256,
            record_context.fingerprint,
        ),
    )
    connection.execute(
        """INSERT INTO quarantine_events
           (artifact_id, staged_record_id, reason_code, diagnostic_json, event_kind, event_at)
           VALUES (?, ?, 'malformed', ?, 'quarantined', ?)""",
        (
            context.artifact_id,
            _lastrowid(cursor),
            json.dumps({"error": str(error)}),
            _now(),
        ),
    )


def _accept_record(
    connection: sqlite3.Connection,
    options: ImportOptions,
    context: _ImportContext,
    record_context: _RecordContext,
    decoded: _DecodedRecord,
) -> None:
    cursor = connection.execute(
        """INSERT INTO staged_records
           (ingest_attempt_id, artifact_id, record_ordinal, byte_offset, byte_length,
            exact_record_sha256, parsed_json, canonical_json_sha256, parse_status,
            record_fingerprint)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'accepted', ?)""",
        (
            context.attempt_id,
            context.artifact_id,
            record_context.ordinal,
            record_context.byte_offset,
            record_context.line.byte_length,
            record_context.line.sha256,
            decoded.canonical,
            decoded.canonical_sha,
            record_context.fingerprint,
        ),
    )
    staged_record_id = _lastrowid(cursor)
    connection.execute(
        """INSERT OR IGNORE INTO source_objects
           (source_id, record_kind, namespace, external_id, first_observed_at)
           VALUES (?, ?, ?, ?, ?)""",
        (
            context.source_id,
            decoded.record.kind,
            options.source_key,
            decoded.record.external_id,
            _now(),
        ),
    )
    object_row = connection.execute(
        """SELECT id FROM source_objects
           WHERE source_id = ? AND record_kind = ? AND namespace = ?
             AND scope_key = '' AND external_id = ?""",
        (
            context.source_id,
            decoded.record.kind,
            options.source_key,
            decoded.record.external_id,
        ),
    ).fetchone()
    if object_row is None:
        raise RuntimeError("source object registration failed")
    source_object_id = int(object_row[0])
    observation_fingerprint = _hash_parts(
        str(source_object_id), str(staged_record_id), decoded.canonical_sha
    )
    observation_cursor = connection.execute(
        """INSERT INTO source_object_observations
           (source_object_id, staged_record_id, observation_kind, observed_at,
            observation_fingerprint)
           VALUES (?, ?, 'present', ?, ?)""",
        (source_object_id, staged_record_id, _now(), observation_fingerprint),
    )
    _normalize(
        connection,
        decoded.record,
        _NormalizeContext(
            source_id=context.source_id,
            policy_id=context.policy_id,
            artifact_sha256=context.artifact_sha256,
            attempt_ref=context.attempt_ref,
            staged_record_id=staged_record_id,
            observation_id=_lastrowid(observation_cursor),
            record_fingerprint=record_context.fingerprint,
            parser_ref=context.parser_ref,
        ),
    )


def _process_records(
    connection: sqlite3.Connection,
    options: ImportOptions,
    context: _ImportContext,
) -> int:
    byte_offset = 0
    ordinal = 0
    with options.input_path.open("rb") as stream:
        while line := _read_bounded_line(stream, options.limits.max_record_bytes):
            if ordinal >= options.limits.max_records:
                connection.execute(
                    """INSERT INTO quarantine_events
                       (artifact_id, reason_code, diagnostic_json, event_kind, event_at)
                       VALUES (?, 'record_limit', '{}', 'quarantined', ?)""",
                    (context.artifact_id, _now()),
                )
                break
            if time.monotonic() - context.started > options.limits.timeout_seconds:
                connection.execute(
                    """INSERT INTO quarantine_events
                       (artifact_id, reason_code, diagnostic_json, event_kind, event_at)
                       VALUES (?, 'timeout', '{}', 'quarantined', ?)""",
                    (context.artifact_id, _now()),
                )
                break
            record_fingerprint = _hash_parts(
                context.attempt_ref,
                context.artifact_sha256,
                str(ordinal),
                line.sha256,
            )
            record_context = _RecordContext(line, ordinal, byte_offset, record_fingerprint)
            if line.oversized:
                connection.execute(
                    """INSERT INTO quarantine_events
                       (artifact_id, reason_code, diagnostic_json, event_kind, event_at)
                       VALUES (?, 'size_limit', ?, 'quarantined', ?)""",
                    (
                        context.artifact_id,
                        json.dumps({"record_ordinal": ordinal}),
                        _now(),
                    ),
                )
            else:
                try:
                    record, canonical, canonical_sha = _decode_record(
                        line, options.limits.max_nesting_depth
                    )
                except (json.JSONDecodeError, UnicodeDecodeError, RecordParseError) as error:
                    _reject_record(connection, context, record_context, error)
                else:
                    _accept_record(
                        connection,
                        options,
                        context,
                        record_context,
                        _DecodedRecord(record, canonical, canonical_sha),
                    )
            byte_offset += line.consumed
            ordinal += 1
    return ordinal


def _import_jsonl_sync(options: ImportOptions) -> ImportSummary:
    database = Database(options.database_path)
    database.initialize()
    artifact_size = options.input_path.stat().st_size
    artifact_sha256 = _hash_file(options.input_path)
    _store_in_vault(options.input_path, options.vault_path, artifact_sha256)
    started = time.monotonic()
    parser_ref = f"{PARSER_KEY}:{PARSER_VERSION}:{_hash_file(Path(__file__))}"
    with database.connect() as connection, connection:
        source_id, policy_id, artifact_id, attempt_ref, reused = _register_import(
            connection, options, artifact_sha256, artifact_size
        )
        attempt_row = connection.execute(
            "SELECT id FROM ingest_attempts WHERE attempt_ref = ?", (attempt_ref,)
        ).fetchone()
        if attempt_row is None:
            raise RuntimeError("attempt lookup failed")
        attempt_id = int(attempt_row[0])
        if reused:
            return _summary(connection, artifact_sha256, attempt_ref, reused=True)
        _event(connection, attempt_id, "discover", "started")
        if artifact_size > options.limits.max_artifact_bytes:
            connection.execute(
                """INSERT INTO quarantine_events
                   (artifact_id, reason_code, diagnostic_json, event_kind, event_at)
                   VALUES (?, 'size_limit', ?, 'quarantined', ?)""",
                (artifact_id, json.dumps({"artifact_bytes": artifact_size}), _now()),
            )
            _event(connection, attempt_id, "complete", "succeeded")
            return _summary(connection, artifact_sha256, attempt_ref, reused=False)
        context = _ImportContext(
            source_id=source_id,
            policy_id=policy_id,
            artifact_id=artifact_id,
            artifact_sha256=artifact_sha256,
            attempt_ref=attempt_ref,
            attempt_id=attempt_id,
            started=started,
            parser_ref=parser_ref,
        )
        ordinal = _process_records(connection, options, context)
        _event(connection, attempt_id, "complete", "succeeded", {"records": ordinal})
        return _summary(connection, artifact_sha256, attempt_ref, reused=False)


def import_jsonl_sync(options: ImportOptions) -> ImportSummary:
    """Run a local import for deterministic command-line pipeline steps."""
    return _import_jsonl_sync(options)


async def import_jsonl(options: ImportOptions) -> ImportSummary:
    """Run one local import without blocking the caller's event loop."""
    return await asyncio.to_thread(import_jsonl_sync, options)
