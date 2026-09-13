"""Serve bounded slices of the committed public open-construction graph."""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING, Literal

from pydantic import Field

from opennoise.models import FrozenModel
from opennoise.serving.open.construction_graph import (
    OpenConstructionGraphArtifact,
    OpenGraphEdge,
    verify_open_construction_graph,
)

if TYPE_CHECKING:
    from pathlib import Path

_LEVEL_BUDGETS = (240, 480, 720, 720)


class OpenConstructionMapNode(FrozenModel):
    """One client-safe node from the committed artifact landscape layout."""

    genre_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    x: float
    y: float
    degree: int = Field(ge=0)
    hierarchy_depth: int = Field(ge=0)


class OpenConstructionMapEdge(FrozenModel):
    """One explainable graph edge whose endpoints are present in a response."""

    source: str = Field(min_length=1)
    target: str = Field(min_length=1)
    kind: Literal["public_taxonomy_parent", "lexical_review_anchor"]
    confidence: float = Field(ge=0.0, le=1.0)
    factual_relationship: bool
    review_candidate: bool


class OpenConstructionMapResponse(FrozenModel):
    """Bounded semantic-map LOD response; it never serializes all 6,291 nodes."""

    source: Literal["open-construction-artifact"] = "open-construction-artifact"
    logical_output_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    level: int = Field(ge=0, le=3)
    node_budget: int = Field(ge=1, le=720)
    total_node_count: int = Field(ge=1)
    total_edge_count: int = Field(ge=0)
    truncated: bool
    nodes: tuple[OpenConstructionMapNode, ...] = Field(max_length=720)
    edges: tuple[OpenConstructionMapEdge, ...] = Field(max_length=512)


class OpenConstructionNeighborResponse(FrozenModel):
    """A bounded one-hop drill result for a selected open graph node."""

    source: Literal["open-construction-artifact"] = "open-construction-artifact"
    genre_id: str = Field(min_length=1)
    nodes: tuple[OpenConstructionMapNode, ...] = Field(min_length=1, max_length=25)
    edges: tuple[OpenConstructionMapEdge, ...] = Field(max_length=24)


class OpenConstructionMapStoreError(ValueError):
    """Report an unavailable or invalid committed open graph artifact."""


