"""Source adapter protocol and explicit registry."""

from collections.abc import Iterator
from pathlib import Path
from typing import Protocol

from musix.models.pipeline import SourceLimits, SourceRecord
from musix.models.sources import DownloadSource


class SourceAdapter(Protocol):
    """Separate source-specific parsing from shared ingestion lifecycle state."""

    @property
    def key(self) -> str:
        """Return the manifest adapter key."""
        ...

    @property
    def version(self) -> str:
        """Return the immutable projection contract version."""
        ...

    def supports(self, source: DownloadSource) -> bool:
        """Return whether this adapter accepts the manifest capabilities."""
        ...

    def iter_records(
        self,
        path: Path,
        limits: SourceLimits,
        *,
        start_after: int,
    ) -> Iterator[SourceRecord]:
        """Stream bounded typed records after a committed checkpoint."""
        ...


class AdapterRegistry:
    """Resolve adapters through explicit registration, never reflection."""

    def __init__(self, adapters: tuple[SourceAdapter, ...]) -> None:
        """Index a closed adapter set and reject duplicate keys."""
        indexed = {adapter.key: adapter for adapter in adapters}
        if len(indexed) != len(adapters):
            raise ValueError("source adapter keys must be unique")
        self._adapters = indexed

    def resolve(self, source: DownloadSource) -> SourceAdapter:
        """Resolve and capability-check the source's declared adapter."""
        adapter = self._adapters.get(source.adapter)
        if adapter is None:
            raise KeyError(f"no source adapter registered for {source.adapter!r}")
        if not adapter.supports(source):
            raise ValueError(f"adapter {adapter.key!r} does not support source {source.id!r}")
        return adapter
