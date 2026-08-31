"""Strict source manifest and verified artifact models."""

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator

from musix.types import Sha256, SourceId


class _FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")


class DownloadSource(BaseModel):
    """Parse the manifest fields required for a verified download."""

    model_config = ConfigDict(frozen=True, strict=True, extra="ignore")

    id: SourceId
    adapter: str = Field(min_length=1)
    snapshot: str = Field(min_length=1)
    url: HttpUrl
    discovery_url: HttpUrl
    expected_content_type: str = Field(min_length=1)
    compression: str = Field(min_length=1)
    expected_bytes: int = Field(gt=0)
    checksum_algorithm: str
    checksum: Sha256
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

    def verified_sha256(self) -> Sha256:
        """Return the checksum only for the supported digest algorithm."""
        if self.checksum_algorithm != "sha256":
            raise ValueError(f"source {self.id} does not declare SHA256")
        return self.checksum


class DataSourceManifest(_FrozenModel):
    """Parse the source collection without leaking untyped TOML dictionaries."""

    sources: tuple[DownloadSource, ...]

    model_config = ConfigDict(frozen=True, strict=True, extra="ignore")

    @field_validator("sources", mode="before")
    @classmethod
    def parse_toml_array(cls, value: object) -> object:
        """Freeze TOML's mutable array representation at the boundary."""
        return tuple(value) if isinstance(value, list) else value


class DownloadResult(_FrozenModel):
    """Describe a verified content-addressed vault object."""

    path: Path
    sha256: Sha256
    byte_size: int
    resumed_from: int
    reused: bool
