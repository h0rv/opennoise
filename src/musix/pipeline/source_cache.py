"""Acquire and replay a bounded, metadata-only source cache.

The cache is deliberately separate from derived releases.  It retains exact,
pinned public input bytes in an :class:`~musix.storage.ObjectStore`, then
publishes a deterministic receipt that can restore those bytes without a
network request.  It never parses source records and never accepts audio.
"""

import asyncio
import hashlib
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, model_validator

from musix.clients.downloads import download_verified
from musix.models.sources import DownloadResult, DownloadSource
from musix.storage import LocalObjectStore, ObjectKey, ObjectStore, ObjectWrite
from musix.types import Sha256, SourceId

_REVISION = "source-cache-receipt-v1"
_ARTIFACT_PREFIX = "source-artifacts/sha256"
_RECEIPT_PREFIX = "source-cache-receipts/sha256"


class SourceCacheError(RuntimeError):
    """Report a cache acquisition or replay invariant failure."""


type SourceCacheScope = Literal["local_vault", "portable_object_store"]


class _FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")


class SourceCacheLimits(_FrozenModel):
    """Bound one explicit source-cache acquisition invocation."""

    max_sources: int = Field(default=8, gt=0)
    max_total_bytes: int = Field(default=128 * 1024 * 1024, gt=0)
    max_concurrency: int = Field(default=2, gt=0, le=8)
    timeout_seconds: float = Field(default=120.0, gt=0.0, le=3600.0)


DEFAULT_SOURCE_CACHE_LIMITS = SourceCacheLimits()


class SourceCacheAcquisition(_FrozenModel):
    """Bind the immutable selection context for one raw-source cache acquisition."""

    declared_manifest_sha256: Sha256
    work_directory: Path
    limits: SourceCacheLimits = DEFAULT_SOURCE_CACHE_LIMITS
    storage_scope: SourceCacheScope = "local_vault"


class SourceCacheEntry(_FrozenModel):
    """One declared source and its immutable cached object."""

    source_id: SourceId
    adapter: str = Field(min_length=1)
    snapshot: str = Field(min_length=1)
    original_url: str = Field(min_length=1)
    discovery_url: str = Field(min_length=1)
    expected_content_type: str = Field(min_length=1)
    expected_bytes: int = Field(gt=0)
    sha256: Sha256
    data_license: str = Field(min_length=1)
    license_url: str
    rights_classification: str = Field(min_length=1)
    local_only: bool
    portable_object_store_eligible: bool
    object_key: ObjectKey

    @model_validator(mode="after")
    def content_address_is_pinned(self) -> "SourceCacheEntry":
        """Require every stored object key to name the source's pinned digest."""
        expected_key = f"{_ARTIFACT_PREFIX}/{self.sha256}"
        if self.object_key.value != expected_key:
            raise ValueError("source cache object key must be its declared SHA256")
        return self


