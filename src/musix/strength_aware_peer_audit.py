"""Deterministic local-only audit of separate direct and support peer channels."""
# ruff: noqa: D101, PLR2004, C901, TC003

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Final, Literal

from pydantic import Field

from musix.models import FrozenModel
from musix.taxonomy.seed_reconciliation import load_seed_reconciliation

_REVISION: Final = "strength-aware-peer-audit-v1"
type GridMinimum = Literal[2, 3, 5]

_GRID: Final[tuple[tuple[GridMinimum, float], ...]] = (
    (2, 0.005),
    (2, 0.01),
    (2, 0.02),
    (3, 0.005),
    (3, 0.01),
    (3, 0.02),
    (5, 0.005),
    (5, 0.01),
    (5, 0.02),
)
_CONSENSUS_REVISION: Final = "consensus-micro-neighborhood-audit-v2"
_CONSENSUS_SEEDS: Final = (1979, 2027, 2039, 2063, 2081)
_CONSENSUS_DROP_NUMERATOR: Final = 2_000
_CONSENSUS_DROP_DENOMINATOR: Final = 10_000
_CONSENSUS_THRESHOLD: Final = 0.8


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
    min_shared_artists: GridMinimum
    min_jaccard: float = Field(ge=0, le=1)
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


class CorroboratedPeerAudit(FrozenModel):
    revision: Literal["corroborated-peer-audit-v1"] = "corroborated-peer-audit-v1"
    scope: Literal["local_research_non_production"] = "local_research_non_production"
    direct_input_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    support_input_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    corroborated_edge_count: int = Field(ge=0)
    covered_seed_count: int = Field(ge=0)
    component_count: int = Field(ge=0)
    largest_partition_size: int = Field(ge=0)
    direct_ablation_coassignment: float = Field(ge=0, le=1)
    support_ablation_coassignment: float = Field(ge=0, le=1)
    output_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class ArtifactBinding(FrozenModel):
    """Byte and logical identities of one replay input."""

    artifact_bytes_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    artifact_logical_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_seed_reconciliation_bytes_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    artifact_bytes: int = Field(ge=1)
    seed_count: int = Field(ge=1)
    support_genre_count: int = Field(ge=0)
    support_membership_count: int = Field(ge=0)
    empty_input_seed_count: int = Field(ge=0)
    seeds_without_qualifying_neighbors_count: int = Field(ge=0)
    candidate_edge_count: int = Field(ge=0)


class ConsensusPerturbationConfig(FrozenModel):
    """Preregistered deterministic edge-drop and partition settings."""

    seeds: tuple[int, ...] = _CONSENSUS_SEEDS
    edge_drop_numerator: Literal[2000] = _CONSENSUS_DROP_NUMERATOR
    edge_drop_denominator: Literal[10000] = _CONSENSUS_DROP_DENOMINATOR
    partition_algorithm: Literal["deterministic_weighted_label_propagation"] = (
        "deterministic_weighted_label_propagation"
    )
    partition_maximum_size: Literal[100] = 100
    label_propagation_iterations: Literal[12] = 12
    edge_weight: Literal["binary_jaccard_times_shared_supported_artist_count"] = (
        "binary_jaccard_times_shared_supported_artist_count"
    )
    singleton_partition_fallback: Literal["lexical_bisection"] = "lexical_bisection"
    consensus_threshold: float = Field(default=_CONSENSUS_THRESHOLD, ge=0.8, le=0.8)


class ChannelPairEvidence(FrozenModel):
    """The raw endpoint metric when that endpoint is present in a channel."""

    score: float = Field(ge=0, le=1)
    shared_supported_artist_count: int = Field(ge=1)


class StableConsensusPair(FrozenModel):
    """One pair stable in both independently perturbed channels."""

    source_genre_id: str
    target_genre_id: str
    direct_coassignment_frequency: float = Field(ge=0.8, le=1)
    support_coassignment_frequency: float = Field(ge=0.8, le=1)
    direct_coassigned_runs: int = Field(ge=4, le=5)
    support_coassigned_runs: int = Field(ge=4, le=5)
    direct_source_evidence: ChannelPairEvidence | None = None
    support_source_evidence: ChannelPairEvidence | None = None


