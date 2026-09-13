"""Project stable consensus peers and factual taxonomy into an abstention-preserving map."""

from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Literal

from pydantic import Field

from opennoise.common import canonical_json, sha256_file, sha256_hex, write_atomic_bytes
from opennoise.ml.layout_lenses import (
    build_weighted_community_spectral_coordinates,
    weighted_spectral_quality,
)
from opennoise.models import FrozenModel
from opennoise.peers.audit.strength_aware_peer_audit import (
    ConsensusAbstention,
    ConsensusMicroNeighborhoodAudit,
)
from opennoise.taxonomy.relations.expansion import TaxonomyRelationExpansionArtifact

if TYPE_CHECKING:
    from pathlib import Path

_REVISION: Final = "consensus-semantic-projection-v1"
_SEED_COUNT: Final = 6_291
_LOD_BUDGETS: Final[tuple[int, ...]] = (48, 240, 480, 958)


class ConsensusSemanticProjectionError(ValueError):
    """A sealed input cannot support this local-only projection."""


class ProjectionInputBinding(FrozenModel):
    """Byte and logical identity of one construction input."""

    role: Literal["consensus_micro_neighborhoods", "exact_qid_taxonomy"]
    byte_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    byte_count: int = Field(gt=0)
    logical_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class ConsensusSemanticProjectionConfig(FrozenModel):
    """Fixed layout and LOD policy for the eligible consensus cohort."""

    layout_algorithm: Literal["weighted_community_spectral_coordinates"] = (
        "weighted_community_spectral_coordinates"
    )
    community_seed: Literal[0] = 0
    maximum_community_iterations: Literal[100] = 100
    node_sort: Literal["descending_degree_then_lexical_id"] = "descending_degree_then_lexical_id"
    lod_budgets: tuple[Literal[48], Literal[240], Literal[480], Literal[958]] = _LOD_BUDGETS


class ConsensusSemanticNode(FrozenModel):
    """One placed eligible genre, with a deterministic semantic-zoom rank."""

    genre_id: str = Field(min_length=1)
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    community_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    degree: int = Field(ge=0)
    label_rank: int = Field(ge=1)
    lod_min: Literal[0, 1, 2, 3]


class ConsensusSemanticEdge(FrozenModel):
    """An unpromoted stable peer or exact factual taxonomy relation."""

    source_genre_id: str = Field(min_length=1)
    target_genre_id: str = Field(min_length=1)
    kind: Literal["stable_consensus_peer", "accepted_factual_taxonomy"]


class ConsensusSemanticCommunity(FrozenModel):
    """A disjoint layout component used only for deterministic local packing."""

    community_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    member_genre_ids: tuple[str, ...] = Field(min_length=1)
    stable_peer_edge_count: int = Field(ge=0)
    factual_taxonomy_edge_count: int = Field(ge=0)


class ConsensusSemanticCoverage(FrozenModel):
    """Separate placed consensus evidence from explicit, unplaced abstentions."""

    covered_seed_count: Literal[6291] = _SEED_COUNT
    eligible_placed_seed_count: int = Field(ge=0, le=_SEED_COUNT)
    explicit_unplaced_abstention_count: int = Field(ge=0, le=_SEED_COUNT)
    stable_peer_edge_count: int = Field(ge=0)
    accepted_factual_taxonomy_edge_count: int = Field(ge=0)
    community_count: int = Field(ge=1)


class ConsensusSemanticLayoutQuality(FrozenModel):
    """Replay diagnostics against the weighted stable-peer/factual input graph."""

    neighbors_per_genre: Literal[10] = 10
    input_weighted_edge_count: int = Field(ge=0)
    layout_weighted_edge_count: int = Field(ge=0)
    mean_knn_preservation: float = Field(ge=0, le=1)
    mutual_neighbor_fraction: float = Field(ge=0, le=1)
    weighted_mean_edge_distance: float = Field(ge=0)
    community_iterations: int = Field(ge=0)
    community_converged: bool


