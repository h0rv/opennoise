"""Parse the pinned source manifest at the pipeline boundary."""

import tomllib
from pathlib import Path

from pydantic import BaseModel, ConfigDict, field_validator

from musix.models.sources import DownloadSource


class SourceManifestError(ValueError):
    """Report a missing or duplicate source manifest entry."""


class _ManifestIndex(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True, extra="ignore")

    sources: tuple[dict[str, object], ...]

    @field_validator("sources", mode="before")
    @classmethod
    def parse_toml_array(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value


def load_download_source(path: Path, source_id: str) -> DownloadSource:
    """Load one download source by stable manifest ID."""
    manifest = _ManifestIndex.model_validate(tomllib.loads(path.read_text(encoding="utf-8")))
    matches = tuple(
        DownloadSource.model_validate(source)
        for source in manifest.sources
        if source.get("id") == source_id
    )
    if len(matches) != 1:
        raise SourceManifestError(f"expected exactly one source named {source_id!r}")
    return matches[0]