class EgoAffiliation(FrozenModel):
    """A stable ego neighborhood; memberships intentionally overlap."""

    genre_id: str
    member_genre_ids: tuple[str, ...]
    stable_peer_genre_ids: tuple[str, ...]
    overlapping_memberships_allowed: Literal[True] = True


class ConsensusAbstention(FrozenModel):
    """One covered seed without an eligible stable ego affiliation."""

    genre_id: str
    reason: Literal[
        "no_direct_candidate_endpoint",
        "no_support_candidate_endpoint",
        "no_cross_channel_stable_coassignment",
    ]


class DerivedComponent(FrozenModel):
    """A disjoint graph projection, explicitly not a genre taxonomy."""

    member_genre_ids: tuple[str, ...]
    not_a_taxonomy: Literal[True] = True


class ConsensusMicroNeighborhoodAudit(FrozenModel):
    revision: Literal["consensus-micro-neighborhood-audit-v2"] = _CONSENSUS_REVISION
    scope: Literal["local_research_non_production"] = "local_research_non_production"
    historical_inputs_used_for_construction: Literal[False] = False
    direct_input: ArtifactBinding
    support_input: ArtifactBinding
    seed_reconciliation_bytes_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    seed_reconciliation_logical_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    perturbation: ConsensusPerturbationConfig
    replay_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    stable_pair_count: int = Field(ge=0)
    covered_seed_count: int = Field(ge=0)
    eligible_seed_count: int = Field(ge=0)
    abstention_count: int = Field(ge=0)
    stable_pairs: tuple[StableConsensusPair, ...]
    ego_affiliations: tuple[EgoAffiliation, ...]
    derived_disjoint_components_not_taxonomy: tuple[DerivedComponent, ...]
    abstentions: tuple[ConsensusAbstention, ...]
    output_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


def build_strength_aware_peer_audit(
    direct_path: Path, support_path: Path
) -> StrengthAwarePeerAudit:
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


def build_corroborated_peer_audit(direct_path: Path, support_path: Path) -> CorroboratedPeerAudit:
    """Audit only independently corroborated pairs, with no raw-score blending."""
    direct = _load(direct_path, "direct_artist_overlap")
    support = _load(support_path, "release_group_artist_overlap")
    direct_by_pair = {_pair(edge): edge for edge in direct.candidates}
    support_by_pair = {_pair(edge): edge for edge in support.candidates}
    pairs = direct_by_pair.keys() & support_by_pair.keys()
    core = tuple(direct_by_pair[pair] for pair in sorted(pairs))
    communities = _partition(core)
    combined = _coassignment(communities)
    return _corroborated_artifact(direct, support, core, combined, communities)