class OpenConstructionMapStore:
    """Load one sealed open graph, then select deterministic bounded cohorts."""

    def __init__(self, artifact_path: Path | None) -> None:
        """Bind one optional immutable artifact path for this process lifetime."""
        self._path = artifact_path
        self._artifact: OpenConstructionGraphArtifact | None = None
        self._nodes: dict[str, OpenConstructionMapNode] = {}
        self._edges_by_node: dict[str, tuple[OpenGraphEdge, ...]] = {}

    @property
    def configured(self) -> bool:
        """Return whether this process was given the committed graph path."""
        return self._path is not None

    async def start(self) -> None:
        """Validate the immutable graph at app start when it is configured."""
        if self.configured:
            self._require_artifact()

    def _require_artifact(self) -> OpenConstructionGraphArtifact:
        if self._artifact is not None:
            return self._artifact
        if self._path is None:
            raise OpenConstructionMapStoreError("open construction graph is disabled")
        try:
            artifact = OpenConstructionGraphArtifact.model_validate_json(self._path.read_bytes())
            verify_open_construction_graph(artifact)
        except (OSError, ValueError) as error:
            raise OpenConstructionMapStoreError(
                "open construction graph artifact unavailable"
            ) from error
        layout = {item.source_item_id: item for item in artifact.layout}
        degree: dict[str, int] = defaultdict(int)
        by_node: dict[str, list[OpenGraphEdge]] = defaultdict(list)
        for edge in artifact.edges:
            degree[edge.source_item_id] += 1
            degree[edge.target_item_id] += 1
            by_node[edge.source_item_id].append(edge)
            by_node[edge.target_item_id].append(edge)
        self._nodes = {
            node.source_item_id: OpenConstructionMapNode(
                genre_id=node.source_item_id,
                name=node.name,
                x=layout[node.source_item_id].landscape_x,
                y=layout[node.source_item_id].landscape_y,
                degree=degree[node.source_item_id],
                hierarchy_depth=layout[node.source_item_id].hierarchy_depth,
            )
            for node in artifact.nodes
        }
        self._edges_by_node = {
            node_id: tuple(sorted(edges, key=lambda item: (-item.confidence, item.edge_id)))
            for node_id, edges in by_node.items()
        }
        self._artifact = artifact
        return artifact

    def _ranked_nodes(self, level: int) -> list[OpenConstructionMapNode]:
        candidates = list(self._nodes.values())
        if level == 0:
            candidates = [node for node in candidates if node.degree and node.hierarchy_depth <= 1]
        elif level == 1:
            candidates = [node for node in candidates if node.degree]
        return sorted(
            candidates,
            key=lambda node: (
                -node.degree,
                node.hierarchy_depth,
                node.name.casefold(),
                node.genre_id,
            ),
        )

    @staticmethod
    def _edge(edge: OpenGraphEdge) -> OpenConstructionMapEdge:
        return OpenConstructionMapEdge(
            source=edge.source_item_id,
            target=edge.target_item_id,
            kind=edge.kind,
            confidence=edge.confidence,
            factual_relationship=edge.factual_relationship,
            review_candidate=edge.review_candidate,
        )

    def response(
        self,
        *,
        level: int,
        min_x: float | None = None,
        min_y: float | None = None,
        max_x: float | None = None,
        max_y: float | None = None,
    ) -> OpenConstructionMapResponse:
        """Return a deterministic LOD cohort, optionally narrowed to a landscape viewport."""
        if level not in range(len(_LEVEL_BUDGETS)):
            raise OpenConstructionMapStoreError("open construction level must be between 0 and 3")
        supplied = (min_x, min_y, max_x, max_y)
        if any(value is None for value in supplied) and any(
            value is not None for value in supplied
        ):
            raise OpenConstructionMapStoreError(
                "open construction viewport must include all bounds"
            )
        artifact = self._require_artifact()
        candidates = self._ranked_nodes(level)
        if all(value is not None for value in supplied):
            if min_x is None or min_y is None or max_x is None or max_y is None:
                raise RuntimeError("complete viewport unexpectedly contained a missing bound")
            if min_x >= max_x or min_y >= max_y:
                raise OpenConstructionMapStoreError("open construction viewport bounds are invalid")
            candidates = [
                node for node in candidates if min_x <= node.x <= max_x and min_y <= node.y <= max_y
            ]
        budget = _LEVEL_BUDGETS[level]
        selected = tuple(candidates[:budget])
        selected_ids = {node.genre_id for node in selected}
        edges = tuple(
            self._edge(edge)
            for edge in artifact.edges
            if edge.source_item_id in selected_ids and edge.target_item_id in selected_ids
        )[:512]
        return OpenConstructionMapResponse(
            logical_output_sha256=artifact.output_sha256,
            level=level,
            node_budget=budget,
            total_node_count=len(artifact.nodes),
            total_edge_count=len(artifact.edges),
            truncated=len(candidates) > len(selected),
            nodes=selected,
            edges=edges,
        )

    def neighbors(self, genre_id: str) -> OpenConstructionNeighborResponse:
        """Return no more than 24 direct edges and their endpoint nodes."""
        self._require_artifact()
        node = self._nodes.get(genre_id)
        if node is None:
            raise OpenConstructionMapStoreError("open construction graph node unavailable")
        edges = self._edges_by_node.get(genre_id, ())[:24]
        ids = {genre_id}
        for edge in edges:
            ids.add(edge.target_item_id if edge.source_item_id == genre_id else edge.source_item_id)
        return OpenConstructionNeighborResponse(
            genre_id=genre_id,
            nodes=tuple(self._nodes[item] for item in sorted(ids)),
            edges=tuple(self._edge(edge) for edge in edges),
        )
