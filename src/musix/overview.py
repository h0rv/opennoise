"""Bounded semantic overview derived only from production community assignments."""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING, Final

from musix.models.production_qa import ProductionMapOverviewCommunity

if TYPE_CHECKING:
    from musix.models.production import ProductionMapArtifact, ProductionNode

_MAX_OVERVIEW_COMMUNITIES: Final = 24


def build_overview_communities(
    artifact: ProductionMapArtifact,
) -> tuple[ProductionMapOverviewCommunity, ...]:
    """Merge artifact communities into at most 24 provenance-preserving groups."""
    source_groups: dict[str, list[ProductionNode]] = defaultdict(list)
    for node in artifact.nodes:
        source_groups[node.community_id].append(node)
    ranked_groups = sorted(source_groups.items(), key=lambda item: (-len(item[1]), item[0]))
    retained = ranked_groups[:_MAX_OVERVIEW_COMMUNITIES]
    merged: dict[str, list[ProductionNode]] = {
        source_id: list(nodes) for source_id, nodes in retained
    }
    centers = {source_id: _center(nodes) for source_id, nodes in merged.items()}
    memberships = {
        node.genre_id: source_id for source_id, nodes in source_groups.items() for node in nodes
    }
    adjacency = _community_adjacency(artifact, memberships)
    for source_id, nodes in ranked_groups[_MAX_OVERVIEW_COMMUNITIES:]:
        source_center = _center(nodes)
        target_id = min(
            centers,
            key=lambda candidate_id: (
                -adjacency.get(_edge_key(source_id, candidate_id), 0.0),
                _squared_distance(source_center, centers[candidate_id]),
                candidate_id,
            ),
        )
        merged[target_id].extend(nodes)
        centers[target_id] = _center(merged[target_id])
    return tuple(
        ProductionMapOverviewCommunity(
            community_id=f"overview:{source_id}",
            member_entity_ids=tuple(
                node.genre_id for node in sorted(nodes, key=lambda node: node.genre_id)
            ),
            x=centers[source_id][0],
            y=centers[source_id][1],
        )
        for source_id, nodes in sorted(merged.items())
    )


def _center(nodes: list[ProductionNode]) -> tuple[float, float]:
    return (
        sum(float(node.x) for node in nodes) / len(nodes),
        sum(float(node.y) for node in nodes) / len(nodes),
    )


def _squared_distance(left: tuple[float, float], right: tuple[float, float]) -> float:
    return (left[0] - right[0]) ** 2 + (left[1] - right[1]) ** 2


def _community_adjacency(
    artifact: ProductionMapArtifact, memberships: dict[str, str]
) -> dict[tuple[str, str], float]:
    """Sum declared similarity-edge weights between source model communities."""
    result: dict[tuple[str, str], float] = defaultdict(float)
    for edge in artifact.edges:
        if edge.kind != "similarity":
            continue
        source = memberships[edge.source_genre_id]
        target = memberships[edge.target_genre_id]
        if source != target:
            result[_edge_key(source, target)] += float(edge.weight)
    return result


def _edge_key(left: str, right: str) -> tuple[str, str]:
    return (left, right) if left < right else (right, left)