def build_consensus_micro_neighborhood_audit(
    direct_path: Path, support_path: Path, seed_reconciliation_path: Path
) -> ConsensusMicroNeighborhoodAudit:
    """Build a replayable endpoint artifact from two independent local channels."""
    direct, direct_binding = _load_consensus_channel(direct_path, "direct_artist_overlap")
    support, support_binding = _load_consensus_channel(support_path, "release_group_artist_overlap")
    reconciliation = load_seed_reconciliation(seed_reconciliation_path)
    seed_ids = tuple(sorted(row.source_item_id for row in reconciliation.dispositions))
    if len(seed_ids) != len(set(seed_ids)):
        raise PeerAuditError("seed reconciliation contains duplicate stable IDs")
    if direct_binding.seed_count != len(seed_ids) or support_binding.seed_count != len(seed_ids):
        raise PeerAuditError("channel seed count does not match seed reconciliation")
    reconciliation_bytes_sha256 = _file_sha256(seed_reconciliation_path)
    if seed_reconciliation_path in {direct_path, support_path}:
        raise PeerAuditError("seed reconciliation must be distinct from channel artifacts")
    for binding in (direct_binding, support_binding):
        if binding.source_seed_reconciliation_bytes_sha256 != reconciliation_bytes_sha256:
            raise PeerAuditError(
                "channel reconciliation hash does not bind the supplied seed universe"
            )
    config = ConsensusPerturbationConfig()
    direct_counts = _coassignment_counts(direct.candidates, config, "direct_artist_overlap")
    support_counts = _coassignment_counts(
        support.candidates, config, "release_group_artist_overlap"
    )
    run_count = len(config.seeds)
    stable = tuple(
        pair
        for pair in sorted(direct_counts.keys() & support_counts.keys())
        if direct_counts[pair] / run_count >= config.consensus_threshold
        and support_counts[pair] / run_count >= config.consensus_threshold
    )
    direct_evidence = {_pair(edge): edge for edge in direct.candidates}
    support_evidence = {_pair(edge): edge for edge in support.candidates}
    stable_pairs = tuple(
        _stable_pair(
            pair,
            (direct_counts, support_counts),
            run_count,
            (direct_evidence, support_evidence),
        )
        for pair in stable
    )
    affiliates = _ego_affiliations(stable)
    eligible_ids = {affiliation.genre_id for affiliation in affiliates}
    direct_endpoints = _endpoint_ids(direct.candidates)
    support_endpoints = _endpoint_ids(support.candidates)
    abstentions = tuple(
        ConsensusAbstention(
            genre_id=seed, reason=_abstention_reason(seed, direct_endpoints, support_endpoints)
        )
        for seed in seed_ids
        if seed not in eligible_ids
    )
    components = tuple(
        DerivedComponent(member_genre_ids=tuple(sorted(component)))
        for component in sorted(
            _components(_edges_from_pairs(stable)),
            key=lambda members: (-len(members), tuple(sorted(members))),
        )
    )
    base = ConsensusMicroNeighborhoodAudit(
        direct_input=direct_binding,
        support_input=support_binding,
        seed_reconciliation_bytes_sha256=reconciliation_bytes_sha256,
        seed_reconciliation_logical_sha256=reconciliation.output_sha256,
        perturbation=config,
        replay_sha256=_replay_sha256(
            direct_binding,
            support_binding,
            reconciliation_bytes_sha256,
            reconciliation.output_sha256,
            config,
        ),
        stable_pair_count=len(stable_pairs),
        covered_seed_count=len(seed_ids),
        eligible_seed_count=len(eligible_ids),
        abstention_count=len(abstentions),
        stable_pairs=stable_pairs,
        ego_affiliations=affiliates,
        derived_disjoint_components_not_taxonomy=components,
        abstentions=abstentions,
        output_sha256="0" * 64,
    )
    if base.eligible_seed_count + base.abstention_count != base.covered_seed_count:
        raise PeerAuditError("consensus coverage does not account for every stable seed")
    return base.model_copy(update={"output_sha256": _hash(base)})


def _load_consensus_channel(path: Path, kind: str) -> tuple[ChannelInput, ArtifactBinding]:
    """Verify an input's raw bytes and its producer's logical checksum."""
    raw_bytes = path.read_bytes()
    try:
        raw_value = json.loads(raw_bytes)
    except json.JSONDecodeError as error:
        raise PeerAuditError("candidate channel is not valid JSON") from error
    if not isinstance(raw_value, dict):
        raise PeerAuditError("candidate channel must be a JSON object")
    value = ChannelInput.model_validate_json(raw_bytes)
    if value.component_kind != kind:
        raise PeerAuditError("candidate channel does not match audit role")
    declared_hash = raw_value.get("output_sha256")
    if not isinstance(declared_hash, str) or declared_hash != _logical_sha256(raw_value):
        raise PeerAuditError("candidate channel logical hash does not match its content")
    required_metrics = (
        "seed_count",
        "support_genre_count",
        "support_membership_count",
        "empty_input_seed_count",
        "seeds_without_qualifying_neighbors_count",
    )
    if any(not isinstance(raw_value.get(metric), int) for metric in required_metrics):
        raise PeerAuditError("candidate channel lacks required source evidence metrics")
    reconciliation_hash = raw_value["reconciliation_sha256"]
    if not isinstance(reconciliation_hash, str):
        raise PeerAuditError("candidate channel lacks a seed reconciliation hash")
    return value, ArtifactBinding(
        artifact_bytes_sha256=hashlib.sha256(raw_bytes).hexdigest(),
        artifact_logical_sha256=declared_hash,
        source_seed_reconciliation_bytes_sha256=reconciliation_hash,
        artifact_bytes=len(raw_bytes),
        seed_count=raw_value["seed_count"],
        support_genre_count=raw_value["support_genre_count"],
        support_membership_count=raw_value["support_membership_count"],
        empty_input_seed_count=raw_value["empty_input_seed_count"],
        seeds_without_qualifying_neighbors_count=raw_value[
            "seeds_without_qualifying_neighbors_count"
        ],
        candidate_edge_count=len(value.candidates),
    )


