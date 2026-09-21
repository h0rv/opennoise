"""Verify and restore the raw source vault for one sealed release manifest."""

from __future__ import annotations

import asyncio
import hashlib
import os
import shutil
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path
from typing import Final, Literal

from pydantic import Field, HttpUrl, model_validator

from opennoise.catalog.entities import EntityProjector
from opennoise.catalog.registry import ProjectorRegistry
from opennoise.db import Database
from opennoise.models import FrozenModel
from opennoise.models.pipeline import SourceLimits
from opennoise.models.sources import DownloadSource
from opennoise.pipeline.release_manifest import RELEASE_MANIFEST_NAME, load_release_manifest
from opennoise.pipeline.runner import DeterministicPartition, PipelineOptions, run_source_pipeline
from opennoise.sources.registry import AdapterRegistry
from opennoise.sources.wikidata import WikidataSourceAdapter
from opennoise.storage import ObjectKey, ObjectStore
from opennoise.types import Sha256  # noqa: TC001

_CHUNK_BYTES: Final = 1024 * 1024
_RAW_PREFIX: Final = "raw/sha256"
_WIKIDATA_SOURCE_PREFIX: Final = "wikidata_phase3_"
_WIKIDATA_DISCOVERY_URL: Final = "https://www.wikidata.org/wiki/Wikidata:Data_access"
_WIKIDATA_QUERY_URL: Final = "https://query.wikidata.org/sparql"


class SourceVaultReplayError(ValueError):
    """Report a manifest, vault, or restore boundary failure."""


class ReleaseManifestInput(FrozenModel):
    """The immutable fields needed to locate one manifest-bound source object."""

    source_key: str = Field(min_length=1, max_length=300)
    artifact_sha256: Sha256
    byte_size: int = Field(ge=0)


class ReleaseManifestReplayInput(ReleaseManifestInput):
    """One manifest input with the fields needed by an available local adapter."""

    snapshot_ref: str = Field(min_length=1, max_length=600)


class CandidateReplayObject(FrozenModel):
    """One raw object and the local replay decision made without network access."""

    source_key: str = Field(min_length=1, max_length=300)
    artifact_sha256: Sha256
    byte_size: int = Field(ge=0)
    status: Literal["ingested", "unsupported"]
    reason: str = Field(min_length=1)


class CandidateDatabaseReplayReport(FrozenModel):
    """Timestamp-free record of a bounded raw-vault replay into a new candidate DB."""

    revision: Literal["source-vault-candidate-database-replay-v1"] = (
        "source-vault-candidate-database-replay-v1"
    )
    release_id: str = Field(min_length=1, max_length=300)
    manifest_sha256: Sha256
    database_path: Path
    database_schema_version: int = Field(ge=1)
    certified_database: Literal[False] = False
    byte_identical_database_replay: Literal[False] = False
    ingested_object_count: int = Field(ge=0)
    unsupported_object_count: int = Field(ge=0)
    objects: tuple[CandidateReplayObject, ...] = Field(min_length=1, max_length=128)
    blockers: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def check_object_counts(self) -> CandidateDatabaseReplayReport:
        """Keep the explicit supported subset consistent with its per-object decisions."""
        ingested = sum(item.status == "ingested" for item in self.objects)
        unsupported = sum(item.status == "unsupported" for item in self.objects)
        if (self.ingested_object_count, self.unsupported_object_count) != (ingested, unsupported):
            raise ValueError("candidate replay object counts are inconsistent")
        if len({item.source_key for item in self.objects}) != len(self.objects):
            raise ValueError("candidate replay objects must have unique source keys")
        return self


class SourceVaultObject(FrozenModel):
    """One verified source object and its content-addressed object-store key."""

    source_key: str = Field(min_length=1, max_length=300)
    artifact_sha256: Sha256
    byte_size: int = Field(ge=0)
    object_key: ObjectKey


