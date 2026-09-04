"""Bounded semantic overview derived only from production community assignments."""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING, Final

from musix.models.production_qa import ProductionMapOverviewCommunity, ProductionMapOverviewNaming

if TYPE_CHECKING:
    from musix.models.production import ProductionMapArtifact, ProductionNode

_MAX_OVERVIEW_COMMUNITIES: Final = 24
_MIN_ANCHOR_WEIGHTED_COVERAGE: Final = 0.5
_MIN_ANCHOR_SUBTREE_SIZE: Final = 3
_MIN_ANCHOR_DIRECT_ARTISTS: Final = 4
_MIN_ANCHOR_PROPAGATED_ARTISTS: Final = 8
_SINGLETON_SUBTREE_SIZE: Final = 1
_SMALL_SUBTREE_SIZE: Final = 2


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
    drafts = [
        _community_draft(source_id, nodes, centers[source_id], artifact.nodes)
        for source_id, nodes in sorted(merged.items())
    ]
    name_counts: dict[str, int] = defaultdict(int)
    for draft in drafts:
        name_counts[draft.name] += 1
    return tuple(
        ProductionMapOverviewCommunity(
            community_id=f"overview:{draft.source_id}",
            member_entity_ids=draft.member_entity_ids,
            name=(
                draft.name
                if name_counts[draft.name] == 1
                else f"{draft.name} ({draft.source_id.rsplit(':', maxsplit=1)[-1]})"
            ),
            naming=draft.naming,
            x=draft.center[0],
            y=draft.center[1],
        )
        for draft in drafts
    )


class _CommunityDraft:
    """Internal, stable overview construction record before name de-duplication."""

    def __init__(
        self,
        source_id: str,
        member_entity_ids: tuple[str, ...],
        name: str,
        naming: ProductionMapOverviewNaming,
        center: tuple[float, float],
    ) -> None:
        self.source_id = source_id
        self.member_entity_ids = member_entity_ids
        self.name = name
        self.naming = naming
        self.center = center


def _community_draft(
    source_id: str,
    members: list[ProductionNode],
    center: tuple[float, float],
    all_nodes: tuple[ProductionNode, ...],
) -> _CommunityDraft:
    """Name a merged similarity community from its public display taxonomy.

    A taxonomy ancestor must cover a weighted majority of the merged community
    and be broad enough to be a useful overview label. This keeps a dense group
    of techno variants under electronic music rather than its most popular leaf.
    """
    by_id = {node.genre_id: node for node in all_nodes}
    total_weight = sum(_member_weight(node) for node in members)
    coverage: dict[str, int] = defaultdict(int)
    for member in members:
        for ancestor in _ancestors(member, by_id):
            coverage[ancestor.genre_id] += _member_weight(member)
    candidates = [
        (by_id[genre_id], weight / total_weight)
        for genre_id, weight in coverage.items()
        if _meaningful_overview_anchor(by_id[genre_id])
        and weight / total_weight >= _MIN_ANCHOR_WEIGHTED_COVERAGE
    ]
    if candidates:
        anchor, weighted_coverage = min(
            candidates,
            key=lambda item: (
                -_coverage_score(item[0], item[1]),
                -item[1],
                -item[0].depth,
                -item[0].subtree_size,
                -item[0].direct_artist_count,
                item[0].name.casefold(),
                item[0].genre_id,
            ),
        )
        method = "canonical_taxonomy_ancestor_weighted_coverage_v1"
    else:
        anchor = min(
            members,
            key=lambda node: (
                -node.direct_artist_count,
                -node.propagated_artist_count,
                -node.subtree_size,
                node.name.casefold(),
                node.genre_id,
            ),
        )
        weighted_coverage = _member_weight(anchor) / total_weight
        method = "community_centrality_fallback_v1"
    return _CommunityDraft(
        source_id=source_id,
        member_entity_ids=tuple(
            node.genre_id for node in sorted(members, key=lambda node: node.genre_id)
        ),
        name=anchor.name,
        naming=ProductionMapOverviewNaming(
            method=method,
            anchor_entity_id=anchor.genre_id,
            weighted_coverage=weighted_coverage,
            provenance_refs=anchor.evidence_refs,
        ),
        center=center,
    )


def _member_weight(node: ProductionNode) -> int:
    """Use observed direct membership without letting a zero-evidence node vanish."""
    return max(1, node.direct_artist_count)


def _ancestors(
    node: ProductionNode, by_id: dict[str, ProductionNode]
) -> tuple[ProductionNode, ...]:
    """Walk the canonical display tree only; fail closed on an invalid cycle."""
    result: list[ProductionNode] = []
    current: ProductionNode | None = node
    seen: set[str] = set()
    while current is not None:
        if current.genre_id in seen:
            raise ValueError("production display taxonomy cannot contain a cycle")
        seen.add(current.genre_id)
        result.append(current)
        current = by_id.get(current.display_parent_id) if current.display_parent_id else None
    return tuple(result)


def _meaningful_overview_anchor(node: ProductionNode) -> bool:
    """Avoid promoting a rare leaf when a community has no shared umbrella."""
    return (
        node.subtree_size >= _MIN_ANCHOR_SUBTREE_SIZE
        or node.direct_artist_count >= _MIN_ANCHOR_DIRECT_ARTISTS
        or node.propagated_artist_count >= _MIN_ANCHOR_PROPAGATED_ARTISTS
    )


def _coverage_score(node: ProductionNode, weighted_coverage: float) -> float:
    """Penalize a singleton or rare anchor without obscuring coverage priority."""
    narrow_penalty = (
        0.12
        if node.subtree_size == _SINGLETON_SUBTREE_SIZE
        else 0.04
        if node.subtree_size <= _SMALL_SUBTREE_SIZE
        else 0.0
    )
    rare_penalty = 0.04 if node.direct_artist_count == 0 else 0.0
    return weighted_coverage - narrow_penalty - rare_penalty


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