class ConsensusSemanticProjection(FrozenModel):
    """A source-neutral eligible-cohort map; it makes no full-corpus placement claim."""

    revision: Literal["consensus-semantic-projection-v1"] = _REVISION
    scope: Literal["local_research_non_production"] = "local_research_non_production"
    historical_inputs_used_for_construction: Literal[False] = False
    historical_coordinates_read: Literal[False] = False
    historical_memberships_read: Literal[False] = False
    historical_neighbors_read: Literal[False] = False
    inputs: tuple[ProjectionInputBinding, ProjectionInputBinding]
    config: ConsensusSemanticProjectionConfig
    coverage: ConsensusSemanticCoverage
    layout_quality: ConsensusSemanticLayoutQuality
    nodes: tuple[ConsensusSemanticNode, ...]
    edges: tuple[ConsensusSemanticEdge, ...]
    communities: tuple[ConsensusSemanticCommunity, ...]
    unplaced_abstentions: tuple[ConsensusAbstention, ...]
    output_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class ConsensusSemanticProjectionInputs:
    """The two sealed source-neutral inputs accepted by the projection builder."""

    consensus_path: Path
    exact_qid_taxonomy_path: Path


def build_consensus_semantic_projection(
    inputs: ConsensusSemanticProjectionInputs,
) -> ConsensusSemanticProjection:
    """Build a deterministic layout for eligible consensus seeds only."""
    consensus, consensus_binding = _load_consensus(inputs.consensus_path)
    taxonomy, taxonomy_binding = _load_taxonomy(inputs.exact_qid_taxonomy_path)
    eligible_ids = {item.genre_id for item in consensus.ego_affiliations}
    abstention_ids = {item.genre_id for item in consensus.abstentions}
    if (
        len(eligible_ids) != consensus.eligible_seed_count
        or len(abstention_ids) != consensus.abstention_count
        or eligible_ids & abstention_ids
        or len(eligible_ids | abstention_ids) != consensus.covered_seed_count
        or consensus.covered_seed_count != _SEED_COUNT
    ):
        raise ConsensusSemanticProjectionError("consensus does not explicitly partition 6291 seeds")
    stable_edges = tuple(
        ConsensusSemanticEdge(
            source_genre_id=item.source_genre_id,
            target_genre_id=item.target_genre_id,
            kind="stable_consensus_peer",
        )
        for item in consensus.stable_pairs
    )
    if len(stable_edges) != consensus.stable_pair_count or any(
        edge.source_genre_id not in eligible_ids or edge.target_genre_id not in eligible_ids
        for edge in stable_edges
    ):
        raise ConsensusSemanticProjectionError(
            "stable peers do not belong to eligible consensus seeds"
        )
    factual_edges = tuple(
        ConsensusSemanticEdge(
            source_genre_id=item.child_seed_id,
            target_genre_id=item.parent_seed_id,
            kind="accepted_factual_taxonomy",
        )
        for item in taxonomy.edges
        if item.disposition == "accepted_factual"
        and item.child_seed_id in eligible_ids
        and item.parent_seed_id in eligible_ids
    )
    weights = _weights(consensus, taxonomy, eligible_ids)
    communities, positions, degrees, quality = _spectral_layout(
        eligible_ids, stable_edges, factual_edges, weights
    )
    node_order = sorted(
        eligible_ids,
        key=lambda genre_id: (
            -len(next(c.member_genre_ids for c in communities if genre_id in c.member_genre_ids)),
            -degrees[genre_id],
            genre_id,
        ),
    )
    nodes = tuple(
        ConsensusSemanticNode(
            genre_id=genre_id,
            x=positions[genre_id][0],
            y=positions[genre_id][1],
            community_id=next(
                c.community_id for c in communities if genre_id in c.member_genre_ids
            ),
            degree=degrees[genre_id],
            label_rank=index,
            lod_min=_lod_min(index),
        )
        for index, genre_id in enumerate(node_order, start=1)
    )
    base = ConsensusSemanticProjection(
        inputs=(consensus_binding, taxonomy_binding),
        config=ConsensusSemanticProjectionConfig(),
        coverage=ConsensusSemanticCoverage(
            eligible_placed_seed_count=len(nodes),
            explicit_unplaced_abstention_count=len(consensus.abstentions),
            stable_peer_edge_count=len(stable_edges),
            accepted_factual_taxonomy_edge_count=len(factual_edges),
            community_count=len(communities),
        ),
        layout_quality=quality,
        nodes=nodes,
        edges=tuple(sorted((*stable_edges, *factual_edges), key=_edge_sort_key)),
        communities=communities,
        unplaced_abstentions=consensus.abstentions,
        output_sha256="0" * 64,
    )
    _verify_projection_shape(base)
    return base.model_copy(update={"output_sha256": _projection_sha256(base)})