class SourceCacheReceipt(_FrozenModel):
    """Timestamp-free restore contract for one exact source manifest selection."""

    revision: Literal["source-cache-receipt-v1"] = _REVISION
    storage_scope: SourceCacheScope = "local_vault"
    declared_manifest_sha256: Sha256
    entries: tuple[SourceCacheEntry, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def ordered_unique_entries(self) -> "SourceCacheReceipt":
        """Keep receipt identity deterministic and preserve local-only custody boundaries."""
        source_ids = tuple(entry.source_id for entry in self.entries)
        if source_ids != tuple(sorted(source_ids)):
            raise ValueError("source cache entries must be sorted by source_id")
        if len(set(source_ids)) != len(source_ids):
            raise ValueError("source cache entries must have unique source IDs")
        if self.storage_scope == "portable_object_store" and any(
            not entry.portable_object_store_eligible for entry in self.entries
        ):
            raise ValueError("portable receipts cannot include local-only raw source artifacts")
        return self


class SourceCachePublication(_FrozenModel):
    """Content-addressed publication result for a restore receipt."""

    receipt: SourceCacheReceipt
    receipt_sha256: Sha256
    receipt_object: ObjectWrite

    @model_validator(mode="after")
    def receipt_object_matches_content(self) -> "SourceCachePublication":
        """Bind portable receipt storage to the exact receipt bytes."""
        expected_key = f"{_RECEIPT_PREFIX}/{self.receipt_sha256}.json"
        if self.receipt_object.key.value != expected_key:
            raise ValueError("receipt object key does not match receipt checksum")
        if self.receipt_object.sha256 != self.receipt_sha256:
            raise ValueError("receipt object checksum does not match receipt checksum")
        return self


class SourceCacheRestore(_FrozenModel):
    """One object restored to downloader-compatible vault layout."""

    source_id: SourceId
    destination: Path
    sha256: Sha256
    byte_size: int = Field(gt=0)


def _sha256_bytes(value: bytes) -> Sha256:
    return hashlib.sha256(value).hexdigest()


def _canonical_json(model: BaseModel) -> bytes:
    return (model.model_dump_json(indent=None) + "\n").encode("utf-8")


def receipt_sha256(receipt: SourceCacheReceipt) -> Sha256:
    """Hash the exact timestamp-free receipt bytes used for publication."""
    return _sha256_bytes(_canonical_json(receipt))


def _entry(source: DownloadSource) -> SourceCacheEntry:
    return SourceCacheEntry(
        source_id=source.id,
        adapter=source.adapter,
        snapshot=source.snapshot,
        original_url=str(source.url),
        discovery_url=str(source.discovery_url),
        expected_content_type=source.expected_content_type,
        expected_bytes=source.expected_bytes,
        sha256=source.verified_sha256(),
        data_license=source.data_license,
        license_url=source.license_url,
        rights_classification=source.rights_classification,
        local_only=source.local_only,
        portable_object_store_eligible=(
            not source.local_only and source.export_raw and source.redistribute
        ),
        object_key=ObjectKey(value=f"{_ARTIFACT_PREFIX}/{source.verified_sha256()}"),
    )


def verify_source_cache_receipt(
    receipt: SourceCacheReceipt,
    sources: Iterable[DownloadSource],
    *,
    declared_manifest_sha256: Sha256,
) -> None:
    """Fail closed unless a receipt names exactly the current pinned declarations."""
    selected = tuple(sorted(sources, key=lambda source: source.id))
    if receipt.declared_manifest_sha256 != declared_manifest_sha256:
        raise SourceCacheError("receipt was made from different manifest bytes")
    expected = tuple(_entry(source) for source in selected)
    if receipt.entries != expected:
        raise SourceCacheError("receipt entries do not exactly match selected source declarations")


def _validated_sources(
    sources: Iterable[DownloadSource],
    limits: SourceCacheLimits,
    storage_scope: SourceCacheScope,
) -> tuple[DownloadSource, ...]:
    selected = tuple(sorted(sources, key=lambda source: source.id))
    ids = tuple(source.id for source in selected)
    if not selected:
        raise SourceCacheError("select at least one declared source")
    if len(selected) > limits.max_sources:
        raise SourceCacheError("selected source count exceeds source cache limit")
    if len(set(ids)) != len(ids):
        raise SourceCacheError("selected source IDs must be unique")
    total_bytes = sum(source.expected_bytes for source in selected)
    if total_bytes > limits.max_total_bytes:
        raise SourceCacheError("declared source bytes exceed source cache limit")
    for source in selected:
        source.verified_sha256()
    if storage_scope == "portable_object_store" and any(
        not _entry(source).portable_object_store_eligible for source in selected
    ):
        raise SourceCacheError("portable object stores cannot receive local-only raw source bytes")
    return selected


async def _acquire_entry(
    source: DownloadSource,
    *,
    runtime: "_AcquisitionRuntime",
) -> SourceCacheEntry:
    async with runtime.semaphore:
        downloaded = await download_verified(
            source,
            runtime.acquisition.work_directory,
            timeout_seconds=runtime.acquisition.limits.timeout_seconds,
            client=runtime.client,
        )
    entry = _entry(source)
    object_write = await asyncio.to_thread(runtime.store.push, downloaded.path, entry.object_key)
    if object_write.sha256 != entry.sha256 or object_write.byte_size != entry.expected_bytes:
        raise SourceCacheError("object store changed a verified source artifact")
    return entry


@dataclass(frozen=True, slots=True)
class _AcquisitionRuntime:
    """Trusted runtime-only collaborators for the structured acquisition task group."""

    acquisition: SourceCacheAcquisition
    store: ObjectStore
    client: httpx.AsyncClient
    semaphore: asyncio.Semaphore


async def acquire_source_cache(
    sources: Iterable[DownloadSource],
    *,
    acquisition: SourceCacheAcquisition,
    store: ObjectStore,
    client: httpx.AsyncClient | None = None,
) -> SourceCacheReceipt:
    """Fetch declared public metadata and retain every byte under its SHA256 key."""
    selected = _validated_sources(sources, acquisition.limits, acquisition.storage_scope)
    if acquisition.storage_scope == "local_vault" and not isinstance(store, LocalObjectStore):
        raise SourceCacheError("local-only acquisition requires LocalObjectStore")
    await asyncio.to_thread(acquisition.work_directory.mkdir, parents=True, exist_ok=True)
    owns_client = client is None
    http_client = client or httpx.AsyncClient(
        follow_redirects=True,
        timeout=httpx.Timeout(acquisition.limits.timeout_seconds),
        headers={"User-Agent": "musix/0.1 (bounded metadata cache acquisition)"},
    )
    runtime = _AcquisitionRuntime(
        acquisition=acquisition,
        store=store,
        client=http_client,
        semaphore=asyncio.Semaphore(acquisition.limits.max_concurrency),
    )
    try:
        async with asyncio.TaskGroup() as group:
            tasks = [
                group.create_task(_acquire_entry(source, runtime=runtime)) for source in selected
            ]
        entries = tuple(
            sorted((task.result() for task in tasks), key=lambda entry: entry.source_id)
        )
        return SourceCacheReceipt(
            storage_scope=acquisition.storage_scope,
            declared_manifest_sha256=acquisition.declared_manifest_sha256,
            entries=entries,
        )
    finally:
        if owns_client:
            await http_client.aclose()


def publish_source_cache_receipt(
    receipt: SourceCacheReceipt,
    *,
    output: Path,
    store: ObjectStore,
) -> SourceCachePublication:
    """Write and custody a deterministic receipt without putting raw input in Git."""
    if receipt.storage_scope != "portable_object_store":
        raise SourceCacheError(
            "local-vault receipts cannot be published to a portable object store"
        )
    payload = _canonical_json(receipt)
    digest = _sha256_bytes(payload)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(payload)
    object_write = store.push(
        output,
        ObjectKey(value=f"{_RECEIPT_PREFIX}/{digest}.json"),
    )
    return SourceCachePublication(
        receipt=receipt,
        receipt_sha256=digest,
        receipt_object=object_write,
    )


def write_source_cache_receipt(receipt: SourceCacheReceipt, *, output: Path) -> Sha256:
    """Write a deterministic local receipt for a local-only source cache."""
    payload = _canonical_json(receipt)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(payload)
    return _sha256_bytes(payload)


def load_source_cache_receipt(path: Path) -> SourceCacheReceipt:
    """Parse one locally supplied receipt before attempting an offline restore."""
    return SourceCacheReceipt.model_validate_json(path.read_bytes())


def _restore_entry(
    entry: SourceCacheEntry,
    *,
    destination_root: Path,
    store: ObjectStore,
) -> SourceCacheRestore:
    destination = destination_root / "raw" / "sha256" / entry.sha256
    object_read = store.pull(entry.object_key, destination)
    if object_read.sha256 != entry.sha256 or object_read.byte_size != entry.expected_bytes:
        raise SourceCacheError("restored source artifact differs from its receipt")
    return SourceCacheRestore(
        source_id=entry.source_id,
        destination=destination,
        sha256=object_read.sha256,
        byte_size=object_read.byte_size,
    )


async def restore_source_cache(
    receipt: SourceCacheReceipt,
    *,
    destination_root: Path,
    store: ObjectStore,
    max_concurrency: int = 2,
) -> tuple[SourceCacheRestore, ...]:
    """Restore all receipt objects without network access and verify every byte."""
    if max_concurrency <= 0:
        raise ValueError("max_concurrency must be positive")
    if receipt.storage_scope == "local_vault" and not isinstance(store, LocalObjectStore):
        raise SourceCacheError("local-vault receipts require LocalObjectStore")
    await asyncio.to_thread(destination_root.mkdir, parents=True, exist_ok=True)
    semaphore = asyncio.Semaphore(max_concurrency)

    async def restore(entry: SourceCacheEntry) -> SourceCacheRestore:
        async with semaphore:
            return await asyncio.to_thread(
                _restore_entry,
                entry,
                destination_root=destination_root,
                store=store,
            )

    async with asyncio.TaskGroup() as group:
        tasks = [group.create_task(restore(entry)) for entry in receipt.entries]
    return tuple(sorted((task.result() for task in tasks), key=lambda item: item.source_id))


def download_result_from_restored(
    source: DownloadSource,
    restored: SourceCacheRestore,
) -> DownloadResult:
    """Adapt verified offline cache bytes to the existing source-pipeline contract."""
    if source.id != restored.source_id:
        raise SourceCacheError("source and restored cache entry do not match")
    if source.verified_sha256() != restored.sha256 or source.expected_bytes != restored.byte_size:
        raise SourceCacheError("current source declaration does not match restored cache bytes")
    return DownloadResult(
        path=restored.destination,
        sha256=restored.sha256,
        byte_size=restored.byte_size,
        resumed_from=restored.byte_size,
        reused=True,
    )