def _coassignment_counts(
    edges: tuple[PeerCandidate, ...],
    config: ConsensusPerturbationConfig,
    channel_kind: str,
) -> dict[tuple[str, str], int]:
    counts: dict[tuple[str, str], int] = defaultdict(int)
    for seed in config.seeds:
        retained = tuple(
            edge for edge in edges if _retained_by_perturbation(edge, seed, channel_kind, config)
        )
        for pair in _coassignment(_partition(retained)):
            counts[pair] += 1
    return counts


def _retained_by_perturbation(
    edge: PeerCandidate,
    seed: int,
    channel_kind: str,
    config: ConsensusPerturbationConfig,
) -> bool:
    material = f"{_CONSENSUS_REVISION}\x1f{channel_kind}\x1f{seed}\x1f" + "\x1f".join(_pair(edge))
    bucket = (
        int.from_bytes(hashlib.sha256(material.encode()).digest()[:8])
        % config.edge_drop_denominator
    )
    return bucket >= config.edge_drop_numerator


def _stable_pair(
    pair: tuple[str, str],
    counts_by_channel: tuple[dict[tuple[str, str], int], dict[tuple[str, str], int]],
    run_count: int,
    evidence_by_channel: tuple[
        dict[tuple[str, str], PeerCandidate], dict[tuple[str, str], PeerCandidate]
    ],
) -> StableConsensusPair:
    direct_counts, support_counts = counts_by_channel
    direct_evidence, support_evidence = evidence_by_channel
    return StableConsensusPair(
        source_genre_id=pair[0],
        target_genre_id=pair[1],
        direct_coassignment_frequency=direct_counts[pair] / run_count,
        support_coassignment_frequency=support_counts[pair] / run_count,
        direct_coassigned_runs=direct_counts[pair],
        support_coassigned_runs=support_counts[pair],
        direct_source_evidence=_pair_evidence(direct_evidence.get(pair)),
        support_source_evidence=_pair_evidence(support_evidence.get(pair)),
    )


def _pair_evidence(edge: PeerCandidate | None) -> ChannelPairEvidence | None:
    if edge is None:
        return None
    return ChannelPairEvidence(
        score=edge.score, shared_supported_artist_count=edge.shared_supported_artist_count
    )


def _ego_affiliations(stable_pairs: tuple[tuple[str, str], ...]) -> tuple[EgoAffiliation, ...]:
    peers: dict[str, set[str]] = defaultdict(set)
    for left, right in stable_pairs:
        peers[left].add(right)
        peers[right].add(left)
    return tuple(
        EgoAffiliation(
            genre_id=genre,
            member_genre_ids=tuple(sorted({genre, *related})),
            stable_peer_genre_ids=tuple(sorted(related)),
        )
        for genre, related in sorted(peers.items())
    )


def _endpoint_ids(edges: tuple[PeerCandidate, ...]) -> set[str]:
    return {edge.source_genre_id for edge in edges} | {edge.target_genre_id for edge in edges}


def _abstention_reason(
    seed_id: str, direct_endpoints: set[str], support_endpoints: set[str]
) -> Literal[
    "no_direct_candidate_endpoint",
    "no_support_candidate_endpoint",
    "no_cross_channel_stable_coassignment",
]:
    if seed_id not in direct_endpoints:
        return "no_direct_candidate_endpoint"
    if seed_id not in support_endpoints:
        return "no_support_candidate_endpoint"
    return "no_cross_channel_stable_coassignment"