def verify_consensus_semantic_projection(projection: ConsensusSemanticProjection) -> None:
    """Fail closed when a persisted projection changes or loses abstention accounting."""
    if projection.output_sha256 != _projection_sha256(projection):
        raise ConsensusSemanticProjectionError("consensus semantic projection hash does not replay")
    _verify_projection_shape(projection)


def write_consensus_semantic_projection(
    path: Path, projection: ConsensusSemanticProjection
) -> None:
    """Atomically write a replay-verified local-only projection."""
    verify_consensus_semantic_projection(projection)
    write_atomic_bytes(path, projection.model_dump_json(indent=2).encode() + b"\n")


def _load_consensus(path: Path) -> tuple[ConsensusMicroNeighborhoodAudit, ProjectionInputBinding]:
    raw = path.read_bytes()
    try:
        consensus = ConsensusMicroNeighborhoodAudit.model_validate_json(raw)
    except (OSError, ValueError) as error:
        raise ConsensusSemanticProjectionError("invalid consensus input") from error
    if _json_output_sha256(raw) != consensus.output_sha256:
        raise ConsensusSemanticProjectionError("consensus logical hash does not replay")
    digest, size = sha256_file(path)
    return consensus, ProjectionInputBinding(
        role="consensus_micro_neighborhoods",
        byte_sha256=digest,
        byte_count=size,
        logical_sha256=consensus.output_sha256,
    )


def _load_taxonomy(path: Path) -> tuple[TaxonomyRelationExpansionArtifact, ProjectionInputBinding]:
    raw = path.read_bytes()
    try:
        taxonomy = TaxonomyRelationExpansionArtifact.model_validate_json(raw)
    except (OSError, ValueError) as error:
        raise ConsensusSemanticProjectionError("invalid exact-QID taxonomy input") from error
    if (
        taxonomy.coverage.seed_count != _SEED_COUNT
        or taxonomy.historical_data_used_for_construction
    ):
        raise ConsensusSemanticProjectionError(
            "taxonomy input is not source-neutral full-seed evidence"
        )
    digest, size = sha256_file(path)
    return taxonomy, ProjectionInputBinding(
        role="exact_qid_taxonomy",
        byte_sha256=digest,
        byte_count=size,
        logical_sha256=taxonomy.output_sha256,
    )


def _weights(
    consensus: ConsensusMicroNeighborhoodAudit,
    taxonomy: TaxonomyRelationExpansionArtifact,
    eligible_ids: set[str],
) -> dict[tuple[str, str], float]:
    """Build positive source-edge weights without treating abstentions as edges."""
    weights: dict[tuple[str, str], float] = {}
    for pair in consensus.stable_pairs:
        key = _pair(pair.source_genre_id, pair.target_genre_id)
        weights[key] = min(pair.direct_coassignment_frequency, pair.support_coassignment_frequency)
    for edge in taxonomy.edges:
        if (
            edge.disposition == "accepted_factual"
            and edge.child_seed_id in eligible_ids
            and edge.parent_seed_id in eligible_ids
        ):
            key = _pair(edge.child_seed_id, edge.parent_seed_id)
            weights[key] = max(weights.get(key, 0.0), 1.0)
    return weights


