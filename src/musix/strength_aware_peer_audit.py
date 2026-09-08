"""Deterministic local-only audit of separate direct and support peer channels."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal

from pydantic import Field

from musix.models import FrozenModel

_REVISION: Final = "strength-aware-peer-audit-v1"
_GRID: Final = ((2, 0.005), (2, 0.01), (2, 0.02), (3, 0.005), (3, 0.01), (3, 0.02), (5, 0.005), (5, 0.01), (5, 0.02))


class PeerAuditError(ValueError):
    """A candidate input does not meet the local audit contract."""


class PeerCandidate(FrozenModel):
    source_genre_id: str
    target_genre_id: str
    score: float = Field(ge=0, le=1)
    shared_supported_artist_count: int = Field(ge=1)


class ChannelInput(FrozenModel):
    output_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    component_kind: str
    candidates: tuple[PeerCandidate, ...]


class CoreMetric(FrozenModel):
    min_shared_artists: Literal[2, 3, 5]
    min_jaccard: Literal[0.005, 0.01, 0.02]
    edge_count: int = Field(ge=0)
    covered_seed_count: int = Field(ge=0)
    component_count: int = Field(ge=0)
    giant_component_fraction: float = Field(ge=0, le=1)
    largest_component_size: int = Field(ge=0)
    exact_pair_stability: float = Field(ge=0, le=1)
    direct_ablation_coassignment: float = Field(ge=0, le=1)
    support_ablation_coassignment: float = Field(ge=0, le=1)
    communities: tuple[tuple[str, ...], ...]
    cross_community_edge_count: int = Field(ge=0)


class StrengthAwarePeerAudit(FrozenModel):
    revision: Literal["strength-aware-peer-audit-v1"] = _REVISION
    scope: Literal["local_research_non_production"] = "local_research_non_production"
    historical_inputs_used_for_construction: Literal[False] = False
    direct_input_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    support_input_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    grid: tuple[CoreMetric, ...]
    direct_support_corroborated_edge_count: int = Field(ge=0)
    weak_navigation_edge_count: int = Field(ge=0)
    output_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


def build_strength_aware_peer_audit(direct_path: Path, support_path: Path) -> StrengthAwarePeerAudit:
    """Audit a preregistered threshold grid without combining source channels."""
    direct = _load(direct_path, "direct_artist_overlap")
    support = _load(support_path, "release_group_artist_overlap")
    metrics = tuple(
        _metric(direct.candidates, support.candidates, shared, score) for shared, score in _GRID
    )
    direct_pairs = {_pair(edge) for edge in direct.candidates}
    support_pairs = {_pair(edge) for edge in support.candidates}
    base = StrengthAwarePeerAudit(
        direct_input_sha256=direct.output_sha256,
        support_input_sha256=support.output_sha256,
        grid=metrics,
        direct_support_corroborated_edge_count=len(direct_pairs & support_pairs),
        weak_navigation_edge_count=sum(
            edge.shared_supported_artist_count < 2 or edge.score < 0.005
            for edge in direct.candidates + support.candidates
        ),
        output_sha256="0" * 64,
    )
    return base.model_copy(update={"output_sha256": _hash(base)})


def _load(path: Path, kind: str) -> ChannelInput:
    value = ChannelInput.model_validate_json(path.read_bytes())
    if value.component_kind != kind:
        raise PeerAuditError("candidate channel does not match audit role")
    return value


def _metric(
    direct: tuple[PeerCandidate, ...], support: tuple[PeerCandidate, ...], shared: int, score: float
) -> CoreMetric:
    edges = direct + support
    selected = tuple(edge for edge in edges if edge.shared_supported_artist_count >= shared and edge.score >= score)
    components = _components(selected)
    covered = sum(len(component) for component in components)
    largest = max((len(component) for component in components), default=0)
    communities = _partition(selected)
    labels = {node: index for index, community in enumerate(communities) for node in community}
    direct_pairs = _coassignment(_partition(_select(direct, shared, score)))
    support_pairs = _coassignment(_partition(_select(support, shared, score)))
    combined_pairs = _coassignment(communities)
    return CoreMetric(
        min_shared_artists=shared, min_jaccard=score, edge_count=len(selected),
        covered_seed_count=covered, component_count=len(components),
        giant_component_fraction=largest / covered if covered else 0.0,
        largest_component_size=largest,
        exact_pair_stability=_stability(selected),
        direct_ablation_coassignment=_jaccard(combined_pairs, direct_pairs),
        support_ablation_coassignment=_jaccard(combined_pairs, support_pairs),
        communities=communities,
        cross_community_edge_count=sum(
            labels.get(edge.source_genre_id) != labels.get(edge.target_genre_id) for edge in selected
        ),
    )


def _select(edges: tuple[PeerCandidate, ...], shared: int, score: float) -> tuple[PeerCandidate, ...]:
    return tuple(edge for edge in edges if edge.shared_supported_artist_count >= shared and edge.score >= score)


def _components(edges: tuple[PeerCandidate, ...]) -> tuple[frozenset[str], ...]:
    adjacency: dict[str, set[str]] = defaultdict(set)
    for edge in edges:
        adjacency[edge.source_genre_id].add(edge.target_genre_id)
        adjacency[edge.target_genre_id].add(edge.source_genre_id)
    pending = set(adjacency)
    result = []
    while pending:
        stack = [min(pending)]
        component: set[str] = set()
        while stack:
            node = stack.pop()
            if node in component:
                continue
            component.add(node)
            pending.discard(node)
            stack.extend(adjacency[node] - component)
        result.append(frozenset(component))
    return tuple(result)


def _stability(edges: tuple[PeerCandidate, ...]) -> float:
    """Exact edge-pair retention under deterministic parity subsampling."""
    if not edges:
        return 1.0
    original = _coassignment(_partition(edges))
    retained = tuple(edge for edge in edges if _stable_bit(edge) == 0)
    sampled = _coassignment(_partition(retained))
    union = original | sampled
    return len(original & sampled) / len(union) if union else 1.0


def _partition(edges: tuple[PeerCandidate, ...]) -> tuple[tuple[str, ...], ...]:
    """Recursively split components by deterministic weighted label propagation."""
    result: list[tuple[str, ...]] = []
    for component in _components(edges):
        result.extend(_split_component(tuple(sorted(component)), edges))
    return tuple(sorted(result, key=lambda members: (-len(members), members)))


def _split_component(nodes: tuple[str, ...], edges: tuple[PeerCandidate, ...]) -> list[tuple[str, ...]]:
    if len(nodes) <= 100:
        return [nodes]
    members = set(nodes)
    labels = {node: node for node in nodes}
    adjacency: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for edge in edges:
        if edge.source_genre_id in members and edge.target_genre_id in members:
            weight = edge.score * edge.shared_supported_artist_count
            adjacency[edge.source_genre_id].append((edge.target_genre_id, weight))
            adjacency[edge.target_genre_id].append((edge.source_genre_id, weight))
    for _ in range(12):
        changed = False
        for node in nodes:
            weights: dict[str, float] = defaultdict(float)
            for other, weight in adjacency[node]:
                weights[labels[other]] += weight
            if weights:
                best = min((-weight, label) for label, weight in weights.items())[1]
                changed = changed or best != labels[node]
                labels[node] = best
        if not changed:
            break
    groups: dict[str, list[str]] = defaultdict(list)
    for node in nodes:
        groups[labels[node]].append(node)
    partitions = [tuple(sorted(group)) for group in groups.values()]
    if len(partitions) == 1:
        midpoint = len(nodes) // 2
        return [nodes[:midpoint], nodes[midpoint:]]
    result: list[tuple[str, ...]] = []
    for group in partitions:
        result.extend(_split_component(group, edges))
    return result


def _coassignment(communities: tuple[tuple[str, ...], ...]) -> set[tuple[str, str]]:
    return {
        (left, right)
        for community in communities
        for index, left in enumerate(community)
        for right in community[index + 1 :]
    }


def _jaccard(left: set[tuple[str, str]], right: set[tuple[str, str]]) -> float:
    return len(left & right) / len(left | right) if left or right else 1.0


def _stable_bit(edge: PeerCandidate) -> int:
    return hashlib.sha256("\x1f".join(_pair(edge)).encode()).digest()[0] & 1


def _pair(edge: PeerCandidate) -> tuple[str, str]:
    return tuple(sorted((edge.source_genre_id, edge.target_genre_id)))


def _hash(artifact: StrengthAwarePeerAudit) -> str:
    payload = artifact.model_dump(mode="json", exclude={"output_sha256"})
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
