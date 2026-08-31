"""Atomic lifecycle for one aggregate derived from several verified artifacts."""

import asyncio
import hashlib
import json
import sqlite3
import time
from collections.abc import Callable, Iterator
from pathlib import Path

import httpx
from pydantic import Field, HttpUrl

from musix.catalog.registry import ProjectorRegistry
from musix.clients.downloads import download_verified
from musix.db import Database
from musix.models import FrozenModel
from musix.models.pipeline import (
    ParsedSourceRecord,
    RejectedSourceRecord,
    SourceLimits,
    SourceRecord,
)
from musix.models.sources import DownloadResult, DownloadSource
from musix.pipeline.runner import (
    DeterministicPartition,
    PipelineOptions,
    empty_pipeline_counters,
    persist_pipeline_record,
    record_pipeline_event,
    register_verified_run,
)
from musix.sources.registry import SourceAdapter
from musix.storage import LocalObjectStore, ObjectKey

type RecordFactory = Callable[[tuple[DownloadResult, ...]], Iterator[SourceRecord]]
MINIMUM_INPUT_ARTIFACTS = 2
DOWNLOAD_ATTEMPTS = 3
HTTP_TOO_MANY_REQUESTS = 429
HTTP_SERVER_ERROR_MINIMUM = 500


class MultiArtifactOptions(FrozenModel):
    """Bound one exact multi-input aggregate and its generated lifecycle object."""

    manifest_path: Path
    database_path: Path
    vault_path: Path
    aggregate_source_id: str = Field(min_length=1, max_length=200)
    configuration_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    limits: SourceLimits


async def _download_with_retry(
    source: DownloadSource, vault_path: Path, timeout_seconds: float
) -> DownloadResult:
    for attempt in range(1, DOWNLOAD_ATTEMPTS + 1):
        try:
            return await download_verified(
                source,
                vault_path,
                timeout_seconds=timeout_seconds,
            )
        except httpx.HTTPStatusError as error:
            status = error.response.status_code
            if status < HTTP_SERVER_ERROR_MINIMUM and status != HTTP_TOO_MANY_REQUESTS:
                raise
        except httpx.TransportError:
            if attempt == DOWNLOAD_ATTEMPTS:
                raise
        if attempt == DOWNLOAD_ATTEMPTS:
            raise RuntimeError(f"verified download failed after retries: {source.id}")
        await asyncio.sleep(2 ** (attempt - 1))
    raise AssertionError("download retry loop did not return or raise")