def _spectral_layout(
    eligible_ids: set[str],
    stable_edges: tuple[ConsensusSemanticEdge, ...],
    factual_edges: tuple[ConsensusSemanticEdge, ...],
    weights: dict[tuple[str, str], float],
) -> tuple[
    tuple[ConsensusSemanticCommunity, ...],
    dict[str, tuple[float, float]],
    dict[str, int],
    ConsensusSemanticLayoutQuality,
]:
    """Reuse the established weighted community spectral layout and its diagnostics."""
    try:
        spectral = build_weighted_community_spectral_coordinates(
            tuple(sorted(eligible_ids)), weights, seed=0, maximum_iterations=100
        )
    except ValueError as error:
        raise ConsensusSemanticProjectionError(
            "eligible consensus graph cannot be spectrally placed"
        ) from error
    quality = weighted_spectral_quality(
        spectral.coordinates,
        weights,
        neighbors_per_genre=10,
        layout_weights=spectral.layout_weights,
    )
    adjacency: dict[str, set[str]] = {genre_id: set() for genre_id in eligible_ids}
    for left, right in weights:
        adjacency[left].add(right)
        adjacency[right].add(left)
    members_by_component: dict[int, list[str]] = defaultdict(list)
    positions = {item.genre_id: (float(item.x), float(item.y)) for item in spectral.coordinates}
    for item in spectral.coordinates:
        members_by_component[item.component].append(item.genre_id)
    communities: list[ConsensusSemanticCommunity] = []
    for _component, members in sorted(members_by_component.items()):
        member_ids = tuple(sorted(members))
        member_set = set(member_ids)
        stable_count = sum(
            edge.source_genre_id in member_set and edge.target_genre_id in member_set
            for edge in stable_edges
        )
        factual_count = sum(
            edge.source_genre_id in member_set and edge.target_genre_id in member_set
            for edge in factual_edges
        )
        communities.append(
            ConsensusSemanticCommunity(
                community_id=sha256_hex("\x1f".join(member_ids).encode()),
                member_genre_ids=member_ids,
                stable_peer_edge_count=stable_count,
                factual_taxonomy_edge_count=factual_count,
            )
        )
    weighted_distance = sum(
        weight * math.dist(positions[left], positions[right])
        for (left, right), weight in weights.items()
    ) / sum(weights.values())
    return (
        tuple(communities),
        positions,
        {genre_id: len(items) for genre_id, items in adjacency.items()},
        ConsensusSemanticLayoutQuality(
            input_weighted_edge_count=len(weights),
            layout_weighted_edge_count=spectral.layout_edge_count,
            mean_knn_preservation=quality.mean_knn_preservation,
            mutual_neighbor_fraction=quality.mutual_neighbor_fraction,
            weighted_mean_edge_distance=round(weighted_distance, 12),
            community_iterations=spectral.iterations,
            community_converged=spectral.converged,
        ),
    )


def _lod_min(rank: int) -> Literal[0, 1, 2, 3]:
    if rank <= _LOD_BUDGETS[0]:
        return 0
    if rank <= _LOD_BUDGETS[1]:
        return 1
    if rank <= _LOD_BUDGETS[2]:
        return 2
    return 3


def _edge_sort_key(edge: ConsensusSemanticEdge) -> tuple[str, str, str]:
    left, right = sorted((edge.source_genre_id, edge.target_genre_id))
    return left, right, edge.kind


def _pair(left: str, right: str) -> tuple[str, str]:
    return (left, right) if left < right else (right, left)


def _verify_projection_shape(projection: ConsensusSemanticProjection) -> None:
    topology = _projection_topology(projection)
    _verify_community_partition(projection, topology)
    _verify_node_metadata(projection, topology)


@dataclass(frozen=True, slots=True)
class _ProjectionTopology:
    node_ids: set[str]
    node_by_id: dict[str, ConsensusSemanticNode]
    community_members: dict[str, set[str]]
    stable_edges: tuple[ConsensusSemanticEdge, ...]
    factual_edges: tuple[ConsensusSemanticEdge, ...]
    neighborhood: dict[str, set[str]]


def _projection_topology(projection: ConsensusSemanticProjection) -> _ProjectionTopology:
    node_ids = {node.genre_id for node in projection.nodes}
    abstention_ids = {item.genre_id for item in projection.unplaced_abstentions}
    community_ids = {community.community_id for community in projection.communities}
    community_members = {
        community.community_id: set(community.member_genre_ids)
        for community in projection.communities
    }
    all_community_members = tuple(
        member for community in projection.communities for member in community.member_genre_ids
    )
    stable_edges = tuple(edge for edge in projection.edges if edge.kind == "stable_consensus_peer")
    factual_edges = tuple(
        edge for edge in projection.edges if edge.kind == "accepted_factual_taxonomy"
    )
    node_by_id = {node.genre_id: node for node in projection.nodes}
    if (
        tuple(binding.role for binding in projection.inputs)
        != ("consensus_micro_neighborhoods", "exact_qid_taxonomy")
        or any(binding.byte_count <= 0 for binding in projection.inputs)
        or len(node_ids) != len(projection.nodes)
        or len(abstention_ids) != len(projection.unplaced_abstentions)
        or node_ids & abstention_ids
        or len(node_ids | abstention_ids) != _SEED_COUNT
        or len(node_ids) != projection.coverage.eligible_placed_seed_count
        or len(abstention_ids) != projection.coverage.explicit_unplaced_abstention_count
        or {node.community_id for node in projection.nodes} != community_ids
        or len(community_ids) != len(projection.communities)
        or len(all_community_members) != len(set(all_community_members))
        or projection.coverage.community_count != len(projection.communities)
        or projection.coverage.stable_peer_edge_count != len(stable_edges)
        or projection.coverage.accepted_factual_taxonomy_edge_count != len(factual_edges)
    ):
        raise ConsensusSemanticProjectionError(
            "projection does not preserve complete placement abstention accounting"
        )
    if any(
        edge.source_genre_id not in node_ids
        or edge.target_genre_id not in node_ids
        or edge.source_genre_id == edge.target_genre_id
        for edge in projection.edges
    ):
        raise ConsensusSemanticProjectionError("projection edge reaches an unplaced abstention")
    neighborhood = {genre_id: set() for genre_id in node_ids}
    for edge in projection.edges:
        neighborhood[edge.source_genre_id].add(edge.target_genre_id)
        neighborhood[edge.target_genre_id].add(edge.source_genre_id)
    return _ProjectionTopology(
        node_ids=node_ids,
        node_by_id=node_by_id,
        community_members=community_members,
        stable_edges=stable_edges,
        factual_edges=factual_edges,
        neighborhood=neighborhood,
    )


def _verify_community_partition(
    projection: ConsensusSemanticProjection, topology: _ProjectionTopology
) -> None:
    all_community_members = {
        member for members in topology.community_members.values() for member in members
    }
    if all_community_members != topology.node_ids or any(
        genre_id not in topology.community_members[node.community_id]
        for genre_id, node in topology.node_by_id.items()
    ):
        raise ConsensusSemanticProjectionError(
            "projection communities do not partition placed nodes"
        )
    if any(
        community.community_id != sha256_hex("\x1f".join(community.member_genre_ids).encode())
        for community in projection.communities
    ):
        raise ConsensusSemanticProjectionError("projection community identifiers do not replay")
    for community in projection.communities:
        members = topology.community_members[community.community_id]
        if community.stable_peer_edge_count != sum(
            edge.source_genre_id in members and edge.target_genre_id in members
            for edge in topology.stable_edges
        ) or community.factual_taxonomy_edge_count != sum(
            edge.source_genre_id in members and edge.target_genre_id in members
            for edge in topology.factual_edges
        ):
            raise ConsensusSemanticProjectionError("projection community edge counts do not replay")


def _verify_node_metadata(
    projection: ConsensusSemanticProjection, topology: _ProjectionTopology
) -> None:
    expected_order = tuple(
        sorted(
            topology.node_ids,
            key=lambda genre_id: (
                -len(topology.community_members[topology.node_by_id[genre_id].community_id]),
                -len(topology.neighborhood[genre_id]),
                genre_id,
            ),
        )
    )
    if expected_order != tuple(node.genre_id for node in projection.nodes):
        raise ConsensusSemanticProjectionError("projection node ordering does not replay")
    if any(node.degree != len(topology.neighborhood[node.genre_id]) for node in projection.nodes):
        raise ConsensusSemanticProjectionError("projection node degree does not replay")
    if tuple(range(1, len(projection.nodes) + 1)) != tuple(
        node.label_rank for node in projection.nodes
    ) or any(node.lod_min != _lod_min(node.label_rank) for node in projection.nodes):
        raise ConsensusSemanticProjectionError(
            "projection label ranks or LOD assignments do not replay"
        )
    edge_keys = {
        (edge.source_genre_id, edge.target_genre_id, edge.kind) for edge in projection.edges
    }
    if len(edge_keys) != len(projection.edges):
        raise ConsensusSemanticProjectionError(
            "projection edges are not unique by directed evidence kind"
        )


def _projection_sha256(projection: ConsensusSemanticProjection) -> str:
    return sha256_hex(canonical_json(projection.model_dump(mode="json", exclude={"output_sha256"})))


def _json_output_sha256(raw: bytes) -> str:
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise TypeError("artifact must be a JSON object")
    payload = {key: item for key, item in value.items() if key != "output_sha256"}
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