class SourceVaultReplayReport(FrozenModel):
    """Manifest-bound proof that every selected raw source object was verified."""

    revision: Literal["source-vault-replay-v1"] = "source-vault-replay-v1"
    release_id: str = Field(min_length=1, max_length=300)
    manifest_sha256: Sha256
    source_vault_layout: Literal["raw/sha256/<artifact_sha256>"] = "raw/sha256/<artifact_sha256>"
    object_count: int = Field(ge=0)
    total_byte_size: int = Field(ge=0)
    complete: bool
    objects: tuple[SourceVaultObject, ...] = Field(max_length=128)

    @model_validator(mode="after")
    def check_totals(self) -> SourceVaultReplayReport:
        """Ensure the report cannot self-assert complete with inconsistent totals."""
        if not self.complete or self.object_count != len(self.objects):
            raise ValueError("source vault replay report is incomplete")
        if self.object_count == 0 or len({item.artifact_sha256 for item in self.objects}) != (
            self.object_count
        ):
            raise ValueError("source vault replay objects must be unique")
        if any(
            item.object_key.value != f"{_RAW_PREFIX}/{item.artifact_sha256}"
            for item in self.objects
        ):
            raise ValueError("source vault object keys must be content-addressed raw objects")
        if self.total_byte_size != sum(item.byte_size for item in self.objects):
            raise ValueError("source vault replay byte total is inconsistent")
        return self


def _hash_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    byte_size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(_CHUNK_BYTES):
            digest.update(chunk)
            byte_size += len(chunk)
    return digest.hexdigest(), byte_size


def _manifest(path: Path) -> tuple[str, str, tuple[ReleaseManifestInput, ...]]:
    if path.name != RELEASE_MANIFEST_NAME:
        raise SourceVaultReplayError(f"manifest path must be named {RELEASE_MANIFEST_NAME}")
    try:
        payload = load_release_manifest(path.parent)
        release_id = str(payload["release_id"])
        raw_inputs = payload["inputs"]
        inputs = tuple(ReleaseManifestInput.model_validate(item) for item in raw_inputs)
    except (OSError, KeyError, TypeError, ValueError) as error:
        raise SourceVaultReplayError(f"invalid release manifest: {path}") from error
    if not inputs:
        raise SourceVaultReplayError("release manifest has no source inputs")
    source_keys = tuple(item.source_key for item in inputs)
    artifact_keys = tuple(item.artifact_sha256 for item in inputs)
    if len(set(source_keys)) != len(source_keys) or len(set(artifact_keys)) != len(artifact_keys):
        raise SourceVaultReplayError("release manifest source inputs must be unique")
    manifest_sha256, _ = _hash_file(path)
    return manifest_sha256, release_id, inputs


def _source_path(vault: Path, artifact_sha256: str) -> Path:
    return vault / "raw" / "sha256" / artifact_sha256


def _require_bytes(path: Path, expected_sha256: str, expected_size: int, label: str) -> None:
    actual_sha256, actual_size = _hash_file(path)
    if (actual_sha256, actual_size) != (expected_sha256, expected_size):
        raise SourceVaultReplayError(f"{label} does not match report")


def _require_object(store: ObjectStore, item: SourceVaultObject) -> None:
    metadata = store.inspect(item.object_key)
    if (metadata.sha256, metadata.byte_size) != (item.artifact_sha256, item.byte_size):
        raise SourceVaultReplayError(f"object store does not match report: {item.source_key}")


def verify_source_vault(
    manifest_path: Path,
    vault_path: Path,
    *,
    object_store: ObjectStore | None = None,
) -> SourceVaultReplayReport:
    """Hash every manifest input and optionally publish it to an object store."""
    manifest_sha256, release_id, inputs = _manifest(manifest_path.resolve(strict=True))
    verified: list[SourceVaultObject] = []
    total_byte_size = 0
    for item in inputs:
        path = _source_path(vault_path, item.artifact_sha256)
        if not path.is_file():
            raise SourceVaultReplayError(f"source object is missing: {path}")
        actual_sha256, actual_size = _hash_file(path)
        if (actual_sha256, actual_size) != (item.artifact_sha256, item.byte_size):
            raise SourceVaultReplayError(
                f"source object does not match manifest: {item.source_key}"
            )
        object_key = ObjectKey(value=f"{_RAW_PREFIX}/{item.artifact_sha256}")
        if object_store is not None:
            stored = object_store.push(path, object_key)
            if (stored.sha256, stored.byte_size) != (actual_sha256, actual_size):
                raise SourceVaultReplayError(
                    f"object store changed source bytes: {item.source_key}"
                )
        verified.append(
            SourceVaultObject(
                source_key=item.source_key,
                artifact_sha256=item.artifact_sha256,
                byte_size=item.byte_size,
                object_key=object_key,
            )
        )
        total_byte_size += item.byte_size
    return SourceVaultReplayReport(
        release_id=release_id,
        manifest_sha256=manifest_sha256,
        object_count=len(verified),
        total_byte_size=total_byte_size,
        complete=True,
        objects=tuple(verified),
    )


