"""Shared, resumable source ingestion lifecycle for explicitly registered adapters."""

import hashlib
import json
import sqlite3
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import NamedTuple, Never

from pydantic import BaseModel, ConfigDict, Field, model_validator

from opennoise.catalog.registry import ProjectorRegistry
from opennoise.clients.downloads import download_verified
from opennoise.db import Database
from opennoise.models.pipeline import ParsedSourceRecord, RejectedSourceRecord, SourceLimits
from opennoise.models.sources import DownloadResult, DownloadSource
from opennoise.sources.registry import AdapterRegistry, SourceAdapter

PIPELINE_VERSION = "source-pipeline-v1"


class _FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")


class DeterministicPartition(_FrozenModel):
    """Select a stable SHA256 prefix partition over source object IDs."""

    sha256_prefix: str = Field(default="0", pattern=r"^[0-9a-f]{0,8}$")

    def accepts(self, external_id: str) -> bool:
        """Return whether one source identity belongs to this partition."""
        return hashlib.sha256(external_id.encode()).hexdigest().startswith(self.sha256_prefix)

    @property
    def expected_fraction(self) -> float:
        """Return the exact ideal hash-space fraction selected by this prefix."""
        return 16.0 ** -len(self.sha256_prefix)


class PipelineOptions(_FrozenModel):
    """Configure one bounded shared-pipeline run."""

    manifest_path: Path
    source_id: str = Field(min_length=1)
    database_path: Path
    vault_path: Path
    partition: DeterministicPartition = DeterministicPartition()
    limits: SourceLimits = SourceLimits()
    checkpoint_every: int = Field(default=10_000, gt=0)
    offline: bool = False

    @model_validator(mode="after")
    def artifact_limit_covers_manifest_later(self) -> "PipelineOptions":
        """Keep cross-boundary source checks in the orchestration entry point."""
        return self


class PipelineSummary(_FrozenModel):
    """Report exact pipeline and partition counters."""

    source_id: str
    artifact_sha256: str
    attempt_ref: str
    raw: int
    selected: int
    accepted: int
    quarantined: int
    duplicates: int
    last_ordinal: int
    reused_attempt: bool
    partition_sha256_prefix: str
    expected_partition_fraction: float
    elapsed_seconds: float


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _hash_parts(*parts: str) -> str:
    digest = hashlib.sha256()
    for part in parts:
        digest.update(part.encode())
        digest.update(b"\0")
    return digest.hexdigest()


def _one_id(connection: sqlite3.Connection, query: str, values: tuple[object, ...]) -> int:
    row = connection.execute(query, values).fetchone()
    if row is None:
        raise RuntimeError("registered ingestion object could not be read back")
    return int(row[0])


def _lastrowid(cursor: sqlite3.Cursor) -> int:
    row_id = cursor.lastrowid
    if row_id is None:
        raise RuntimeError("SQLite insert returned no row ID")
    return row_id


def _policy_id(connection: sqlite3.Connection, source: DownloadSource) -> int:
    policy_key = f"manifest:{source.id}:{source.checksum}"
    basis = f"{source.data_license}; {source.license_url or 'no license URL declared'}"
    connection.execute(
        """INSERT OR IGNORE INTO rights_policies
           (policy_key, policy_version, classification, local_only, basis, reviewed_at)
           VALUES (?, 1, ?, ?, ?, ?)""",
        (policy_key, source.rights_classification, int(source.local_only), basis, _now()),
    )
    policy_id = _one_id(
        connection,
        "SELECT id FROM rights_policies WHERE policy_key = ? AND policy_version = 1",
        (policy_key,),
    )
    sealed = connection.execute(
        "SELECT 1 FROM rights_policy_seals WHERE policy_id = ?", (policy_id,)
    ).fetchone()
    if sealed is None:
        permissions = {
            "normalize": source.normalize,
            "local_search": source.local_search,
            "display": source.display,
            "embed": source.embed,
            "train": source.train,
            "export": source.export_metadata,
        }
        for use_kind, allowed in permissions.items():
            connection.execute(
                """INSERT INTO rights_policy_permissions
                   (policy_id, use_kind, decision, reason) VALUES (?, ?, ?, ?)""",
                (
                    policy_id,
                    use_kind,
                    "allow" if allowed else "deny",
                    f"Pinned source manifest sets {use_kind} to {allowed}",
                ),
            )
        connection.execute(
            "INSERT INTO rights_policy_seals (policy_id, sealed_at) VALUES (?, ?)",
            (policy_id, _now()),
        )
    return policy_id


