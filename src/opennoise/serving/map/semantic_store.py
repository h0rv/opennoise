"""Serve one verified structural-map artifact to the Canvas renderer."""
# ruff: noqa: D101, D102

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from pydantic import Field, model_validator

from opennoise.ml.semantic_layout.contracts import (
    CameraBounds,
    SemanticLayoutArtifact,
    verify_semantic_map_layout,
)
from opennoise.models import FrozenModel

if TYPE_CHECKING:
    from pathlib import Path

_DETAIL_EDGE_BUDGET = 12
_LABEL_BUDGETS = (45, 96, 210, 420)
_LOD_LEVELS: tuple[Literal[0, 1, 2, 3], ...] = (0, 1, 2, 3)


class SemanticMapStoreError(ValueError):
    """Report a semantic-map artifact that is unavailable or invalid."""


class SemanticRendererNode(FrozenModel):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    x: float
    y: float
    lod: Literal[0, 1, 2, 3]
    importance: float = Field(ge=0)
    community_id: int = Field(ge=0)
    display_parent_id: str | None = Field(default=None, min_length=1)
    hierarchy_root_id: str | None = Field(default=None, min_length=1)
    hierarchy_depth: int = Field(ge=0)


class SemanticRendererRegion(FrozenModel):
    """One artifact community exposed as a progressive map heading."""

    community_id: int = Field(ge=0)
    label: str = Field(min_length=1)
    x: float
    y: float
    member_count: int = Field(ge=1)
    overview_visible: bool
    heading_lod: Literal[0, 1, 2, 3]


class SemanticRendererLabelSet(FrozenModel):
    level: Literal[0, 1, 2, 3]
    ids: tuple[str, ...]


class SemanticRendererAlias(FrozenModel):
    term: str = Field(min_length=1)
    target: str = Field(min_length=1)


class SemanticRendererResponse(FrozenModel):
    revision: Literal["semantic-scatter-map-v2"] = "semantic-scatter-map-v2"
    source: Literal["semantic-map-layout-v1"] = "semantic-map-layout-v1"
    logical_output_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    total_seed_count: int = Field(ge=1)
    placed_node_count: int = Field(ge=1)
    unplaced_node_count: int = Field(ge=0)
    world_bounds: CameraBounds
    content_bounds: CameraBounds
    initial_camera: CameraBounds
    nodes: tuple[SemanticRendererNode, ...]
    overview_regions: tuple[SemanticRendererRegion, ...] = ()
    labels: tuple[SemanticRendererLabelSet, ...]
    aliases: tuple[SemanticRendererAlias, ...]

    @model_validator(mode="after")
    def _invariants(self) -> SemanticRendererResponse:  # noqa: C901
        if self.placed_node_count + self.unplaced_node_count != self.total_seed_count:
            raise ValueError("placed and unplaced counts must partition stable seeds")
        ids = {node.id for node in self.nodes}
        if len(ids) != self.placed_node_count or len(ids) != len(self.nodes):
            raise ValueError("renderer node IDs must be unique and complete")
        regions = {region.community_id: region for region in self.overview_regions}
        if len(regions) != len(self.overview_regions):
            raise ValueError("renderer region IDs must be unique")
        node_communities = {node.community_id for node in self.nodes}
        if node_communities != set(regions):
            raise ValueError("renderer regions must cover every placed node community")
        for region in self.overview_regions:
            if region.member_count != sum(
                node.community_id == region.community_id for node in self.nodes
            ):
                raise ValueError("renderer region member count must replay")
        prior: set[str] = set()
        for cap, record in zip(_LABEL_BUDGETS, self.labels, strict=True):
            current = set(record.ids)
            if len(record.ids) != len(current) or len(record.ids) > cap or not prior <= current:
                raise ValueError("renderer labels must be persistent and capped")
            if not current <= ids:
                raise ValueError("renderer labels must refer to placed nodes")
            prior = current
        aliases: dict[str, str] = {}
        for alias in self.aliases:
            if alias.target not in ids:
                raise ValueError("renderer aliases must focus placed stable seeds")
            if aliases.setdefault(alias.term, alias.target) != alias.target:
                raise ValueError("renderer aliases cannot ambiguously target multiple seeds")
        return self