def restore_source_vault(
    report: SourceVaultReplayReport,
    object_store: ObjectStore,
    destination: Path,
    *,
    manifest_path: Path,
) -> None:
    """Restore a report into a new destination after rechecking its manifest binding."""
    manifest_sha256, release_id, inputs = _manifest(manifest_path.resolve(strict=True))
    if (manifest_sha256, release_id) != (report.manifest_sha256, report.release_id):
        raise SourceVaultReplayError("restore manifest does not match replay report")
    expected = {item.artifact_sha256: (item.source_key, item.byte_size) for item in inputs}
    if {
        item.artifact_sha256: (item.source_key, item.byte_size) for item in report.objects
    } != expected:
        raise SourceVaultReplayError("replay report objects do not match the release manifest")
    if destination.is_symlink() or destination.exists():
        raise SourceVaultReplayError("restore destination must not already exist")
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{destination.name}.restore-", dir=destination.parent))
    try:
        for item in report.objects:
            _require_object(object_store, item)
            target = staging / item.object_key.value
            object_store.pull(item.object_key, target)
            _require_bytes(target, item.artifact_sha256, item.byte_size, item.source_key)
        staging.replace(destination)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def write_report(report: SourceVaultReplayReport, path: Path) -> None:
    """Atomically write a JSON replay report."""
    _write_json_report(report.model_dump_json(indent=2), path)


def write_candidate_database_report(report: CandidateDatabaseReplayReport, path: Path) -> None:
    """Atomically write the explicit non-certification record for a candidate DB."""
    _write_json_report(report.model_dump_json(indent=2), path)