class _RunContext(_FrozenModel):
    source_id: int
    policy_id: int
    artifact_id: int
    attempt_id: int
    attempt_ref: str
    parser_ref: str
    reused: bool


class _EventSpec(_FrozenModel):
    stage: str
    kind: str
    error_code: str | None = None
    error_text: str | None = None


def _register_run(
    connection: sqlite3.Connection,
    source: DownloadSource,
    download: DownloadResult,
    adapter: SourceAdapter,
    options: PipelineOptions,
) -> _RunContext:
    policy_id = _policy_id(connection, source)
    connection.execute(
        """INSERT OR IGNORE INTO data_sources
           (source_key, name, homepage_url, license_name, license_url, acquisition_kind,
            default_policy_id)
           VALUES (?, ?, ?, ?, ?, 'public_download', ?)""",
        (
            source.id,
            source.id.replace("_", " ").title(),
            str(source.discovery_url),
            source.data_license,
            source.license_url or None,
            policy_id,
        ),
    )
    source_id = _one_id(
        connection, "SELECT id FROM data_sources WHERE source_key = ?", (source.id,)
    )
    manifest_sha = hashlib.sha256(source.model_dump_json().encode()).hexdigest()
    snapshot_ref = f"{source.id}:{source.snapshot}"
    connection.execute(
        """INSERT OR IGNORE INTO source_snapshots
           (source_id, snapshot_ref, snapshot_kind, upstream_version, manifest_sha256,
            acquired_at, policy_id)
           VALUES (?, ?, 'full', ?, ?, ?, ?)""",
        (source_id, snapshot_ref, source.snapshot, manifest_sha, _now(), policy_id),
    )
    snapshot_id = _one_id(
        connection, "SELECT id FROM source_snapshots WHERE snapshot_ref = ?", (snapshot_ref,)
    )
    connection.execute(
        """INSERT OR IGNORE INTO source_artifacts
           (snapshot_id, artifact_ref, logical_name, media_type, byte_size, sha256,
            vault_key, policy_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            snapshot_id,
            source.checksum,
            Path(str(source.url)).name,
            source.expected_content_type,
            download.byte_size,
            download.sha256,
            download.sha256,
            policy_id,
        ),
    )
    artifact_id = _one_id(
        connection,
        "SELECT id FROM source_artifacts WHERE snapshot_id = ? AND artifact_ref = ?",
        (snapshot_id, source.checksum),
    )
    parser_sha = _hash_parts(adapter.key, adapter.version)
    parser_ref = f"{adapter.key}:{adapter.version}:{parser_sha}"
    connection.execute(
        """INSERT OR IGNORE INTO parser_releases
           (parser_key, parser_version, build_sha256, media_type, released_at)
           VALUES (?, ?, ?, ?, ?)""",
        (adapter.key, adapter.version, parser_sha, source.expected_content_type, _now()),
    )
    parser_id = _one_id(
        connection,
        """SELECT id FROM parser_releases
           WHERE parser_key = ? AND parser_version = ? AND build_sha256 = ?""",
        (adapter.key, adapter.version, parser_sha),
    )
    config_sha = _hash_parts(
        PIPELINE_VERSION,
        options.partition.sha256_prefix,
        options.limits.model_dump_json(),
        str(options.checkpoint_every),
    )
    attempt_fingerprint = _hash_parts(
        snapshot_ref, download.sha256, parser_ref, config_sha, str(policy_id)
    )
    attempt_ref = f"attempt:{attempt_fingerprint}"
    connection.execute(
        """INSERT OR IGNORE INTO ingest_attempts
           (attempt_ref, snapshot_id, parser_release_id, config_sha256, pipeline_version,
            policy_id, attempt_fingerprint, max_artifact_bytes, max_record_bytes, max_records,
            max_nesting_depth, max_decompression_ratio, timeout_ms, started_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 64, ?, ?, ?)""",
        (
            attempt_ref,
            snapshot_id,
            parser_id,
            config_sha,
            PIPELINE_VERSION,
            policy_id,
            attempt_fingerprint,
            options.limits.max_archive_bytes,
            options.limits.max_record_bytes,
            options.limits.max_records,
            options.limits.max_decompression_ratio,
            int(options.limits.timeout_seconds * 1000),
            _now(),
        ),
    )
    attempt_id = _one_id(
        connection,
        "SELECT id FROM ingest_attempts WHERE attempt_fingerprint = ?",
        (attempt_fingerprint,),
    )
    reused = (
        connection.execute(
            """SELECT 1 FROM ingest_attempt_events WHERE ingest_attempt_id = ?
               AND stage = 'complete' AND event_kind = 'succeeded'""",
            (attempt_id,),
        ).fetchone()
        is not None
    )
    return _RunContext(
        source_id=source_id,
        policy_id=policy_id,
        artifact_id=artifact_id,
        attempt_id=attempt_id,
        attempt_ref=attempt_ref,
        parser_ref=parser_ref,
        reused=reused,
    )


def _last_counters(connection: sqlite3.Connection, attempt_id: int) -> dict[str, int]:
    row = connection.execute(
        """SELECT counters_json FROM ingest_attempt_events
           WHERE ingest_attempt_id = ? AND event_kind IN ('checkpoint', 'succeeded')
           ORDER BY id DESC LIMIT 1""",
        (attempt_id,),
    ).fetchone()
    if row is None:
        return {
            "raw": 0,
            "selected": 0,
            "accepted": 0,
            "quarantined": 0,
            "duplicates": 0,
            "last_ordinal": -1,
        }
    raw: object = json.loads(str(row[0]))
    if not isinstance(raw, dict):
        raise TypeError("stored pipeline counters are invalid")
    return {
        key: int(raw[key])
        for key in ("raw", "selected", "accepted", "quarantined", "duplicates", "last_ordinal")
    }


def _event(
    connection: sqlite3.Connection,
    attempt_id: int,
    counters: dict[str, int],
    event: _EventSpec,
) -> None:
    connection.execute(
        """INSERT INTO ingest_attempt_events
           (ingest_attempt_id, stage, event_kind, event_at, counters_json,
            error_code, error_text)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (
            attempt_id,
            event.stage,
            event.kind,
            _now(),
            json.dumps(counters, sort_keys=True),
            event.error_code,
            event.error_text,
        ),
    )


