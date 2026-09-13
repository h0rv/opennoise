"""Parse the pinned source manifest at the pipeline boundary."""

import tomllib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from opennoise.models.sources import DownloadSource
from opennoise.types import SourceId


class SourceManifestError(ValueError):
    """Report a missing or duplicate source manifest entry."""


_SHA256_HEX_LENGTH = 64


class SourceAcquisitionStatus(BaseModel):
    """State whether one declared source can be verified from the network."""

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    source_id: str = Field(min_length=1)
    state: Literal[
        "network_verifiable",
        "operator_supplied_local_only",
        "operator_supplied_unpinned",
    ]
    network_acquirable: bool
    portable_object_store_eligible: bool
    reason: str = Field(min_length=1)


class _SourceDeclaration(BaseModel):
    """Broad manifest entry used only to decide whether conversion is safe."""

    model_config = ConfigDict(frozen=True, strict=True, extra="ignore")

    id: SourceId
    adapter: str = Field(min_length=1)
    content_kind: Literal["metadata"] = "metadata"
    snapshot: str = Field(min_length=1)
    url: str = Field(min_length=1)
    discovery_url: str = Field(min_length=1)
    expected_content_type: str = Field(min_length=1)
    compression: str = Field(min_length=1)
    expected_bytes: int = Field(ge=0)
    checksum_algorithm: str = Field(min_length=1)
    checksum: str
    data_license: str = Field(min_length=1)
    license_url: str
    rights_classification: str = Field(min_length=1)
    local_only: bool
    normalize: bool
    local_search: bool
    display: bool
    embed: bool
    train: bool
    export_metadata: bool
    export_raw: bool = False
    redistribute: bool = False


class _SourceDeclarationManifest(BaseModel):
    """Parse all declared sources once before conversion to a downloader input."""

    model_config = ConfigDict(frozen=True, strict=True, extra="ignore")

    sources: tuple[_SourceDeclaration, ...]

    @field_validator("sources", mode="before")
    @classmethod
    def parse_toml_array(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value


def source_acquisition_status(path: Path, source_id: str) -> SourceAcquisitionStatus:
    """Explain whether a source has the fixed evidence needed for re-acquisition."""
    manifest = _SourceDeclarationManifest.model_validate(
        tomllib.loads(path.read_text(encoding="utf-8"))
    )
    matches = tuple(source for source in manifest.sources if source.id == source_id)
    if len(matches) != 1:
        raise SourceManifestError(f"expected exactly one source named {source_id!r}")
    source = matches[0]
    checksum = source.checksum.casefold()
    is_pinned = (
        source.checksum_algorithm == "sha256"
        and source.expected_bytes > 0
        and len(checksum) == _SHA256_HEX_LENGTH
        and all(character in "0123456789abcdef" for character in checksum)
    )
    if not is_pinned:
        return SourceAcquisitionStatus(
            source_id=source.id,
            state="operator_supplied_unpinned",
            network_acquirable=False,
            portable_object_store_eligible=False,
            reason=(
                "does not declare a positive byte count and SHA256 checksum; "
                "network acquisition is intentionally disabled"
            ),
        )
    if not str(source.url).startswith(("https://", "http://")):
        return SourceAcquisitionStatus(
            source_id=source.id,
            state="operator_supplied_local_only",
            network_acquirable=False,
            portable_object_store_eligible=False,
            reason="the source is pinned but does not declare an HTTP(S) acquisition URL",
        )
    return SourceAcquisitionStatus(
        source_id=source.id,
        state="network_verifiable",
        network_acquirable=True,
        portable_object_store_eligible=(
            not source.local_only and source.export_raw and source.redistribute
        ),
        reason="declares an HTTP(S) URL, positive byte count, and SHA256 checksum",
    )


def load_download_source(path: Path, source_id: str) -> DownloadSource:
    """Load one download source by stable manifest ID."""
    manifest = _SourceDeclarationManifest.model_validate(
        tomllib.loads(path.read_text(encoding="utf-8"))
    )
    matches = tuple(source for source in manifest.sources if source.id == source_id)
    if len(matches) != 1:
        raise SourceManifestError(f"expected exactly one source named {source_id!r}")
    return DownloadSource.model_validate(matches[0].model_dump())


def load_reacquirable_download_sources(
    path: Path, source_ids: tuple[str, ...]
) -> tuple[DownloadSource, ...]:
    """Load only selected sources whose immutable network verification is declared."""
    if not source_ids:
        raise SourceManifestError("select at least one source ID")
    if len(set(source_ids)) != len(source_ids):
        raise SourceManifestError("selected source IDs must be unique")
    statuses = tuple(source_acquisition_status(path, source_id) for source_id in source_ids)
    unavailable = tuple(status for status in statuses if status.state != "network_verifiable")
    if unavailable:
        names = ", ".join(status.source_id for status in unavailable)
        raise SourceManifestError(f"operator-supplied source cannot be reacquired: {names}")
    return tuple(load_download_source(path, source_id) for source_id in source_ids)
