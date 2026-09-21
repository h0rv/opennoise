"""Verify and restore the raw source vault for one sealed release manifest."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
from contextlib import closing
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Final, Literal

from pydantic import Field, HttpUrl, model_validator

from opennoise.catalog.co_listens import ArtistCoListenProjector, ArtistCoListenRunProjector
from opennoise.catalog.entities import EntityProjector
from opennoise.catalog.registry import ProjectorRegistry
from opennoise.db import Database
from opennoise.models import FrozenModel
from opennoise.models.listenbrainz import JointListenArtifact, ListenBrainzAggregationConfig
from opennoise.models.pipeline import SourceLimits, SourceRecord
from opennoise.models.sources import DownloadResult, DownloadSource
from opennoise.pipeline.manifest import load_download_source
from opennoise.pipeline.multi_source import (
    MultiArtifactOptions,
    run_multi_artifact_pipeline_from_verified_downloads,
)
from opennoise.pipeline.release_manifest import RELEASE_MANIFEST_NAME, load_release_manifest
from opennoise.pipeline.runner import DeterministicPartition, PipelineOptions, run_source_pipeline
from opennoise.sources.listenbrainz import ListenBrainzIncrementalAdapter
from opennoise.sources.registry import AdapterRegistry
from opennoise.sources.wikidata import WikidataSourceAdapter
from opennoise.storage import ObjectKey, ObjectStore
from opennoise.types import Sha256  # noqa: TC001

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

_CHUNK_BYTES: Final = 1024 * 1024
_RAW_PREFIX: Final = "raw/sha256"
_WIKIDATA_SOURCE_PREFIX: Final = "wikidata_phase3_"
_LISTENBRAINZ_SOURCE_PREFIX: Final = "listenbrainz_incremental_"
_LISTENBRAINZ_JOINT_SOURCE_KEY: Final = "listenbrainz_joint_20260824_20260830"
_LISTENBRAINZ_DAILY_OBJECT_COUNT: Final = 7
_WIKIDATA_OBJECT_COUNT: Final = 54
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
    source_manifest_sha256: Sha256


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


class CandidateListenBrainzReplayReport(FrozenModel):
    """Explicitly uncertified replay record for the retained seven-day corpus."""

    revision: Literal["source-vault-listenbrainz-candidate-replay-v1"] = (
        "source-vault-listenbrainz-candidate-replay-v1"
    )
    release_id: str = Field(min_length=1, max_length=300)
    manifest_sha256: Sha256
    database_path: Path
    database_schema_version: int = Field(ge=1)
    certified_database: Literal[False] = False
    byte_identical_database_replay: Literal[False] = False
    configuration_sha256: Sha256
    sealed_joint_artifact_sha256: Sha256
    sealed_joint_artifact_byte_size: int = Field(ge=0)
    generated_joint_matches_sealed_artifact: Literal[True] = True
    historical_source_declarations_match: Literal[False] = False
    daily_objects: tuple[CandidateReplayObject, ...] = Field(
        min_length=_LISTENBRAINZ_DAILY_OBJECT_COUNT,
        max_length=_LISTENBRAINZ_DAILY_OBJECT_COUNT,
    )
    accepted_record_count: int = Field(ge=0)
    quarantined_record_count: int = Field(ge=0)
    blockers: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def check_daily_objects(self) -> CandidateListenBrainzReplayReport:
        """Require exactly the seven independent daily source objects."""
        if any(item.status != "ingested" for item in self.daily_objects):
            raise ValueError("candidate ListenBrainz daily objects must be ingested")
        keys = tuple(item.source_key for item in self.daily_objects)
        if len(set(keys)) != _LISTENBRAINZ_DAILY_OBJECT_COUNT or any(
            not key.startswith(_LISTENBRAINZ_SOURCE_PREFIX) for key in keys
        ):
            raise ValueError("candidate ListenBrainz replay requires seven unique daily objects")
        return self


class CandidateCombinedReplayReport(FrozenModel):
    """Receipt for one fresh, offline candidate containing both replayable inputs."""

    revision: Literal["source-vault-combined-candidate-replay-v1"] = (
        "source-vault-combined-candidate-replay-v1"
    )
    release_id: str = Field(min_length=1, max_length=300)
    manifest_sha256: Sha256
    database_path: Path
    database_schema_version: int = Field(ge=1)
    certified_database: Literal[False] = False
    byte_identical_database_replay: Literal[False] = False
    verified_object_count: int = Field(ge=1, le=128)
    wikidata_objects: tuple[CandidateReplayObject, ...] = Field(min_length=1, max_length=128)
    listenbrainz_daily_objects: tuple[CandidateReplayObject, ...] = Field(
        min_length=_LISTENBRAINZ_DAILY_OBJECT_COUNT,
        max_length=_LISTENBRAINZ_DAILY_OBJECT_COUNT,
    )
    sealed_joint_artifact_sha256: Sha256
    sealed_joint_artifact_byte_size: int = Field(ge=0)
    generated_joint_matches_sealed_artifact: Literal[True] = True
    accepted_record_count: int = Field(ge=0)
    quarantined_record_count: int = Field(ge=0)
    blockers: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def check_inputs(self) -> CandidateCombinedReplayReport:
        """Keep the combined receipt explicit about every replayed raw object."""
        if (
            self.verified_object_count
            != len(self.wikidata_objects) + len(self.listenbrainz_daily_objects) + 1
        ):
            raise ValueError("combined replay verified object count is inconsistent")
        if any(item.status != "ingested" for item in self.wikidata_objects):
            raise ValueError("combined replay Wikidata objects must be ingested")
        if any(item.status != "ingested" for item in self.listenbrainz_daily_objects):
            raise ValueError("combined replay ListenBrainz objects must be ingested")
        if any(
            not item.source_key.startswith(_WIKIDATA_SOURCE_PREFIX)
            for item in self.wikidata_objects
        ):
            raise ValueError("combined replay requires only Wikidata replay objects")
        if any(
            not item.source_key.startswith(_LISTENBRAINZ_SOURCE_PREFIX)
            for item in self.listenbrainz_daily_objects
        ):
            raise ValueError("combined replay requires seven ListenBrainz daily objects")
        return self


class HistoricalDeclarationReplayObject(FrozenModel):
    """One reconstructed pre-schema-expansion source declaration digest."""

    source_key: str = Field(min_length=1, max_length=300)
    expected_sha256: Sha256
    replayed_sha256: Sha256

    @model_validator(mode="after")
    def check_digest(self) -> HistoricalDeclarationReplayObject:
        """Require the reconstructed declaration to equal its sealed digest."""
        if self.expected_sha256 != self.replayed_sha256:
            raise ValueError("historical declaration digest does not replay")
        return self


class HistoricalDeclarationReplayReport(FrozenModel):
    """Timestamp-free proof that all historical source declarations can be rebuilt."""

    revision: Literal["phase3-historical-source-declarations-v1"] = (
        "phase3-historical-source-declarations-v1"
    )
    release_id: str = Field(min_length=1, max_length=300)
    manifest_sha256: Sha256
    pre_schema_fields_omitted: tuple[Literal["export_raw", "redistribute"], ...] = (
        "export_raw",
        "redistribute",
    )
    object_count: int = Field(ge=1, le=128)
    objects: tuple[HistoricalDeclarationReplayObject, ...] = Field(min_length=1, max_length=128)

    @model_validator(mode="after")
    def check_objects(self) -> HistoricalDeclarationReplayReport:
        """Keep the declaration receipt complete and unambiguous."""
        if self.object_count != len(self.objects):
            raise ValueError("historical declaration replay object count is inconsistent")
        if len({item.source_key for item in self.objects}) != len(self.objects):
            raise ValueError("historical declaration replay source keys must be unique")
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


def write_candidate_database_report(
    report: (
        CandidateDatabaseReplayReport
        | CandidateListenBrainzReplayReport
        | CandidateCombinedReplayReport
        | HistoricalDeclarationReplayReport
    ),
    path: Path,
) -> None:
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


def _require_verified_vault_objects(report: SourceVaultReplayReport, vault_path: Path) -> None:
    """Rehash each report-bound raw object immediately before offline replay."""
    for item in report.objects:
        path = _source_path(vault_path, item.artifact_sha256)
        if path.is_symlink() or not path.is_file():
            raise SourceVaultReplayError(f"source object is missing: {item.source_key}")
        _require_bytes(path, item.artifact_sha256, item.byte_size, item.source_key)


def _report_progress(progress: Callable[[str], None] | None, stage: str) -> None:
    """Emit optional human-facing timing state without affecting replay receipts."""
    if progress is not None:
        progress(stage)


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


def _historical_wikidata_source(item: ReleaseManifestReplayInput) -> DownloadSource:
    """Recreate the Phase 3 constructor retained in the historical ingest script."""
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
        local_only=False,
        normalize=True,
        local_search=True,
        display=True,
        embed=True,
        train=True,
        export_metadata=True,
    )


def _historical_declaration_sha256(source: DownloadSource) -> str:
    """Hash the exact pre-Phase-3 source model, before two later default fields."""
    return hashlib.sha256(
        source.model_dump_json(exclude={"export_raw", "redistribute"}).encode()
    ).hexdigest()


def replay_historical_source_declarations(
    manifest_path: Path, source_manifest_path: Path
) -> HistoricalDeclarationReplayReport:
    """Rebuild and verify all historical declaration hashes without raw ingestion."""
    resolved_manifest = manifest_path.resolve(strict=True)
    manifest_sha256, release_id, inputs = _replay_inputs(resolved_manifest)
    daily, sources = _candidate_listenbrainz_sources(
        inputs, source_manifest_path.resolve(strict=True)
    )
    daily_sources = {item.source_key: source for item, source in zip(daily, sources, strict=True)}
    replayed: list[HistoricalDeclarationReplayObject] = []
    for item in inputs:
        if item.source_key.startswith(_WIKIDATA_SOURCE_PREFIX):
            source = _historical_wikidata_source(item)
        elif item.source_key.startswith(_LISTENBRAINZ_SOURCE_PREFIX):
            source = daily_sources[item.source_key]
        elif item.source_key == _LISTENBRAINZ_JOINT_SOURCE_KEY:
            first = sources[0]
            source = DownloadSource(
                id=item.source_key,
                adapter=ListenBrainzIncrementalAdapter(_candidate_listenbrainz_config()).key,
                snapshot=item.snapshot_ref.removeprefix(f"{item.source_key}:"),
                url=HttpUrl(f"https://example.invalid/{item.source_key}.json"),
                discovery_url=first.discovery_url,
                expected_content_type="application/json",
                compression="none",
                expected_bytes=item.byte_size,
                checksum_algorithm="sha256",
                checksum=item.artifact_sha256,
                data_license=first.data_license,
                license_url=first.license_url,
                rights_classification=first.rights_classification,
                local_only=all(item.local_only for item in sources),
                normalize=all(item.normalize for item in sources),
                local_search=all(item.local_search for item in sources),
                display=all(item.display for item in sources),
                embed=all(item.embed for item in sources),
                train=all(item.train for item in sources),
                export_metadata=all(item.export_metadata for item in sources),
            )
        else:
            raise SourceVaultReplayError(f"unsupported historical declaration: {item.source_key}")
        replayed_sha256 = _historical_declaration_sha256(source)
        if replayed_sha256 != item.source_manifest_sha256:
            raise SourceVaultReplayError(
                f"historical declaration does not match manifest: {item.source_key}"
            )
        replayed.append(
            HistoricalDeclarationReplayObject(
                source_key=item.source_key,
                expected_sha256=item.source_manifest_sha256,
                replayed_sha256=replayed_sha256,
            )
        )
    return HistoricalDeclarationReplayReport(
        release_id=release_id,
        manifest_sha256=manifest_sha256,
        object_count=len(replayed),
        objects=tuple(replayed),
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


def _candidate_listenbrainz_config() -> ListenBrainzAggregationConfig:
    """Return the hash-bound joint settings retained by the Phase 3 receipt."""
    return ListenBrainzAggregationConfig(
        ordering="unordered_bounded",
        window_seconds=86_400,
        minimum_distinct_users=5,
        minimum_window_start=1_787_443_200,
        maximum_window_start=1_787_961_600,
        max_users_per_window=500_000,
        max_distinct_artists=500_000,
        max_pairs_per_window=2_000_000,
        max_active_windows=7,
        max_total_user_windows=3_500_000,
    )


def _listenbrainz_joint_input(
    inputs: tuple[ReleaseManifestReplayInput, ...], vault_path: Path
) -> ReleaseManifestReplayInput:
    """Read the tiny sealed joint receipt and reject configuration drift before scans."""
    matches = tuple(item for item in inputs if item.source_key == _LISTENBRAINZ_JOINT_SOURCE_KEY)
    if len(matches) != 1:
        raise SourceVaultReplayError("release manifest has no unique ListenBrainz joint artifact")
    joint = matches[0]
    path = _source_path(vault_path, joint.artifact_sha256)
    if path.is_symlink() or not path.is_file() or path.stat().st_size != joint.byte_size:
        raise SourceVaultReplayError(
            "sealed ListenBrainz joint artifact is missing or has wrong size"
        )
    _require_bytes(
        path,
        joint.artifact_sha256,
        joint.byte_size,
        "sealed ListenBrainz joint artifact",
    )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise SourceVaultReplayError("sealed ListenBrainz joint artifact is not JSON") from error
    expected_configuration = hashlib.sha256(
        _candidate_listenbrainz_config().model_dump_json().encode()
    ).hexdigest()
    if (
        not isinstance(payload, dict)
        or payload.get("configuration_sha256") != expected_configuration
    ):
        raise SourceVaultReplayError("sealed ListenBrainz joint artifact configuration differs")
    return joint


def _candidate_listenbrainz_sources(
    inputs: tuple[ReleaseManifestReplayInput, ...],
    source_manifest_path: Path,
) -> tuple[tuple[ReleaseManifestReplayInput, ...], tuple[DownloadSource, ...]]:
    """Bind current local declarations to the seven sealed daily raw objects.

    The historical declaration digests are retained in the release manifest but
    the current TOML declarations do not reproduce them.  This checks the
    immutable fields the local adapter needs without misrepresenting that fact.
    """
    daily = tuple(
        item for item in inputs if item.source_key.startswith(_LISTENBRAINZ_SOURCE_PREFIX)
    )
    if len(daily) != _LISTENBRAINZ_DAILY_OBJECT_COUNT:
        raise SourceVaultReplayError(
            "release manifest must retain exactly seven ListenBrainz dailies"
        )
    sources = tuple(load_download_source(source_manifest_path, item.source_key) for item in daily)
    for item, source in zip(daily, sources, strict=True):
        if (
            source.id,
            f"{source.id}:{source.snapshot}",
            source.verified_sha256(),
            source.expected_bytes,
        ) != (item.source_key, item.snapshot_ref, item.artifact_sha256, item.byte_size):
            raise SourceVaultReplayError(
                "current ListenBrainz declaration does not bind sealed raw object: "
                f"{item.source_key}"
            )
    return daily, sources


def _require_generated_joint_matches(
    joint: ReleaseManifestReplayInput, derived_vault: Path, aggregate_sha256: str
) -> None:
    """Require the deterministic candidate joint receipt to match its sealed byte object."""
    generated = _source_path(derived_vault, aggregate_sha256)
    if aggregate_sha256 != joint.artifact_sha256:
        raise SourceVaultReplayError(
            "generated ListenBrainz joint artifact differs from sealed receipt"
        )
    _require_bytes(
        generated,
        joint.artifact_sha256,
        joint.byte_size,
        "generated ListenBrainz joint artifact",
    )


async def _ingest_listenbrainz_candidate(  # noqa: PLR0913
    daily: tuple[ReleaseManifestReplayInput, ...],
    sources: tuple[DownloadSource, ...],
    *,
    vault_path: Path,
    candidate_database: Path,
    source_manifest_path: Path,
    derived_vault_path: Path,
) -> tuple[int, int, str]:
    """Run the seven retained dailies through the existing joint adapter offline."""
    downloads = tuple(
        DownloadResult(
            path=_source_path(vault_path, item.artifact_sha256),
            sha256=item.artifact_sha256,
            byte_size=item.byte_size,
            resumed_from=item.byte_size,
            reused=True,
        )
        for item in daily
    )
    artifacts = tuple(
        JointListenArtifact(
            source=source,
            path=download.path,
            sequence=int(source.snapshot.split("-", maxsplit=1)[0]),
            snapshot_date=date.fromisoformat(
                f"{source.snapshot[5:9]}-{source.snapshot[9:11]}-{source.snapshot[11:13]}"
            ),
        )
        for source, download in zip(sources, downloads, strict=True)
    )
    config = _candidate_listenbrainz_config()
    adapter = ListenBrainzIncrementalAdapter(config)
    limits = SourceLimits(
        max_archive_bytes=300_000_000,
        max_record_bytes=2_097_152,
        max_records=50_000_000,
        timeout_seconds=7_200,
    )

    def records(_: tuple[DownloadResult, ...]) -> Iterator[SourceRecord]:
        return adapter.iter_joint_records(artifacts, limits)

    summary = await run_multi_artifact_pipeline_from_verified_downloads(
        sources,
        downloads,
        adapter,
        ProjectorRegistry((ArtistCoListenProjector(), ArtistCoListenRunProjector())),
        records,
        MultiArtifactOptions(
            manifest_path=source_manifest_path,
            database_path=candidate_database,
            vault_path=derived_vault_path,
            aggregate_source_id=_LISTENBRAINZ_JOINT_SOURCE_KEY,
            configuration_sha256=hashlib.sha256(config.model_dump_json().encode()).hexdigest(),
            limits=limits,
        ),
    )
    return summary.accepted, summary.quarantined, summary.aggregate_sha256


def replay_listenbrainz_source_vault_to_candidate_database(
    report: SourceVaultReplayReport,
    vault_path: Path,
    candidate_database: Path,
    *,
    manifest_path: Path,
    source_manifest_path: Path,
) -> CandidateListenBrainzReplayReport:
    """Create an offline, non-certified candidate DB from seven retained dailies.

    The source vault and sealed database are read-only inputs.  The generated
    joint receipt must match the sealed joint artifact, but candidate database
    bytes and provenance are intentionally not historical certification claims.
    """
    resolved_manifest = manifest_path.resolve(strict=True)
    resolved_source_manifest = source_manifest_path.resolve(strict=True)
    manifest_sha256, release_id, inputs = _replay_inputs(resolved_manifest)
    _require_report_matches_manifest(report, manifest_sha256, release_id, inputs)
    if candidate_database.exists() or candidate_database.is_symlink():
        raise SourceVaultReplayError("candidate database must not already exist")
    joint = _listenbrainz_joint_input(inputs, vault_path)
    daily, sources = _candidate_listenbrainz_sources(inputs, resolved_source_manifest)
    candidate_database.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(
            prefix=f".{candidate_database.name}.listenbrainz-", dir=candidate_database.parent
        )
    )
    staging_database = staging / candidate_database.name
    derived_vault = staging / "derived-vault"
    try:
        accepted, quarantined, aggregate_sha256 = asyncio.run(
            _ingest_listenbrainz_candidate(
                daily,
                sources,
                vault_path=vault_path,
                candidate_database=staging_database,
                source_manifest_path=resolved_source_manifest,
                derived_vault_path=derived_vault,
            )
        )
        _require_generated_joint_matches(joint, derived_vault, aggregate_sha256)
        with closing(sqlite3.connect(staging_database)) as connection:
            connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            connection.execute("PRAGMA journal_mode = DELETE")
        staging_database.replace(candidate_database)
    except SourceVaultReplayError:
        raise
    except (OSError, ValueError, sqlite3.Error) as error:
        raise SourceVaultReplayError("candidate ListenBrainz replay failed") from error
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    with Database(candidate_database, read_only=True).connect() as connection:
        schema_row = connection.execute("PRAGMA user_version").fetchone()
    if schema_row is None:
        raise SourceVaultReplayError("candidate database has no schema version")
    return CandidateListenBrainzReplayReport(
        release_id=release_id,
        manifest_sha256=manifest_sha256,
        database_path=candidate_database,
        database_schema_version=int(schema_row[0]),
        configuration_sha256=hashlib.sha256(
            _candidate_listenbrainz_config().model_dump_json().encode()
        ).hexdigest(),
        sealed_joint_artifact_sha256=joint.artifact_sha256,
        sealed_joint_artifact_byte_size=joint.byte_size,
        daily_objects=tuple(
            CandidateReplayObject(
                source_key=item.source_key,
                artifact_sha256=item.artifact_sha256,
                byte_size=item.byte_size,
                status="ingested",
                reason="replayed offline with the sealed joint configuration",
            )
            for item in daily
        ),
        accepted_record_count=accepted,
        quarantined_record_count=quarantined,
        blockers=(
            (
                "current source declarations bind retained bytes but do not reproduce "
                "historical per-source declaration hashes"
            ),
            (
                "candidate provenance, timestamps, adapter build identity, and SQLite "
                "bytes are not historical byte-identical or certified"
            ),
        ),
    )


def replay_combined_source_vault_to_candidate_database(  # noqa: PLR0913
    report: SourceVaultReplayReport,
    vault_path: Path,
    candidate_database: Path,
    *,
    manifest_path: Path,
    source_manifest_path: Path,
    progress: Callable[[str], None] | None = None,
) -> CandidateCombinedReplayReport:
    """Replay all 54 Wikidata objects and seven ListenBrainz dailies into one DB.

    The sealed joint artifact is rehashed as part of the full vault receipt and
    then checked again against the newly derived joint artifact.  No existing
    database is opened for writing: both projectors write only to a fresh
    staging database which is atomically published to ``candidate_database``.
    """
    resolved_manifest = manifest_path.resolve(strict=True)
    resolved_source_manifest = source_manifest_path.resolve(strict=True)
    manifest_sha256, release_id, inputs = _replay_inputs(resolved_manifest)
    _require_report_matches_manifest(report, manifest_sha256, release_id, inputs)
    _report_progress(progress, "rehashing source-vault receipt")
    _require_verified_vault_objects(report, vault_path)
    _report_progress(progress, "source-vault receipt verified")
    if candidate_database.exists() or candidate_database.is_symlink():
        raise SourceVaultReplayError("candidate database must not already exist")
    wikidata = tuple(item for item in inputs if item.source_key.startswith(_WIKIDATA_SOURCE_PREFIX))
    if len(wikidata) != _WIKIDATA_OBJECT_COUNT:
        raise SourceVaultReplayError(
            f"release manifest must retain exactly {_WIKIDATA_OBJECT_COUNT} Wikidata objects"
        )
    joint = _listenbrainz_joint_input(inputs, vault_path)
    daily, sources = _candidate_listenbrainz_sources(inputs, resolved_source_manifest)
    candidate_database.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(
            prefix=f".{candidate_database.name}.combined-", dir=candidate_database.parent
        )
    )
    staging_database = staging / candidate_database.name
    derived_vault = staging / "derived-vault"
    try:
        _report_progress(progress, "replaying Wikidata objects")
        asyncio.run(
            _ingest_wikidata_objects(
                wikidata,
                manifest_path=resolved_manifest,
                vault_path=vault_path,
                database_path=staging_database,
            )
        )
        _report_progress(progress, "Wikidata replay complete; replaying ListenBrainz daily objects")
        accepted, quarantined, aggregate_sha256 = asyncio.run(
            _ingest_listenbrainz_candidate(
                daily,
                sources,
                vault_path=vault_path,
                candidate_database=staging_database,
                source_manifest_path=resolved_source_manifest,
                derived_vault_path=derived_vault,
            )
        )
        _require_generated_joint_matches(joint, derived_vault, aggregate_sha256)
        _report_progress(progress, "ListenBrainz replay complete; sealed joint receipt matched")
        with closing(sqlite3.connect(staging_database)) as connection:
            connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            connection.execute("PRAGMA journal_mode = DELETE")
        staging_database.replace(candidate_database)
        _report_progress(progress, "candidate database published")
    except SourceVaultReplayError:
        raise
    except (OSError, ValueError, sqlite3.Error) as error:
        raise SourceVaultReplayError("combined candidate database replay failed") from error
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    with Database(candidate_database, read_only=True).connect() as connection:
        schema_row = connection.execute("PRAGMA user_version").fetchone()
    if schema_row is None:
        raise SourceVaultReplayError("candidate database has no schema version")
    return CandidateCombinedReplayReport(
        release_id=release_id,
        manifest_sha256=manifest_sha256,
        database_path=candidate_database,
        database_schema_version=int(schema_row[0]),
        verified_object_count=len(report.objects),
        wikidata_objects=tuple(
            CandidateReplayObject(
                source_key=item.source_key,
                artifact_sha256=item.artifact_sha256,
                byte_size=item.byte_size,
                status="ingested",
                reason="replayed offline with wikidata_music_sparql_slice_v1",
            )
            for item in wikidata
        ),
        listenbrainz_daily_objects=tuple(
            CandidateReplayObject(
                source_key=item.source_key,
                artifact_sha256=item.artifact_sha256,
                byte_size=item.byte_size,
                status="ingested",
                reason="replayed offline with the sealed joint configuration",
            )
            for item in daily
        ),
        sealed_joint_artifact_sha256=joint.artifact_sha256,
        sealed_joint_artifact_byte_size=joint.byte_size,
        accepted_record_count=accepted,
        quarantined_record_count=quarantined,
        blockers=(
            (
                "current source declarations bind retained bytes but do not reproduce "
                "historical per-source declaration hashes"
            ),
            (
                "candidate provenance, timestamps, adapter build identity, and SQLite "
                "bytes are not historical byte-identical or certified"
            ),
        ),
    )