def register_verified_run(
    connection: sqlite3.Connection,
    source: DownloadSource,
    download: DownloadResult,
    adapter: SourceAdapter,
    options: PipelineOptions,
) -> _RunContext:
    """Register one verified artifact for a shared or multi-artifact lifecycle."""
    return _register_run(connection, source, download, adapter, options)


def record_pipeline_event(  # noqa: PLR0913
    connection: sqlite3.Connection,
    attempt_id: int,
    counters: dict[str, int],
    *,
    stage: str,
    kind: str,
    error_code: str | None = None,
    error_text: str | None = None,
) -> None:
    """Append one typed lifecycle event without exposing the internal event model."""
    _event(
        connection,
        attempt_id,
        counters,
        _EventSpec(
            stage=stage,
            kind=kind,
            error_code=error_code,
            error_text=error_text,
        ),
    )


def empty_pipeline_counters() -> dict[str, int]:
    """Return the complete zero-record lifecycle counter shape."""
    return {
        "raw": 0,
        "selected": 0,
        "accepted": 0,
        "quarantined": 0,
        "duplicates": 0,
        "last_ordinal": -1,
    }


def _insert_rejection(
    connection: sqlite3.Connection,
    context: _RunContext,
    record: RejectedSourceRecord,
) -> None:
    fingerprint = _hash_parts(str(context.artifact_id), str(record.ordinal), record.exact_sha256)
    cursor = connection.execute(
        """INSERT INTO staged_records
           (ingest_attempt_id, artifact_id, record_ordinal, byte_length, exact_record_sha256,
            parse_status, record_fingerprint)
           VALUES (?, ?, ?, ?, ?, 'rejected', ?)""",
        (
            context.attempt_id,
            context.artifact_id,
            record.ordinal,
            None,
            record.exact_sha256,
            fingerprint,
        ),
    )
    connection.execute(
        """INSERT INTO quarantine_events
           (artifact_id, staged_record_id, reason_code, diagnostic_json, event_kind, event_at)
           VALUES (?, ?, 'malformed', ?, 'quarantined', ?)""",
        (
            context.artifact_id,
            cursor.lastrowid,
            json.dumps({"error": record.reason[:2000], "byte_length": record.byte_length}),
            _now(),
        ),
    )