def _edges_from_pairs(pairs: tuple[tuple[str, str], ...]) -> tuple[PeerCandidate, ...]:
    return tuple(
        PeerCandidate(
            source_genre_id=left,
            target_genre_id=right,
            score=1.0,
            shared_supported_artist_count=1,
        )
        for left, right in pairs
    )


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _logical_sha256(value: dict[str, object]) -> str:
    payload = {key: item for key, item in value.items() if key != "output_sha256"}
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def _replay_sha256(
    direct: ArtifactBinding,
    support: ArtifactBinding,
    reconciliation_bytes_sha256: str,
    reconciliation_logical_sha256: str,
    config: ConsensusPerturbationConfig,
) -> str:
    return hashlib.sha256(
        json.dumps(
            {
                "revision": _CONSENSUS_REVISION,
                "direct_input": direct.model_dump(mode="json"),
                "support_input": support.model_dump(mode="json"),
                "seed_reconciliation_bytes_sha256": reconciliation_bytes_sha256,
                "seed_reconciliation_logical_sha256": reconciliation_logical_sha256,
                "perturbation": config.model_dump(mode="json"),
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


def _corroborated_artifact(
    direct: ChannelInput,
    support: ChannelInput,
    core: tuple[PeerCandidate, ...],
    combined: set[tuple[str, str]],
    communities: tuple[tuple[str, ...], ...],
) -> CorroboratedPeerAudit:
    covered = sum(len(group) for group in communities)
    base = CorroboratedPeerAudit(
        direct_input_sha256=direct.output_sha256,
        support_input_sha256=support.output_sha256,
        corroborated_edge_count=len(core),
        covered_seed_count=covered,
        component_count=len(_components(core)),
        largest_partition_size=max(map(len, communities), default=0),
        direct_ablation_coassignment=_jaccard(
            combined, _coassignment(_partition(direct.candidates))
        ),
        support_ablation_coassignment=_jaccard(
            combined, _coassignment(_partition(support.candidates))
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
    direct: tuple[PeerCandidate, ...],
    support: tuple[PeerCandidate, ...],
    shared: GridMinimum,
    score: float,
) -> CoreMetric:
    edges = direct + support
    selected = tuple(
        edge
        for edge in edges
        if edge.shared_supported_artist_count >= shared and edge.score >= score
    )
    components = _components(selected)
    covered = sum(len(component) for component in components)
    largest = max((len(component) for component in components), default=0)
    communities = _partition(selected)
    labels = {node: index for index, community in enumerate(communities) for node in community}
    direct_pairs = _coassignment(_partition(_select(direct, shared, score)))
    support_pairs = _coassignment(_partition(_select(support, shared, score)))
    combined_pairs = _coassignment(communities)
    return CoreMetric(
        min_shared_artists=shared,
        min_jaccard=score,
        edge_count=len(selected),
        covered_seed_count=covered,
        component_count=len(components),
        giant_component_fraction=largest / covered if covered else 0.0,
        largest_component_size=largest,
        exact_pair_stability=_stability(selected),
        direct_ablation_coassignment=_jaccard(combined_pairs, direct_pairs),
        support_ablation_coassignment=_jaccard(combined_pairs, support_pairs),
        communities=communities,
        cross_community_edge_count=sum(
            labels.get(edge.source_genre_id) != labels.get(edge.target_genre_id)
            for edge in selected
        ),
    )


def _select(
    edges: tuple[PeerCandidate, ...], shared: int, score: float
) -> tuple[PeerCandidate, ...]:
    return tuple(
        edge
        for edge in edges
        if edge.shared_supported_artist_count >= shared and edge.score >= score
    )


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


def _split_component(
    nodes: tuple[str, ...], edges: tuple[PeerCandidate, ...]
) -> list[tuple[str, ...]]:
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
    if edge.source_genre_id <= edge.target_genre_id:
        return edge.source_genre_id, edge.target_genre_id
    return edge.target_genre_id, edge.source_genre_id


def _hash(artifact: FrozenModel) -> str:
    payload = artifact.model_dump(mode="json", exclude={"output_sha256"})
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
