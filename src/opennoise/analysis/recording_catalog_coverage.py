"""Receipt-bound local comparison of an exact recording cohort to local catalogs."""

from __future__ import annotations

import stat
from pathlib import Path  # noqa: TC003  # Pydantic resolves this annotation at definition.
from typing import Literal

from pydantic import Field, model_validator

from opennoise.analysis.listenbrainz_recording_co_listen import (
    RecordingIdCohortArtifact,
    load_catalog_recording_ids,
    recording_id_set_sha256,
    sha256_file,
)
from opennoise.models import FrozenModel
from opennoise.types import Sha256  # noqa: TC001  # Pydantic resolves the alias at definition.

_MAXIMUM_LOCAL_CATALOGS = 8
_MAXIMUM_CATALOG_RECORDING_IDS = 100_000


class RecordingCatalogCoverageError(ValueError):
    """Report invalid exact catalog coverage comparison inputs."""


class LocalCatalogInput(FrozenModel):
    """Name one local SQLite catalog that will be read but never changed."""

    label: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,79}$")
    database_path: Path


class CatalogCoverage(FrozenModel):
    """One exact UUID intersection and every identity needed to replay it."""

    label: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,79}$")
    database_sha256: Sha256
    catalog_recording_id_set_sha256: Sha256
    catalog_recording_id_count: int = Field(ge=0)
    cohort_overlap_count: int = Field(ge=0)


class RecordingCatalogCoverageArtifact(FrozenModel):
    """Local-only catalog-readiness report that retains no recording IDs itself."""

    revision: Literal["recording-catalog-coverage-v1"] = "recording-catalog-coverage-v1"
    local_only: Literal[True] = True
    export_allowed: Literal[False] = False
    serving_allowed: Literal[False] = False
    cohort_source_artifact_sha256: Sha256
    cohort_recording_id_set_sha256: Sha256
    cohort_recording_id_count: int = Field(ge=0)
    catalogs: tuple[CatalogCoverage, ...] = Field(min_length=1)
    union_catalog_recording_id_count: int = Field(ge=0)
    union_catalog_overlap_count: int = Field(ge=0)

    @model_validator(mode="after")
    def require_unique_catalog_labels(self) -> RecordingCatalogCoverageArtifact:
        """Reject ambiguous or nondeterministically ordered catalog identities."""
        labels = tuple(item.label for item in self.catalogs)
        if labels != tuple(sorted(labels)) or len(labels) != len(set(labels)):
            raise ValueError("catalog coverage labels must be sorted and unique")
        return self


def assess_recording_catalog_coverage(
    cohort: RecordingIdCohortArtifact,
    catalogs: tuple[LocalCatalogInput, ...],
) -> RecordingCatalogCoverageArtifact:
    """Compare only exact MusicBrainz recording UUIDs across read-only SQLite catalogs."""
    if not catalogs:
        raise RecordingCatalogCoverageError("coverage comparison requires at least one catalog")
    if len(catalogs) > _MAXIMUM_LOCAL_CATALOGS:
        raise RecordingCatalogCoverageError("coverage comparison exceeds catalog limit")
    labels = tuple(item.label for item in catalogs)
    if len(labels) != len(set(labels)):
        raise RecordingCatalogCoverageError("coverage comparison repeats a catalog label")
    cohort_ids = frozenset(
        f"musicbrainz:recording:{recording_id}" for recording_id in cohort.recording_ids
    )
    rows: list[CatalogCoverage] = []
    union_catalog_ids: set[str] = set()
    for catalog in sorted(catalogs, key=lambda item: item.label):
        catalog_ids, database_sha256 = _read_stable_catalog(catalog)
        union_catalog_ids.update(catalog_ids)
        rows.append(
            CatalogCoverage(
                label=catalog.label,
                database_sha256=database_sha256,
                catalog_recording_id_set_sha256=recording_id_set_sha256(catalog_ids),
                catalog_recording_id_count=len(catalog_ids),
                cohort_overlap_count=len(cohort_ids & catalog_ids),
            )
        )
    return RecordingCatalogCoverageArtifact(
        cohort_source_artifact_sha256=cohort.source_artifact_sha256,
        cohort_recording_id_set_sha256=cohort.recording_id_set_sha256,
        cohort_recording_id_count=len(cohort.recording_ids),
        catalogs=tuple(rows),
        union_catalog_recording_id_count=len(union_catalog_ids),
        union_catalog_overlap_count=len(cohort_ids & union_catalog_ids),
    )


def _read_stable_catalog(catalog: LocalCatalogInput) -> tuple[frozenset[str], str]:
    """Read a regular local SQLite file only if its bytes stay stable across the query."""
    before = _regular_file_identity(catalog.database_path, catalog.label)
    before_sha256 = sha256_file(catalog.database_path)
    catalog_ids = load_catalog_recording_ids(catalog.database_path)
    if len(catalog_ids) > _MAXIMUM_CATALOG_RECORDING_IDS:
        raise RecordingCatalogCoverageError(f"catalog exceeds recording-ID limit: {catalog.label}")
    after = _regular_file_identity(catalog.database_path, catalog.label)
    after_sha256 = sha256_file(catalog.database_path)
    if before != after or before_sha256 != after_sha256:
        raise RecordingCatalogCoverageError(f"catalog changed during read: {catalog.label}")
    return catalog_ids, before_sha256


def _regular_file_identity(path: Path, label: str) -> tuple[int, int, int, int, int]:
    """Reject indirections and return the mutation-relevant identity of one catalog file."""
    try:
        metadata = path.lstat()
    except OSError as error:
        raise RecordingCatalogCoverageError(f"catalog does not exist: {label}") from error
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise RecordingCatalogCoverageError(f"catalog is not a regular file: {label}")
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )
