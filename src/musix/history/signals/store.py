"""Serve bounded H3 historical-map slices from one explicitly configured artifact."""

from __future__ import annotations

import asyncio
import json
from threading import Lock
from typing import TYPE_CHECKING, Literal

from pydantic import Field, ValidationError

from musix.models import FrozenModel
from musix.models.historical_signal import (
    HistoricalSignalHierarchyNode,
    HistoricalSignalLOD,
    HistoricalSignalNeighbor,
    HistoricalSignalNode,
    HistoricalSignalPublicationArtifact,
    HistoricalSignalTile,
)

if TYPE_CHECKING:
    from pathlib import Path

_MAX_NODES_PER_RESPONSE = 512
_MAX_NEIGHBORS_PER_RESPONSE = 50
_MAX_LOD_LEVEL = 3
_MAX_INITIAL_NODES = 24
_MAX_RESPONSE_BYTES = 256 * 1_024
_MICROGENRE_LEVEL = 2


class HistoricalSignalMapStoreError(RuntimeError):
    """Report a disabled, malformed, or unbounded historical-map request."""


class HistoricalSignalMapMetadata(FrozenModel):
    """Expose provenance and semantic-zoom counts without serializing the whole map."""

    revision: Literal["historical-signal-publication-v1"]
    source_signal_artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    h2_artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    h3_artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    node_count: int = Field(gt=0, le=20_000)
    lods: tuple[HistoricalSignalLOD, ...] = Field(min_length=4, max_length=4)


class HistoricalSignalMapApiResponse(FrozenModel):
    """Bounded node or tile slice with zero initial edges and explicit source identity."""

    source: Literal["historical-signal-artifact"] = "historical-signal-artifact"
    fallback: Literal[False] = False
    metadata: HistoricalSignalMapMetadata
    level: int = Field(ge=0, le=3)
    tile: HistoricalSignalTile | None = None
    hierarchy: tuple[HistoricalSignalHierarchyNode, ...] = Field(
        default=(), max_length=_MAX_NODES_PER_RESPONSE
    )
    nodes: tuple[HistoricalSignalNode, ...] = Field(max_length=_MAX_NODES_PER_RESPONSE)
    initial_edge_count: Literal[0] = 0


class HistoricalSignalNeighborApiResponse(FrozenModel):
    """Focused H3 membership similarity data, independently bounded from map tiles."""

    source: Literal["historical-signal-artifact"] = "historical-signal-artifact"
    fallback: Literal[False] = False
    metadata: HistoricalSignalMapMetadata
    genre_id: str = Field(min_length=1, max_length=200)
    neighbors: tuple[HistoricalSignalNeighbor, ...] = Field(max_length=_MAX_NEIGHBORS_PER_RESPONSE)