def _insert_projection(
    connection: sqlite3.Connection,
    source: DownloadSource,
    context: _RunContext,
    record: ParsedSourceRecord,
    projectors: ProjectorRegistry,
) -> bool:
    projection = record.projection
    canonical = projection.model_dump_json()
    canonical_sha = hashlib.sha256(canonical.encode()).hexdigest()
    record_fingerprint = _hash_parts(
        source.id, source.snapshot, projection.external_id, record.exact_sha256
    )
    cursor = connection.execute(
        """INSERT INTO staged_records
           (ingest_attempt_id, artifact_id, record_ordinal, byte_length, exact_record_sha256,
            parsed_json, canonical_json_sha256, parse_status, record_fingerprint)
           VALUES (?, ?, ?, ?, ?, ?, ?, 'accepted', ?)""",
        (
            context.attempt_id,
            context.artifact_id,
            record.ordinal,
            record.byte_length,
            record.exact_sha256,
            canonical,
            canonical_sha,
            record_fingerprint,
        ),
    )
    staged_id = _lastrowid(cursor)
    connection.execute(
        """INSERT OR IGNORE INTO source_objects
           (source_id, record_kind, namespace, external_id, first_observed_at)
           VALUES (?, ?, ?, ?, ?)""",
        (
            context.source_id,
            projection.projection_kind,
            source.adapter,
            projection.external_id,
            _now(),
        ),
    )
    object_id = _one_id(
        connection,
        """SELECT id FROM source_objects WHERE source_id = ? AND record_kind = ?
           AND namespace = ? AND scope_key = '' AND external_id = ?""",
        (
            context.source_id,
            projection.projection_kind,
            source.adapter,
            projection.external_id,
        ),
    )
    observation_fingerprint = _hash_parts(str(object_id), record_fingerprint)
    observation_cursor = connection.execute(
        """INSERT INTO source_object_observations
           (source_object_id, staged_record_id, observation_kind, observed_at,
            observation_fingerprint)
           VALUES (?, ?, 'present', ?, ?)""",
        (object_id, staged_id, _now(), observation_fingerprint),
    )
    observation_id = _lastrowid(observation_cursor)
    connection.execute(
        """INSERT OR IGNORE INTO provenance_records
           (source_id, policy_id, snapshot_ref, artifact_sha256, record_fingerprint,
            parser_release_ref, ingest_attempt_ref, observed_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            context.source_id,
            context.policy_id,
            f"{source.id}:{source.snapshot}",
            source.checksum,
            record_fingerprint,
            context.parser_ref,
            context.attempt_ref,
            _now(),
        ),
    )
    provenance_id = _one_id(
        connection,
        """SELECT id FROM provenance_records
           WHERE source_id = ? AND snapshot_ref = ? AND record_fingerprint = ?
             AND parser_release_ref = ?""",
        (
            context.source_id,
            f"{source.id}:{source.snapshot}",
            record_fingerprint,
            context.parser_ref,
        ),
    )
    result = projectors.resolve(projection).persist(
        connection,
        projection,
        provenance_id=provenance_id,
        policy_id=context.policy_id,
    )
    connection.execute(
        """INSERT INTO normalization_exports
           (staged_record_id, source_object_observation_id, provenance_id, projection_kind,
            output_fingerprint, exported_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (
            staged_id,
            observation_id,
            provenance_id,
            result.projection_kind,
            _hash_parts(str(staged_id), str(result.target_id), canonical_sha),
            _now(),
        ),
    )
    return result.duplicate


def persist_pipeline_record(
    connection: sqlite3.Connection,
    source: DownloadSource,
    context: _RunContext,
    record: ParsedSourceRecord | RejectedSourceRecord,
    projectors: ProjectorRegistry,
) -> bool:
    """Stage and persist one aggregate record through the shared projection boundary."""
    if isinstance(record, RejectedSourceRecord):
        _insert_rejection(connection, context, record)
        return False
    return _insert_projection(connection, source, context, record, projectors)


class _Completion(_FrozenModel):
    reused: bool
    elapsed_seconds: float = Field(ge=0)


def _summary(
    source: DownloadSource,
    context: _RunContext,
    counters: dict[str, int],
    options: PipelineOptions,
    completion: _Completion,
) -> PipelineSummary:
    return PipelineSummary(
        source_id=source.id,
        artifact_sha256=source.checksum,
        attempt_ref=context.attempt_ref,
        raw=counters["raw"],
        selected=counters["selected"],
        accepted=counters["accepted"],
        quarantined=counters["quarantined"],
        duplicates=counters["duplicates"],
        last_ordinal=counters["last_ordinal"],
        reused_attempt=completion.reused,
        partition_sha256_prefix=options.partition.sha256_prefix,
        expected_partition_fraction=options.partition.expected_fraction,
        elapsed_seconds=completion.elapsed_seconds,
    )


class _StreamJob(NamedTuple):
    source: DownloadSource
    adapter: SourceAdapter
    projectors: ProjectorRegistry
    options: PipelineOptions
    context: _RunContext


def _cancel_for_timeout(
    connection: sqlite3.Connection,
    context: _RunContext,
    counters: dict[str, int],
) -> Never:
    connection.rollback()
    _event(
        connection,
        context.attempt_id,
        counters,
        _EventSpec(
            stage="parse",
            kind="cancelled",
            error_code="timeout",
            error_text="source ingestion exceeded timeout_seconds",
        ),
    )
    connection.commit()
    raise TimeoutError("source ingestion exceeded timeout_seconds")


def _process_record(
    connection: sqlite3.Connection,
    job: _StreamJob,
    record: ParsedSourceRecord | RejectedSourceRecord,
    counters: dict[str, int],
) -> None:
    counters["raw"] += 1
    counters["last_ordinal"] = record.ordinal
    match record:
        case RejectedSourceRecord():
            _insert_rejection(connection, job.context, record)
            counters["quarantined"] += 1
        case ParsedSourceRecord() if job.options.partition.accepts(record.projection.external_id):
            counters["selected"] += 1
            duplicate = _insert_projection(
                connection,
                job.source,
                job.context,
                record,
                job.projectors,
            )
            counters["accepted"] += 1
            counters["duplicates"] += int(duplicate)
        case ParsedSourceRecord():
            pass


def _process_stream(
    connection: sqlite3.Connection,
    download: DownloadResult,
    job: _StreamJob,
    counters: dict[str, int],
    started: float,
) -> None:
    committed_counters = dict(counters)
    try:
        for record in job.adapter.iter_records(
            download.path,
            job.options.limits,
            start_after=counters["last_ordinal"],
        ):
            if time.monotonic() - started > job.options.limits.timeout_seconds:
                _cancel_for_timeout(connection, job.context, committed_counters)
            _process_record(connection, job, record, counters)
            if counters["raw"] % job.options.checkpoint_every == 0:
                _event(
                    connection,
                    job.context.attempt_id,
                    counters,
                    _EventSpec(stage="normalize", kind="checkpoint"),
                )
                connection.commit()
                committed_counters = dict(counters)
    except TimeoutError:
        raise
    except Exception as error:
        connection.rollback()
        _event(
            connection,
            job.context.attempt_id,
            committed_counters,
            _EventSpec(
                stage="parse",
                kind="failed",
                error_code=type(error).__name__,
                error_text=str(error)[:2000],
            ),
        )
        connection.execute(
            """INSERT INTO quarantine_events
               (artifact_id, reason_code, diagnostic_json, event_kind, event_at)
               VALUES (?, 'other', ?, 'quarantined', ?)""",
            (
                job.context.artifact_id,
                json.dumps(
                    {"error_type": type(error).__name__, "error": str(error)[:2000]},
                    sort_keys=True,
                ),
                _now(),
            ),
        )
        connection.commit()
        raise


def _ingest_sync(
    source: DownloadSource,
    download: DownloadResult,
    adapter: SourceAdapter,
    projectors: ProjectorRegistry,
    options: PipelineOptions,
) -> PipelineSummary:
    started = time.monotonic()
    database = Database(options.database_path)
    database.initialize()
    with database.connect() as connection:
        context = _register_run(connection, source, download, adapter, options)
        counters = _last_counters(connection, context.attempt_id)
        if context.reused:
            return _summary(
                source,
                context,
                counters,
                options,
                _Completion(reused=True, elapsed_seconds=time.monotonic() - started),
            )
        if counters["last_ordinal"] < 0:
            _event(
                connection,
                context.attempt_id,
                counters,
                _EventSpec(stage="parse", kind="started"),
            )
            connection.commit()
        _process_stream(
            connection,
            download,
            _StreamJob(source, adapter, projectors, options, context),
            counters,
            started,
        )
        _event(
            connection,
            context.attempt_id,
            counters,
            _EventSpec(stage="complete", kind="succeeded"),
        )
        connection.commit()
    return _summary(
        source,
        context,
        counters,
        options,
        _Completion(reused=False, elapsed_seconds=time.monotonic() - started),
    )


async def run_source_pipeline(
    source: DownloadSource,
    registry: AdapterRegistry,
    projectors: ProjectorRegistry,
    options: PipelineOptions,
) -> PipelineSummary:
    """Download asynchronously, then stream sync parsing inside the caller's job boundary."""
    if source.id != options.source_id:
        raise ValueError("pipeline source_id does not match the parsed source")
    if source.expected_bytes > options.limits.max_archive_bytes:
        raise ValueError("source expected_bytes exceeds max_archive_bytes")
    adapter = registry.resolve(source)
    download = await download_verified(source, options.vault_path, offline=options.offline)
    return _ingest_sync(source, download, adapter, projectors, options)
