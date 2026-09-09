"""Serve bounded, typed slices of a verified Open construction graph v2."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Literal

from pydantic import Field

from musix.models import FrozenModel
from musix.serving.open.open_construction_graph_v2 import (
    OpenConstructionGraphV2Artifact,
    OpenGraphV2Edge,
    verify_open_construction_graph_v2,
)

if TYPE_CHECKING:
    from pathlib import Path

_LEVEL_BUDGETS = (48, 240, 480, 720)
_SEARCH_LIMIT = 20
_HIERARCHY_RELATION_LIMIT = 12
_MUSIC_ROOT_NODE_ID: Final = "catalog:wikidata:genre:Q115484611"
# A reviewed presentation distinction for this exact catalog identity, not a
# general rule inferred from a node name or from taxonomy depth.
_POPULAR_MUSIC_NODE_ID: Final = "catalog:wikidata:genre:Q373342"
_UNRESOLVED_IMPORT_STATUSES: Final = frozenset(
    {"anchored_compositional", "ambiguous_exact", "ambiguous_compositional", "abstained"}
)


@dataclass(frozen=True, slots=True)
class OpenConstructionV2Alias:
    """One reviewed display alias for an immutable retained source node."""

    display_name: str
    search_terms: tuple[str, ...]


_ALIASES_BY_NODE_ID = {
    # This is a search convenience only. Q37073 remains a distinct ordinary
    # genre from the structural Q373342 umbrella in every graph response.
    "catalog:wikidata:genre:Q37073": OpenConstructionV2Alias(
        display_name="Pop music",
        search_terms=("pop", "popular music"),
    ),
    "legacy:item887": OpenConstructionV2Alias(
        display_name="Intelligent dance music (IDM)",
        search_terms=("idm", "intelligent dance music"),
    ),
}


class OpenConstructionV2MapNode(FrozenModel):
    """One client-safe legacy or public catalog node."""

    node_id: str = Field(min_length=1)
    node_kind: Literal["legacy_name_seed", "public_catalog_genre"]
    name: str = Field(min_length=1)
    source_name: str | None = Field(default=None, min_length=1)
    taxonomy_status: str | None = Field(default=None, min_length=1)
    taxonomy_presentation: Literal["ordinary", "structural_umbrella"] = "ordinary"
    x: float
    y: float
    degree: int = Field(ge=0)
    hierarchy_depth: int = Field(ge=0)


class OpenConstructionV2MapEdge(FrozenModel):
    """One client-safe typed factual or review/navigation edge."""

    source: str = Field(min_length=1)
    target: str = Field(min_length=1)
    kind: Literal[
        "canonical_catalog_identity",
        "public_catalog_taxonomy_parent",
        "compositional_review_anchor",
        "ambiguous_identity_review_candidate",
    ]
    factual_relationship: bool
    review_candidate: bool


class OpenConstructionV2MapResponse(FrozenModel):
    """Bounded v2 LOD response; it never emits the full graph in one call."""

    source: Literal["open-construction-v2-artifact"] = "open-construction-v2-artifact"
    revision: Literal["open-construction-graph-v2"] = "open-construction-graph-v2"
    logical_output_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    taxonomy_expansion_logical_output_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    level: int = Field(ge=0, le=3)
    node_budget: int = Field(ge=1, le=720)
    legacy_seed_node_count: int = Field(ge=1)
    total_node_count: int = Field(ge=1)
    total_edge_count: int = Field(ge=0)
    factual_taxonomy_edge_count: int = Field(ge=0)
    review_navigation_edge_count: int = Field(ge=0)
    truncated: bool
    nodes: tuple[OpenConstructionV2MapNode, ...] = Field(max_length=720)
    edges: tuple[OpenConstructionV2MapEdge, ...] = Field(max_length=512)


class OpenConstructionV2NeighborResponse(FrozenModel):
    """A bounded one-hop v2 drill preserving edge semantics."""

    source: Literal["open-construction-v2-artifact"] = "open-construction-v2-artifact"
    node_id: str = Field(min_length=1)
    nodes: tuple[OpenConstructionV2MapNode, ...] = Field(min_length=1, max_length=25)
    edges: tuple[OpenConstructionV2MapEdge, ...] = Field(max_length=24)
    hierarchy: OpenConstructionV2HierarchyRelations


class OpenConstructionV2HierarchyRelations(FrozenModel):
    """Factual taxonomy navigation, kept separate from review links and peers."""

    broader: tuple[OpenConstructionV2MapNode, ...] = Field(max_length=_HIERARCHY_RELATION_LIMIT)
    broader_total: int = Field(ge=0)
    broader_remaining: int = Field(ge=0)
    narrower: tuple[OpenConstructionV2MapNode, ...] = Field(max_length=_HIERARCHY_RELATION_LIMIT)
    narrower_total: int = Field(ge=0)
    narrower_remaining: int = Field(ge=0)
    siblings: tuple[OpenConstructionV2MapNode, ...] = Field(max_length=_HIERARCHY_RELATION_LIMIT)
    siblings_total: int = Field(ge=0)
    siblings_remaining: int = Field(ge=0)


class OpenConstructionV2SearchResponse(FrozenModel):
    """A small, name-only lookup result for the Open v2 map surface."""

    source: Literal["open-construction-v2-artifact"] = "open-construction-v2-artifact"
    hits: tuple[OpenConstructionV2MapNode, ...] = Field(max_length=_SEARCH_LIMIT)


class OpenConstructionV2MapStoreError(ValueError):
    """Report an unavailable, malformed, or disabled v2 artifact."""


class OpenConstructionV2MapStore:
    """Load one explicit v2 artifact; never silently fall back to v1."""

    def __init__(self, artifact_path: Path | None) -> None:
        """Retain one optional immutable artifact path for this process lifetime."""
        self._path = artifact_path
        self._artifact: OpenConstructionGraphV2Artifact | None = None
        self._nodes: dict[str, OpenConstructionV2MapNode] = {}
        self._edges_by_node: dict[str, tuple[OpenGraphV2Edge, ...]] = {}

    @property
    def configured(self) -> bool:
        """Return whether a v2 artifact was explicitly selected."""
        return self._path is not None

    async def start(self) -> None:
        """Fail application startup if a configured artifact cannot pass its gate."""
        if self.configured:
            self._require_artifact()

    def _require_artifact(self) -> OpenConstructionGraphV2Artifact:
        if self._artifact is not None:
            return self._artifact
        if self._path is None:
            raise OpenConstructionV2MapStoreError("open construction v2 graph is disabled")
        try:
            artifact = OpenConstructionGraphV2Artifact.model_validate_json(self._path.read_bytes())
            verify_open_construction_graph_v2(artifact)
        except (OSError, ValueError) as error:
            raise OpenConstructionV2MapStoreError(
                "open construction v2 graph artifact unavailable"
            ) from error
        layout = {item.node_id: item for item in artifact.layout}
        degree: dict[str, int] = defaultdict(int)
        by_node: dict[str, list[OpenGraphV2Edge]] = defaultdict(list)
        for edge in artifact.edges:
            degree[edge.source_node_id] += 1
            degree[edge.target_node_id] += 1
            by_node[edge.source_node_id].append(edge)
            by_node[edge.target_node_id].append(edge)
        self._nodes = {
            node.node_id: OpenConstructionV2MapNode(
                node_id=node.node_id,
                node_kind=node.node_kind,
                name=_display_name(node.node_id, node.name),
                source_name=node.name if node.node_id in _ALIASES_BY_NODE_ID else None,
                taxonomy_status=node.taxonomy_status,
                taxonomy_presentation=(
                    "structural_umbrella" if node.node_id == _POPULAR_MUSIC_NODE_ID else "ordinary"
                ),
                x=layout[node.node_id].landscape_x,
                y=layout[node.node_id].landscape_y,
                degree=degree[node.node_id],
                hierarchy_depth=layout[node.node_id].hierarchy_depth,
            )
            for node in artifact.nodes
        }
        self._edges_by_node = {
            node_id: tuple(sorted(edges, key=lambda item: item.edge_id))
            for node_id, edges in by_node.items()
        }
        self._artifact = artifact
        return artifact

    def _ranked_nodes(self, level: int) -> list[OpenConstructionV2MapNode]:
        candidates = list(self._nodes.values())
        if level == 0:
            candidates = [
                node
                for node in candidates
                if (
                    node.node_kind == "public_catalog_genre"
                    and node.taxonomy_presentation == "ordinary"
                    and node.degree
                )
            ]
        elif level == 1:
            candidates = [
                node
                for node in candidates
                if node.taxonomy_presentation == "ordinary" and node.degree
            ]
        # The deep cohorts are spatially tiled by the request bounds. Include
        # isolated names here as well: they have no edge-driven reason to be
        # ranked into the overview, but their coordinates must remain
        # discoverable by zooming and panning through the complete artifact.
        return sorted(
            candidates,
            key=lambda node: (
                -node.degree,
                node.hierarchy_depth,
                node.name.casefold(),
                node.node_id,
            ),
        )

    @staticmethod
    def _edge(edge: OpenGraphV2Edge) -> OpenConstructionV2MapEdge:
        return OpenConstructionV2MapEdge(
            source=edge.source_node_id,
            target=edge.target_node_id,
            kind=edge.kind,
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
    ) -> OpenConstructionV2MapResponse:
        """Return one deterministic LOD cohort, optionally narrowed to a viewport."""
        if level not in range(len(_LEVEL_BUDGETS)):
            raise OpenConstructionV2MapStoreError(
                "open construction v2 level must be between 0 and 3"
            )
        bounds = (min_x, min_y, max_x, max_y)
        if any(value is None for value in bounds) and any(value is not None for value in bounds):
            raise OpenConstructionV2MapStoreError(
                "open construction v2 viewport must include all bounds"
            )
        artifact = self._require_artifact()
        candidates = self._ranked_nodes(level)
        if all(value is not None for value in bounds):
            if min_x is None or min_y is None or max_x is None or max_y is None:
                raise RuntimeError("complete v2 viewport unexpectedly contained a missing bound")
            if min_x >= max_x or min_y >= max_y:
                raise OpenConstructionV2MapStoreError(
                    "open construction v2 viewport bounds are invalid"
                )
            candidates = [
                node for node in candidates if min_x <= node.x <= max_x and min_y <= node.y <= max_y
            ]
        budget = _LEVEL_BUDGETS[level]
        nodes = tuple(candidates[:budget])
        selected = {node.node_id for node in nodes}
        edges = tuple(
            self._edge(edge)
            for edge in artifact.edges
            if edge.source_node_id in selected and edge.target_node_id in selected
        )[:512]
        return OpenConstructionV2MapResponse(
            logical_output_sha256=artifact.output_sha256,
            taxonomy_expansion_logical_output_sha256=artifact.taxonomy_expansion_logical_output_sha256,
            level=level,
            node_budget=budget,
            legacy_seed_node_count=artifact.coverage.legacy_seed_node_count,
            total_node_count=len(artifact.nodes),
            total_edge_count=len(artifact.edges),
            factual_taxonomy_edge_count=artifact.coverage.catalog_taxonomy_edge_count,
            review_navigation_edge_count=(
                artifact.coverage.compositional_review_edge_count
                + artifact.coverage.ambiguous_identity_review_edge_count
            ),
            truncated=len(candidates) > len(nodes),
            nodes=nodes,
            edges=edges,
        )

    def neighbors(self, node_id: str) -> OpenConstructionV2NeighborResponse:
        """Return no more than 24 direct edges and their endpoint nodes."""
        self._require_artifact()
        node = self._nodes.get(node_id)
        if node is None:
            raise OpenConstructionV2MapStoreError("open construction v2 graph node unavailable")
        edges = tuple(
            edge
            for edge in self._edges_by_node.get(node_id, ())
            if not _is_generic_music_review_anchor(node, edge)
        )[:24]
        node_ids = {node_id}
        for edge in edges:
            node_ids.add(
                edge.target_node_id if edge.source_node_id == node_id else edge.source_node_id
            )
        return OpenConstructionV2NeighborResponse(
            node_id=node_id,
            nodes=tuple(self._nodes[value] for value in sorted(node_ids)),
            edges=tuple(self._edge(edge) for edge in edges),
            hierarchy=self._hierarchy_relations(node_id),
        )

    def _hierarchy_relations(self, node_id: str) -> OpenConstructionV2HierarchyRelations:
        """Project factual parent, child, and shared-parent navigation only."""
        artifact = self._require_artifact()
        parents: set[str] = set()
        children: set[str] = set()
        for edge in artifact.edges:
            if edge.kind != "public_catalog_taxonomy_parent" or not edge.factual_relationship:
                continue
            if edge.source_node_id == node_id:
                parents.add(edge.target_node_id)
            elif edge.target_node_id == node_id:
                children.add(edge.source_node_id)
        siblings: set[str] = set()
        for edge in artifact.edges:
            if (
                edge.kind == "public_catalog_taxonomy_parent"
                and edge.factual_relationship
                and edge.target_node_id in parents
                and edge.source_node_id != node_id
            ):
                siblings.add(edge.source_node_id)
        broader = self._relation_nodes(parents)
        narrower = self._relation_nodes(children)
        sibling_nodes = self._relation_nodes(siblings)
        return OpenConstructionV2HierarchyRelations(
            broader=broader,
            broader_total=len(parents),
            broader_remaining=len(parents) - len(broader),
            narrower=narrower,
            narrower_total=len(children),
            narrower_remaining=len(children) - len(narrower),
            siblings=sibling_nodes,
            siblings_total=len(siblings),
            siblings_remaining=len(siblings) - len(sibling_nodes),
        )

    def _relation_nodes(self, node_ids: set[str]) -> tuple[OpenConstructionV2MapNode, ...]:
        """Bound factual relations by graph prominence, then stable visible name."""
        return tuple(
            sorted(
                (self._nodes[node_id] for node_id in node_ids),
                key=lambda node: (-node.degree, node.name.casefold(), node.node_id),
            )[:_HIERARCHY_RELATION_LIMIT]
        )

    def search(self, query: str, *, limit: int = _SEARCH_LIMIT) -> OpenConstructionV2SearchResponse:
        """Find a bounded, deterministic set of names from the configured artifact."""
        if limit < 1 or limit > _SEARCH_LIMIT:
            raise ValueError(
                f"open construction v2 search limit must be between 1 and {_SEARCH_LIMIT}"
            )
        self._require_artifact()
        needle = query.strip().casefold()
        if not needle:
            return OpenConstructionV2SearchResponse(hits=())
        matches = sorted(
            (
                (_search_rank(node, needle), node)
                for node in self._nodes.values()
                if _search_rank(node, needle) is not None
            ),
            key=lambda item: (item[0], item[1].name.casefold(), item[1].node_id),
        )
        return OpenConstructionV2SearchResponse(hits=tuple(node for _, node in matches[:limit]))


def _display_name(node_id: str, source_name: str) -> str:
    """Use a reviewed alias without replacing the immutable source label."""
    alias = _ALIASES_BY_NODE_ID.get(node_id)
    return alias.display_name if alias is not None else source_name


def _is_generic_music_review_anchor(node: OpenConstructionV2MapNode, edge: OpenGraphV2Edge) -> bool:
    """Hide a generic review root, while retaining factual taxonomy relationships."""
    other_node_id = (
        edge.target_node_id if edge.source_node_id == node.node_id else edge.source_node_id
    )
    return (
        edge.review_candidate
        and edge.kind == "compositional_review_anchor"
        and not edge.factual_relationship
        and other_node_id == _MUSIC_ROOT_NODE_ID
        and node.node_kind == "legacy_name_seed"
        and node.taxonomy_status in _UNRESOLVED_IMPORT_STATUSES
    )


def _search_rank(node: OpenConstructionV2MapNode, needle: str) -> int | None:
    """Rank reviewed aliases before ordinary source-name substring matches."""
    alias = _ALIASES_BY_NODE_ID.get(node.node_id)
    terms = (node.name, node.source_name, *(alias.search_terms if alias is not None else ()))
    normalized = tuple(term.casefold() for term in terms if term is not None)
    if needle in normalized:
        return 0
    if any(term.startswith(needle) for term in normalized):
        return 1
    return 2 if any(needle in term for term in normalized) else None