def _write_json_report(payload: str, path: Path) -> None:
    """Atomically write one already validated JSON report payload."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(payload)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def load_report(path: Path) -> SourceVaultReplayReport:
    """Parse a replay report at the CLI boundary."""
    try:
        return SourceVaultReplayReport.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise SourceVaultReplayError(f"invalid source-vault replay report: {path}") from error


def _replay_inputs(manifest_path: Path) -> tuple[str, str, tuple[ReleaseManifestReplayInput, ...]]:
    """Load the manifest fields required to replay only explicitly supported objects."""
    manifest_sha256, release_id, _ = _manifest(manifest_path)
    try:
        payload = load_release_manifest(manifest_path.parent)
        inputs = tuple(
            ReleaseManifestReplayInput.model_validate(item) for item in payload["inputs"]
        )
    except (KeyError, TypeError, ValueError) as error:
        raise SourceVaultReplayError(
            f"invalid replay fields in release manifest: {manifest_path}"
        ) from error
    return manifest_sha256, release_id, inputs


def _require_report_matches_manifest(
    report: SourceVaultReplayReport,
    manifest_sha256: str,
    release_id: str,
    inputs: tuple[ReleaseManifestReplayInput, ...],
) -> None:
    """Reject a report that was not produced for precisely this sealed input list."""
    expected = {(item.source_key, item.artifact_sha256, item.byte_size) for item in inputs}
    actual = {(item.source_key, item.artifact_sha256, item.byte_size) for item in report.objects}
    if (report.manifest_sha256, report.release_id) != (
        manifest_sha256,
        release_id,
    ) or actual != expected:
        raise SourceVaultReplayError("source-vault report does not match the release manifest")


def _offline_wikidata_source(item: ReleaseManifestReplayInput) -> DownloadSource:
    """Make the minimum typed adapter declaration from a sealed Wikidata raw object.

    The release manifest does not retain the original downloader declaration.  This
    declaration is deliberately local-only orchestration metadata and is never used
    to certify the candidate database against the historic release.
    """
    source_prefix = f"{item.source_key}:"
    if not item.snapshot_ref.startswith(source_prefix):
        raise SourceVaultReplayError(f"Wikidata snapshot does not belong to {item.source_key}")
    return DownloadSource(
        id=item.source_key,
        adapter="wikidata_music_sparql_slice_v1",
        snapshot=item.snapshot_ref.removeprefix(source_prefix),
        url=HttpUrl(_WIKIDATA_QUERY_URL),
        discovery_url=HttpUrl(_WIKIDATA_DISCOVERY_URL),
        expected_content_type="application/sparql-results+json",
        compression="none",
        expected_bytes=item.byte_size,
        checksum_algorithm="sha256",
        checksum=item.artifact_sha256,
        data_license="CC0-1.0",
        license_url="https://www.wikidata.org/wiki/Wikidata:Licensing",
        rights_classification="public_domain",
        local_only=True,
        normalize=True,
        local_search=True,
        display=False,
        embed=False,
        train=False,
        export_metadata=False,
    )


async def _ingest_wikidata_objects(
    inputs: tuple[ReleaseManifestReplayInput, ...],
    *,
    manifest_path: Path,
    vault_path: Path,
    database_path: Path,
) -> None:
    """Replay supported SPARQL objects from already verified raw vault paths only."""
    adapters = AdapterRegistry((WikidataSourceAdapter(),))
    projectors = ProjectorRegistry((EntityProjector(),))
    for item in inputs:
        source = _offline_wikidata_source(item)
        await run_source_pipeline(
            source,
            adapters,
            projectors,
            PipelineOptions(
                manifest_path=manifest_path,
                source_id=source.id,
                database_path=database_path,
                vault_path=vault_path,
                partition=DeterministicPartition(sha256_prefix=""),
                limits=SourceLimits(max_archive_bytes=item.byte_size),
                offline=True,
            ),
        )


def replay_source_vault_to_candidate_database(
    report: SourceVaultReplayReport,
    vault_path: Path,
    candidate_database: Path,
    *,
    manifest_path: Path,
) -> CandidateDatabaseReplayReport:
    """Build a fresh, explicitly uncertified SQLite candidate from supported raw objects.

    This routine never requests the network.  It accepts only a report that already
    proves all manifest objects in ``vault_path`` and writes to a path that did not
    exist when the replay began.  The sealed release cache is intentionally neither
    read nor overwritten.
    """
    resolved_manifest = manifest_path.resolve(strict=True)
    manifest_sha256, release_id, inputs = _replay_inputs(resolved_manifest)
    _require_report_matches_manifest(report, manifest_sha256, release_id, inputs)
    if candidate_database.exists() or candidate_database.is_symlink():
        raise SourceVaultReplayError("candidate database must not already exist")
    supported = tuple(
        item for item in inputs if item.source_key.startswith(_WIKIDATA_SOURCE_PREFIX)
    )
    unsupported = tuple(item for item in inputs if item not in supported)
    if not supported:
        raise SourceVaultReplayError("release manifest has no supported local raw-source adapters")
    candidate_database.parent.mkdir(parents=True, exist_ok=True)
    staging_directory = Path(
        tempfile.mkdtemp(
            prefix=f".{candidate_database.name}.replay-", dir=candidate_database.parent
        )
    )
    staging_database = staging_directory / candidate_database.name
    try:
        asyncio.run(
            _ingest_wikidata_objects(
                supported,
                manifest_path=resolved_manifest,
                vault_path=vault_path,
                database_path=staging_database,
            )
        )
        with closing(sqlite3.connect(staging_database)) as connection:
            connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            connection.execute("PRAGMA journal_mode = DELETE")
        staging_database.replace(candidate_database)
    except SourceVaultReplayError:
        raise
    except (OSError, ValueError, sqlite3.Error) as error:
        raise SourceVaultReplayError("candidate database replay failed") from error
    finally:
        shutil.rmtree(staging_directory, ignore_errors=True)
    objects = tuple(
        CandidateReplayObject(
            source_key=item.source_key,
            artifact_sha256=item.artifact_sha256,
            byte_size=item.byte_size,
            status="ingested",
            reason="replayed offline with wikidata_music_sparql_slice_v1",
        )
        for item in supported
    ) + tuple(
        CandidateReplayObject(
            source_key=item.source_key,
            artifact_sha256=item.artifact_sha256,
            byte_size=item.byte_size,
            status="unsupported",
            reason="no manifest-bound local replay adapter is available for ListenBrainz inputs",
        )
        for item in unsupported
    )
    with Database(candidate_database, read_only=True).connect() as connection:
        schema_row = connection.execute("PRAGMA user_version").fetchone()
    if schema_row is None:
        raise SourceVaultReplayError("candidate database has no schema version")
    return CandidateDatabaseReplayReport(
        release_id=release_id,
        manifest_sha256=manifest_sha256,
        database_path=candidate_database,
        database_schema_version=int(schema_row[0]),
        ingested_object_count=len(supported),
        unsupported_object_count=len(unsupported),
        objects=objects,
        blockers=(
            (
                "the Phase 3 release manifest does not retain the original per-source downloader "
                "declarations, so source_manifest_sha256 values cannot be reproduced"
            ),
            (
                "the seven ListenBrainz incrementals and their generated joint artifact require "
                "their historical joint aggregation configuration and adapter provenance"
            ),
            (
                "the current catalog schema and ingestion timestamps differ from the sealed "
                "Phase 3 "
                "cache, so this candidate is not byte-identical or certified"
            ),
        ),
    )
