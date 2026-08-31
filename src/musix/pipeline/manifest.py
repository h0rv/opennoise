"""Parse the pinned source manifest at the pipeline boundary."""

import tomllib
from pathlib import Path

from musix.models.sources import DataSourceManifest, DownloadSource


class SourceManifestError(ValueError):
    """Report a missing or duplicate source manifest entry."""


def load_download_source(path: Path, source_id: str) -> DownloadSource:
    """Load one download source by stable manifest ID."""
    manifest = DataSourceManifest.model_validate(tomllib.loads(path.read_text(encoding="utf-8")))
    matches = tuple(source for source in manifest.sources if source.id == source_id)
    if len(matches) != 1:
        raise SourceManifestError(f"expected exactly one source named {source_id!r}")
    return matches[0]