class MultiArtifactSummary(FrozenModel):
    """Report one complete or reused multi-input aggregate."""

    aggregate_source_id: str
    aggregate_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    input_artifacts: int = Field(gt=1)
    accepted: int = Field(ge=0)
    quarantined: int = Field(ge=0)
    duplicates: int = Field(ge=0)
    reused_attempt: bool
    elapsed_seconds: float = Field(ge=0)


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _generated_source(
    sources: tuple[DownloadSource, ...],
    downloads: tuple[DownloadResult, ...],
    adapter: SourceAdapter,
    options: MultiArtifactOptions,
) -> tuple[DownloadSource, DownloadResult]:
    payload = json.dumps(
        {
            "adapter": {"key": adapter.key, "version": adapter.version},
            "configuration_sha256": options.configuration_sha256,
            "inputs": [
                {
                    "source_id": source.id,
                    "snapshot": source.snapshot,
                    "sha256": download.sha256,
                    "byte_size": download.byte_size,
                }
                for source, download in zip(sources, downloads, strict=True)
            ],
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    digest = _sha256(payload)
    staging = options.vault_path / "staging" / f"{options.aggregate_source_id}.json"
    staging.parent.mkdir(parents=True, exist_ok=True)
    staging.write_bytes(payload)
    stored = LocalObjectStore(options.vault_path / "raw" / "sha256").push(
        staging,
        ObjectKey(value=digest),
    )
    staging.unlink()
    path = options.vault_path / "raw" / "sha256" / digest
    first = sources[0]
    source = DownloadSource(
        id=options.aggregate_source_id,
        adapter=adapter.key,
        snapshot=f"joint:{digest}",
        url=HttpUrl(f"https://example.invalid/{options.aggregate_source_id}.json"),
        discovery_url=first.discovery_url,
        expected_content_type="application/json",
        compression="none",
        expected_bytes=stored.byte_size,
        checksum_algorithm="sha256",
        checksum=digest,
        data_license=first.data_license,
        license_url=first.license_url,
        rights_classification=first.rights_classification,
        local_only=any(item.local_only for item in sources),
        normalize=all(item.normalize for item in sources),
        local_search=all(item.local_search for item in sources),
        display=all(item.display for item in sources),
        embed=all(item.embed for item in sources),
        train=all(item.train for item in sources),
        export_metadata=all(item.export_metadata for item in sources),
    )
    return source, DownloadResult(
        path=path,
        sha256=digest,
        byte_size=stored.byte_size,
        resumed_from=stored.byte_size if stored.reused else 0,
        reused=stored.reused,
    )


def _input_provenance(
    connection: sqlite3.Connection,
    sources: tuple[DownloadSource, ...],
    downloads: tuple[DownloadResult, ...],
    adapter: SourceAdapter,
    options: MultiArtifactOptions,
) -> tuple[int, ...]:
    provenance_ids: list[int] = []
    for source, download in zip(sources, downloads, strict=True):
        pipeline_options = PipelineOptions(
            manifest_path=options.manifest_path,
            source_id=source.id,
            database_path=options.database_path,
            vault_path=options.vault_path,
            partition=DeterministicPartition(sha256_prefix=""),
            limits=options.limits,
            checkpoint_every=10_000,
        )
        context = register_verified_run(connection, source, download, adapter, pipeline_options)
        fingerprint = _sha256(f"multi-input\0{source.id}\0{download.sha256}".encode())
        connection.execute(
            """INSERT OR IGNORE INTO provenance_records
               (source_id, policy_id, snapshot_ref, artifact_sha256, record_fingerprint,
                parser_release_ref, ingest_attempt_ref, observed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))""",
            (
                context.source_id,
                context.policy_id,
                f"{source.id}:{source.snapshot}",
                download.sha256,
                fingerprint,
                context.parser_ref,
                context.attempt_ref,
            ),
        )
        row = connection.execute(
            """SELECT id FROM provenance_records
               WHERE source_id = ? AND snapshot_ref = ? AND record_fingerprint = ?""",
            (context.source_id, f"{source.id}:{source.snapshot}", fingerprint),
        ).fetchone()
        if row is None:
            raise RuntimeError("multi-input provenance could not be read back")
        provenance_ids.append(int(row[0]))
        if not context.reused:
            record_pipeline_event(
                connection,
                context.attempt_id,
                empty_pipeline_counters(),
                stage="complete",
                kind="succeeded",
            )
    return tuple(provenance_ids)


def _persist_joint(  # noqa: PLR0913, PLR0917
    sources: tuple[DownloadSource, ...],
    downloads: tuple[DownloadResult, ...],
    adapter: SourceAdapter,
    projectors: ProjectorRegistry,
    record_factory: RecordFactory,
    options: MultiArtifactOptions,
) -> MultiArtifactSummary:
    started = time.monotonic()
    generated_source, generated_download = _generated_source(sources, downloads, adapter, options)
    database = Database(options.database_path)
    database.initialize()
    pipeline_options = PipelineOptions(
        manifest_path=options.manifest_path,
        source_id=generated_source.id,
        database_path=options.database_path,
        vault_path=options.vault_path,
        partition=DeterministicPartition(sha256_prefix=""),
        limits=options.limits,
        checkpoint_every=options.limits.max_records,
    )
    counters = empty_pipeline_counters()
    with database.connect() as connection, connection:
        parent_provenance = _input_provenance(connection, sources, downloads, adapter, options)
        context = register_verified_run(
            connection, generated_source, generated_download, adapter, pipeline_options
        )
        if context.reused:
            return MultiArtifactSummary(
                aggregate_source_id=generated_source.id,
                aggregate_sha256=generated_download.sha256,
                input_artifacts=len(sources),
                accepted=0,
                quarantined=0,
                duplicates=0,
                reused_attempt=True,
                elapsed_seconds=time.monotonic() - started,
            )
        record_pipeline_event(
            connection, context.attempt_id, counters, stage="parse", kind="started"
        )
        for record in record_factory(downloads):
            counters["raw"] += 1
            counters["last_ordinal"] = record.ordinal
            duplicate = persist_pipeline_record(
                connection, generated_source, context, record, projectors
            )
            if isinstance(record, ParsedSourceRecord):
                counters["selected"] += 1
                counters["accepted"] += 1
                counters["duplicates"] += int(duplicate)
            elif isinstance(record, RejectedSourceRecord):
                counters["quarantined"] += 1
        connection.execute(
            """INSERT INTO derived_outputs
                   (output_kind, output_ref, content_sha256, policy_id, created_at)
                   VALUES ('multi_source_aggregate', ?, ?, ?,
                           strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))""",
            (generated_source.id, generated_download.sha256, context.policy_id),
        )
        output_id = connection.execute("SELECT last_insert_rowid()").fetchone()
        if output_id is None:
            raise RuntimeError("multi-input derived output could not be read back")
        connection.executemany(
            """INSERT INTO derivation_edges
                   (parent_kind, parent_ref, child_output_id) VALUES ('provenance', ?, ?)""",
            ((str(parent_id), int(output_id[0])) for parent_id in parent_provenance),
        )
        connection.execute(
            """INSERT INTO derived_output_events
                   (derived_output_id, event_kind, event_at, reason)
                   VALUES (?, 'created', strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
                           'verified multi-input aggregate')""",
            (int(output_id[0]),),
        )
        record_pipeline_event(
            connection, context.attempt_id, counters, stage="complete", kind="succeeded"
        )
    return MultiArtifactSummary(
        aggregate_source_id=generated_source.id,
        aggregate_sha256=generated_download.sha256,
        input_artifacts=len(sources),
        accepted=counters["accepted"],
        quarantined=counters["quarantined"],
        duplicates=counters["duplicates"],
        reused_attempt=False,
        elapsed_seconds=time.monotonic() - started,
    )


async def run_multi_artifact_pipeline(
    sources: tuple[DownloadSource, ...],
    adapter: SourceAdapter,
    projectors: ProjectorRegistry,
    record_factory: RecordFactory,
    options: MultiArtifactOptions,
) -> MultiArtifactSummary:
    """Verify every input concurrently and persist exactly one atomic aggregate."""
    if len(sources) < MINIMUM_INPUT_ARTIFACTS:
        raise ValueError("multi-artifact pipeline requires at least two sources")
    if len({source.id for source in sources}) != len(sources):
        raise ValueError("multi-artifact source IDs must be unique")
    if any(source.expected_bytes > options.limits.max_archive_bytes for source in sources):
        raise ValueError("multi-artifact input exceeds max_archive_bytes")

    async with asyncio.TaskGroup() as group:
        tasks = tuple(
            group.create_task(
                _download_with_retry(
                    source,
                    options.vault_path,
                    options.limits.timeout_seconds,
                )
            )
            for source in sources
        )
    downloads = tuple(task.result() for task in tasks)
    return await asyncio.to_thread(
        _persist_joint,
        sources,
        downloads,
        adapter,
        projectors,
        record_factory,
        options,
    )