class HistoricalSignalMapStore:
    """Load and validate the sealed historical artifact once, then select bounded slices."""

    def __init__(self, path: Path | None) -> None:
        """Bind the separately configured local artifact path for this process lifetime."""
        self._path = path
        self._lock = Lock()
        self._loaded = False
        self._artifact: HistoricalSignalPublicationArtifact | None = None
        self._error: str | None = None
        self._node_by_id: dict[str, HistoricalSignalNode] = {}
        self._nodes_by_level: tuple[tuple[HistoricalSignalNode, ...], ...] = ()
        self._hierarchy_by_id: dict[str, HistoricalSignalHierarchyNode] = {}
        self._tiles_by_key: dict[tuple[int, int, int], HistoricalSignalTile] = {}
        self._neighbors_by_genre: dict[str, tuple[HistoricalSignalNeighbor, ...]] = {}

    @property
    def configured(self) -> bool:
        """Return whether the separate historical-map environment setting is present."""
        return self._path is not None

    async def start(self) -> None:
        """Preload the configured artifact off the event loop and fail startup if it is unsafe."""
        if not self.configured:
            return
        await asyncio.to_thread(self._require_artifact)

    def publication_artifact(self) -> HistoricalSignalPublicationArtifact | None:
        """Return the already-validated sealed artifact for other startup-only adapters."""
        return self._require_artifact()

    def response(  # noqa: C901, PLR0912 - one bounded public-slice state machine.
        self,
        *,
        level: int,
        column: int | None = None,
        row: int | None = None,
        parent_id: str | None = None,
    ) -> HistoricalSignalMapApiResponse | None:
        """Return one bounded LOD cohort or one bounded viewport tile, never all edges."""
        artifact = self._require_artifact()
        if artifact is None:
            return None
        if not 0 <= level <= _MAX_LOD_LEVEL:
            raise HistoricalSignalMapStoreError(
                "historical signal level must be between zero and three"
            )
        if (column is None) != (row is None):
            raise HistoricalSignalMapStoreError(
                "historical signal tile requires both column and row"
            )
        metadata = _metadata(artifact)
        if parent_id is not None:
            if column is not None or row is not None:
                raise HistoricalSignalMapStoreError(
                    "historical hierarchy focus cannot request a tile"
                )
            parent = self._hierarchy_by_id.get(parent_id)
            if parent is None:
                raise HistoricalSignalMapStoreError("historical hierarchy focus does not exist")
            expected_level = parent.level + 1
            if level != expected_level:
                raise HistoricalSignalMapStoreError(
                    "historical hierarchy focus level does not match"
                )
            if parent.level == _MICROGENRE_LEVEL:
                nodes = tuple(
                    node for node in self._node_by_id.values() if node.microgenre_id == parent_id
                )
                return _require_bounded_response(
                    HistoricalSignalMapApiResponse(metadata=metadata, level=level, nodes=nodes)
                )
            children = tuple(
                self._hierarchy_by_id[child_id]
                for child_id in parent.children_ids
                if child_id in self._hierarchy_by_id
            )
            return _require_bounded_response(
                HistoricalSignalMapApiResponse(
                    metadata=metadata, level=level, hierarchy=children, nodes=()
                )
            )
        if column is None or row is None:
            if level == 0:
                hierarchy = tuple(
                    item for item in self._hierarchy_by_id.values() if item.level == 0
                )
                if len(hierarchy) > _MAX_INITIAL_NODES:
                    raise HistoricalSignalMapStoreError(
                        "historical overview exceeds the 24-node cap"
                    )
                return _require_bounded_response(
                    HistoricalSignalMapApiResponse(
                        metadata=metadata, level=level, hierarchy=hierarchy, nodes=()
                    )
                )
            nodes = self._nodes_by_level[level]
            if len(nodes) > _MAX_NODES_PER_RESPONSE:
                raise HistoricalSignalMapStoreError(
                    "historical signal level exceeds the response cap; request a viewport tile"
                )
            return _require_bounded_response(
                HistoricalSignalMapApiResponse(metadata=metadata, level=level, nodes=nodes)
            )
        tile = self._tiles_by_key.get((level, column, row))
        if tile is None:
            raise HistoricalSignalMapStoreError("historical signal tile does not exist")
        if len(tile.node_ids) > _MAX_NODES_PER_RESPONSE:
            raise HistoricalSignalMapStoreError(
                "historical signal tile exceeds the 512-node response cap"
            )
        return _require_bounded_response(
            HistoricalSignalMapApiResponse(
                metadata=metadata,
                level=level,
                tile=tile,
                nodes=tuple(self._node_by_id[genre_id] for genre_id in tile.node_ids),
            )
        )

    def neighbors(self, genre_id: str) -> HistoricalSignalNeighborApiResponse | None:
        """Return the retained H3 kNN evidence for one requested genre only."""
        artifact = self._require_artifact()
        if artifact is None:
            return None
        if genre_id not in self._node_by_id:
            raise HistoricalSignalMapStoreError("historical signal genre does not exist")
        return HistoricalSignalNeighborApiResponse(
            metadata=_metadata(artifact),
            genre_id=genre_id,
            neighbors=self._neighbors_by_genre.get(genre_id, ())[:_MAX_NEIGHBORS_PER_RESPONSE],
        )

    def _require_artifact(self) -> HistoricalSignalPublicationArtifact | None:
        if not self.configured:
            return None
        with self._lock:
            self._load_once()
            if self._artifact is None:
                raise HistoricalSignalMapStoreError(
                    self._error or "historical signal map unavailable"
                )
            return self._artifact

    def _load_once(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        if self._path is None:
            return
        try:
            self._artifact = HistoricalSignalPublicationArtifact.model_validate_json(
                self._path.read_text(encoding="utf-8")
            )
            self._node_by_id = {node.genre_id: node for node in self._artifact.map.nodes}
            self._nodes_by_level = tuple(
                tuple(node for node in self._artifact.map.nodes if node.lod_min <= level)
                for level in range(_MAX_LOD_LEVEL + 1)
            )
            self._hierarchy_by_id = {
                item.hierarchy_id: item for item in getattr(self._artifact.map, "hierarchy", ())
            }
            self._tiles_by_key = {
                (tile.level, tile.column, tile.row): tile for tile in self._artifact.map.tiles
            }
            grouped_neighbors: dict[str, list[HistoricalSignalNeighbor]] = {}
            for edge in self._artifact.map.neighbors:
                grouped_neighbors.setdefault(edge.genre_id, []).append(edge)
            self._neighbors_by_genre = {
                genre_id: tuple(edges) for genre_id, edges in grouped_neighbors.items()
            }
        except (OSError, ValidationError, ValueError) as error:
            self._error = str(error)


def _metadata(artifact: HistoricalSignalPublicationArtifact) -> HistoricalSignalMapMetadata:
    """Project stable source identity without retaining a second map-sized structure."""
    return HistoricalSignalMapMetadata(
        revision=artifact.revision,
        source_signal_artifact_sha256=artifact.source_signal_artifact_sha256,
        h2_artifact_sha256=artifact.h2_artifact_sha256,
        h3_artifact_sha256=artifact.h3_artifact_sha256,
        node_count=artifact.quality.node_count,
        lods=artifact.map.progressive_lods,
    )


def _require_bounded_response(
    value: HistoricalSignalMapApiResponse,
) -> HistoricalSignalMapApiResponse:
    """Reject a legal record count whose long names still exceed the wire budget."""
    encoded = json.dumps(value.model_dump(mode="json"), ensure_ascii=False).encode()
    if len(encoded) > _MAX_RESPONSE_BYTES:
        raise HistoricalSignalMapStoreError("historical signal response exceeds the 256 KiB cap")
    return value
