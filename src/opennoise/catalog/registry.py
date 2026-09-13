"""Explicit catalog projector protocol and registry."""

import sqlite3
from typing import Protocol

from opennoise.models.catalog import CatalogProjection, ProjectionResult


class CatalogProjector(Protocol):
    """Persist one common projection without owning pipeline lifecycle state."""

    @property
    def key(self) -> str:
        """Return the projection discriminant accepted by this projector."""
        ...

    def persist(
        self,
        connection: sqlite3.Connection,
        projection: CatalogProjection,
        *,
        provenance_id: int,
        policy_id: int,
    ) -> ProjectionResult:
        """Persist catalog claims using pipeline-provided provenance."""
        ...


class ProjectorRegistry:
    """Resolve projectors explicitly by projection discriminant."""

    def __init__(self, projectors: tuple[CatalogProjector, ...]) -> None:
        """Index a closed projector set and reject duplicate keys."""
        indexed = {projector.key: projector for projector in projectors}
        if len(indexed) != len(projectors):
            raise ValueError("catalog projector keys must be unique")
        self._projectors = indexed

    def resolve(self, projection: CatalogProjection) -> CatalogProjector:
        """Return the projector matching a typed projection."""
        projector = self._projectors.get(projection.projection_kind)
        if projector is None:
            raise KeyError(f"no catalog projector for {projection.projection_kind!r}")
        return projector