class SemanticMapNode(FrozenModel):
    node_id: str
    name: str


class SemanticMapEdge(FrozenModel):
    source: str
    target: str
    confidence: float = Field(gt=0)


class SemanticMapNeighbors(FrozenModel):
    node_id: str
    nodes: tuple[SemanticMapNode, ...]
    edges: tuple[SemanticMapEdge, ...]


class SemanticMapSearchHit(FrozenModel):
    node_id: str
    name: str
    placed: bool
    unplaced_reason: Literal["no_supported_structural_relation"] | None = None


@dataclass(slots=True)
class SemanticMapStore:
    """A small in-memory index over the artifact's precomputed geometry."""

    layout_path: Path
    _artifact: SemanticLayoutArtifact | None = None
    _nodes: dict[str, SemanticRendererNode] | None = None
    _names: dict[str, SemanticMapSearchHit] | None = None
    _edges: tuple[SemanticMapEdge, ...] = ()

    @property
    def configured(self) -> bool:
        return self._artifact is not None

    def start(self) -> None:
        try:
            artifact = SemanticLayoutArtifact.model_validate_json(self.layout_path.read_bytes())
            verify_semantic_map_layout(artifact)
        except (OSError, ValueError) as error:
            raise SemanticMapStoreError("semantic map artifact is invalid") from error
        if artifact.publication_scope != "local_research_only":
            raise SemanticMapStoreError("semantic map artifact is not local-only")
        self._artifact = artifact
        self._nodes = {
            f"legacy:{coordinate.seed_id}": SemanticRendererNode(
                id=f"legacy:{coordinate.seed_id}",
                name=coordinate.name,
                x=coordinate.x,
                y=coordinate.y,
                lod=coordinate.lod,
                importance=coordinate.importance,
                community_id=coordinate.community_id,
                display_parent_id=(
                    f"legacy:{coordinate.display_parent_id}"
                    if coordinate.display_parent_id
                    else None
                ),
                hierarchy_root_id=(
                    f"legacy:{coordinate.hierarchy_root_id}"
                    if coordinate.hierarchy_root_id
                    else None
                ),
                hierarchy_depth=coordinate.hierarchy_depth,
            )
            for coordinate in artifact.coordinates
        }
        self._names = {
            f"legacy:{coordinate.seed_id}": SemanticMapSearchHit(
                node_id=f"legacy:{coordinate.seed_id}", name=coordinate.name, placed=True
            )
            for coordinate in artifact.coordinates
        } | {
            f"legacy:{unplaced.seed_id}": SemanticMapSearchHit(
                node_id=f"legacy:{unplaced.seed_id}",
                name=unplaced.name,
                placed=False,
                unplaced_reason="no_supported_structural_relation",
            )
            for unplaced in artifact.unplaced
        }
        self._edges = tuple(
            SemanticMapEdge(
                source=f"legacy:{edge.left_seed_id}",
                target=f"legacy:{edge.right_seed_id}",
                confidence=edge.weight,
            )
            for edge in artifact.structural_edges
        )

    def renderer(self) -> SemanticRendererResponse:
        artifact, nodes = self._require()
        anchors = tuple(
            f"legacy:{community.anchor_seed_id}"
            for community in artifact.communities
            if community.overview_visible
        )
        ranked = sorted(
            nodes.values(), key=lambda node: (-node.importance, node.name.casefold(), node.id)
        )
        label_sets: list[SemanticRendererLabelSet] = []
        prior = list(anchors)
        for level, budget in zip(_LOD_LEVELS, _LABEL_BUDGETS, strict=True):
            candidates = [node.id for node in ranked if node.lod <= level and node.id not in prior]
            prior.extend(candidates[: max(0, budget - len(prior))])
            label_sets.append(SemanticRendererLabelSet(level=level, ids=tuple(prior)))
        aliases = [
            SemanticRendererAlias(term=node.name.casefold(), target=node.id)
            for node in nodes.values()
        ]
        aliases.extend(
            (
                SemanticRendererAlias(term="idm", target="legacy:item887"),
                SemanticRendererAlias(term="intelligent dance", target="legacy:item887"),
                SemanticRendererAlias(term="pop music", target="legacy:item1"),
                SemanticRendererAlias(term="popular music", target="legacy:item1"),
            )
        )
        overview_regions = tuple(
            SemanticRendererRegion(
                community_id=community.community_id,
                label=community.label,
                x=community.x,
                y=community.y,
                member_count=community.member_count,
                overview_visible=community.overview_visible,
                heading_lod=(
                    0
                    if community.overview_visible
                    else min(
                        node.lod
                        for node in nodes.values()
                        if node.community_id == community.community_id
                    )
                ),
            )
            for community in artifact.communities
        )
        return SemanticRendererResponse(
            logical_output_sha256=artifact.output_sha256,
            total_seed_count=artifact.stable_seed_count,
            placed_node_count=len(nodes),
            unplaced_node_count=len(artifact.unplaced),
            world_bounds=artifact.world_bounds,
            content_bounds=artifact.content_bounds,
            initial_camera=artifact.initial_camera,
            nodes=tuple(sorted(nodes.values(), key=lambda node: node.id)),
            overview_regions=overview_regions,
            labels=tuple(label_sets),
            aliases=tuple(
                SemanticRendererAlias(term=term, target=target)
                for term, target in sorted({(alias.term, alias.target) for alias in aliases})
            ),
        )

    def neighbors(self, node_id: str, *, offset: int = 0) -> SemanticMapNeighbors:
        del offset
        _, nodes = self._require()
        if node_id not in nodes:
            raise SemanticMapStoreError("unplaced or unknown seed has no map neighborhood")
        edges = tuple(
            sorted(
                (edge for edge in self._edges if node_id in {edge.source, edge.target}),
                key=lambda edge: (-edge.confidence, edge.source, edge.target),
            )[:_DETAIL_EDGE_BUDGET]
        )
        ids = {node_id} | {edge.target if edge.source == node_id else edge.source for edge in edges}
        return SemanticMapNeighbors(
            node_id=node_id,
            nodes=tuple(
                SemanticMapNode(node_id=identifier, name=nodes[identifier].name)
                for identifier in sorted(ids)
            ),
            edges=edges,
        )

    def search(self, query: str) -> tuple[SemanticMapSearchHit, ...]:
        _, _ = self._require()
        assert self._names is not None  # noqa: S101
        needle = query.strip().casefold()
        if not needle:
            return ()
        aliases = {
            "idm": "legacy:item887",
            "intelligent dance": "legacy:item887",
            "pop music": "legacy:item1",
            "popular music": "legacy:item1",
        }
        direct = self._names.get(aliases.get(needle, ""))
        matches = [hit for hit in self._names.values() if needle in hit.name.casefold()]
        if direct is not None and direct not in matches:
            matches.insert(0, direct)
        ordered = sorted(
            matches, key=lambda hit: (not hit.placed, hit.name.casefold(), hit.node_id)
        )
        if direct is not None:
            ordered = [direct, *(hit for hit in ordered if hit != direct)]
        return tuple(ordered[:50])

    def _require(self) -> tuple[SemanticLayoutArtifact, dict[str, SemanticRendererNode]]:
        if self._artifact is None or self._nodes is None:
            raise SemanticMapStoreError("semantic map is unavailable")
        return self._artifact, self._nodes
