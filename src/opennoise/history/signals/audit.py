"""Bounded quality audit for the local H3 artist-membership signal graph."""

from __future__ import annotations

import sqlite3
import unicodedata
from collections import Counter, defaultdict
from typing import TYPE_CHECKING, Literal

from pydantic import Field

from opennoise.models import FrozenModel
from opennoise.models.historical_signal import (  # noqa: TC001 - Pydantic resolves these annotations.
    HistoricalSignalArtifact,
    HistoricalSignalNeighbor,
    HistoricalSignalNode,
)
from opennoise.types import Sha256  # noqa: TC001 - Pydantic resolves this annotation.

if TYPE_CHECKING:
    from pathlib import Path

_HUB_CUTOFF = 32
_EXAMPLE_NAMES = ("rock", "black metal", "cumbia", "japanese alternative rock")


class AuditBucket(FrozenModel):
    """A small bounded histogram bucket."""

    label: str = Field(min_length=1, max_length=100)
    count: int = Field(ge=0)


class HistoricalSignalMembershipAudit(FrozenModel):
    """Coverage and degree facts from source-scoped H3 membership rows."""

    stored_membership_count: int = Field(ge=0)
    distinct_artist_count: int = Field(ge=0)
    member_genre_count: int = Field(ge=0)
    zero_coverage_genres: tuple[str, ...] = Field(max_length=20)
    genre_membership_degree: tuple[AuditBucket, ...] = Field(max_length=20)
    artist_genre_degree: tuple[AuditBucket, ...] = Field(max_length=20)
    artists_above_hub_cutoff: int = Field(ge=0)
    memberships_excluded_by_hub_cutoff: int = Field(ge=0)


class HistoricalSignalComponentAudit(FrozenModel):
    """Explain connectivity without publishing graph-wide membership lists."""

    component_count: int = Field(ge=0)
    isolate_count: int = Field(ge=0)
    largest_component_size: int = Field(ge=0)
    component_size_distribution: tuple[AuditBucket, ...] = Field(max_length=20)


class HistoricalSignalKnnAudit(FrozenModel):
    """Summarize directed H3 kNN edges and reciprocity."""

    directed_edge_count: int = Field(ge=0)
    reciprocal_pair_count: int = Field(ge=0)
    one_way_edge_count: int = Field(ge=0)
    mutual_directed_edge_fraction: float = Field(ge=0.0, le=1.0)
    rank_distribution: tuple[AuditBucket, ...] = Field(max_length=50)


class HistoricalSignalExample(FrozenModel):
    """One compact H3-only evidence explanation for a selected genre style."""

    genre_id: str = Field(min_length=1, max_length=200)
    genre_name: str = Field(min_length=1, max_length=500)
    membership_count: int = Field(ge=0)
    neighbor_genre_id: str | None = Field(default=None, max_length=200)
    neighbor_genre_name: str | None = Field(default=None, max_length=500)
    neighbor_weighted_jaccard: float | None = Field(default=None, ge=0.0, le=1.0)
    shared_artist_count: int = Field(ge=0)
    shared_artist_id_sample: tuple[str, ...] = Field(max_length=3)


class HistoricalSignalAuditReport(FrozenModel):
    """A no-H2-input audit report designed for review rather than data export."""

    revision: Literal["historical-signal-audit-v1"] = "historical-signal-audit-v1"
    source_signal_artifact_sha256: Sha256
    h3_artifact_sha256: Sha256
    coordinate_oracle_accessed: Literal[False] = False
    membership: HistoricalSignalMembershipAudit
    components: HistoricalSignalComponentAudit
    knn: HistoricalSignalKnnAudit
    duplicate_genre_id_count: int = Field(ge=0)
    normalized_duplicate_name_count: int = Field(ge=0)
    examples: tuple[HistoricalSignalExample, ...] = Field(max_length=len(_EXAMPLE_NAMES))


def audit_historical_signal(
    artifact: HistoricalSignalArtifact,
    membership_database: Path,
) -> HistoricalSignalAuditReport:
    """Audit H3 membership and kNN evidence without accessing H2 coordinate evaluation."""
    artist_degrees = _artist_degrees(membership_database, artifact.inputs.h3_artifact_sha256)
    membership = _membership_audit(artifact, artist_degrees)
    nodes_by_id: dict[str, HistoricalSignalNode] = {node.genre_id: node for node in artifact.nodes}
    return HistoricalSignalAuditReport(
        source_signal_artifact_sha256=artifact.quality.artifact_sha256,
        h3_artifact_sha256=artifact.inputs.h3_artifact_sha256,
        membership=membership,
        components=_component_audit(artifact),
        knn=_knn_audit(artifact),
        duplicate_genre_id_count=len(artifact.nodes) - len(nodes_by_id),
        normalized_duplicate_name_count=_normalized_duplicate_names(artifact),
        examples=_examples(artifact, membership_database, nodes_by_id),
    )


def _artist_degrees(database_path: Path, source_hash: str) -> dict[str, int]:
    query = """
        SELECT source_artist_id, count(DISTINCT genre_id)
        FROM historical_genre_artist_observations
        WHERE observation_role = 'genre_page_member'
          AND source_artifact_sha256 = ?
          AND source_artist_id IS NOT NULL
        GROUP BY source_artist_id
    """
    with sqlite3.connect(f"file:{database_path}?mode=ro", uri=True) as connection:
        rows = connection.execute(query, (source_hash,))
        return {str(artist_id): int(degree) for artist_id, degree in rows}


def _membership_audit(
    artifact: HistoricalSignalArtifact, artist_degrees: dict[str, int]
) -> HistoricalSignalMembershipAudit:
    node_degrees = [node.membership_count for node in artifact.nodes]
    zero_coverage = tuple(sorted(node.name for node in artifact.nodes if not node.membership_count))
    excluded_memberships = sum(degree for degree in artist_degrees.values() if degree > _HUB_CUTOFF)
    return HistoricalSignalMembershipAudit(
        stored_membership_count=artifact.inputs.membership_count,
        distinct_artist_count=len(artist_degrees),
        member_genre_count=sum(degree > 0 for degree in node_degrees),
        zero_coverage_genres=zero_coverage,
        genre_membership_degree=_histogram(node_degrees, (0, 1, 10, 25, 50)),
        artist_genre_degree=_histogram(list(artist_degrees.values()), (1, 2, 5, 10, 32)),
        artists_above_hub_cutoff=sum(degree > _HUB_CUTOFF for degree in artist_degrees.values()),
        memberships_excluded_by_hub_cutoff=excluded_memberships,
    )


def _component_audit(artifact: HistoricalSignalArtifact) -> HistoricalSignalComponentAudit:
    sizes = Counter(node.component_id for node in artifact.nodes)
    values = list(sizes.values())
    return HistoricalSignalComponentAudit(
        component_count=len(sizes),
        isolate_count=sum(size == 1 for size in values),
        largest_component_size=max(values, default=0),
        component_size_distribution=_histogram(values, (1, 2, 5, 10, 100)),
    )


def _knn_audit(artifact: HistoricalSignalArtifact) -> HistoricalSignalKnnAudit:
    directed = {(edge.genre_id, edge.neighbor_genre_id) for edge in artifact.neighbors}
    reciprocal_pairs = {
        tuple(sorted((source, target)))
        for source, target in directed
        if (target, source) in directed
    }
    mutual_directed = len(reciprocal_pairs) * 2
    return HistoricalSignalKnnAudit(
        directed_edge_count=len(directed),
        reciprocal_pair_count=len(reciprocal_pairs),
        one_way_edge_count=len(directed) - mutual_directed,
        mutual_directed_edge_fraction=round(mutual_directed / len(directed), 12)
        if directed
        else 0.0,
        rank_distribution=_histogram([edge.rank for edge in artifact.neighbors], (1, 5, 10, 20)),
    )


def _examples(
    artifact: HistoricalSignalArtifact,
    database_path: Path,
    nodes_by_id: dict[str, HistoricalSignalNode],
) -> tuple[HistoricalSignalExample, ...]:
    name_to_node = {node.name.casefold(): node for node in artifact.nodes}
    neighbors_by_genre: dict[str, list[HistoricalSignalNeighbor]] = defaultdict(list)
    for edge in artifact.neighbors:
        neighbors_by_genre[edge.genre_id].append(edge)
    return tuple(
        _example(
            node=name_to_node[name],
            neighbor=min(
                neighbors_by_genre[name_to_node[name].genre_id], key=lambda edge: edge.rank
            ),
            nodes_by_id=nodes_by_id,
            database_path=database_path,
            source_hash=artifact.inputs.h3_artifact_sha256,
        )
        for name in _EXAMPLE_NAMES
        if name in name_to_node and neighbors_by_genre[name_to_node[name].genre_id]
    )


def _example(
    *,
    node: HistoricalSignalNode,
    neighbor: HistoricalSignalNeighbor,
    nodes_by_id: dict[str, HistoricalSignalNode],
    database_path: Path,
    source_hash: str,
) -> HistoricalSignalExample:
    """Use only three lexically stable shared source IDs, never an artist export."""
    node_name = node.name
    neighbor_id = neighbor.neighbor_genre_id
    neighbor_node = nodes_by_id[neighbor_id]
    samples = _shared_artist_sample(database_path, node_name, neighbor_node.name, source_hash)
    return HistoricalSignalExample(
        genre_id=node.genre_id,
        genre_name=node_name,
        membership_count=node.membership_count,
        neighbor_genre_id=neighbor_id,
        neighbor_genre_name=neighbor_node.name,
        neighbor_weighted_jaccard=neighbor.weighted_jaccard,
        shared_artist_count=neighbor.shared_artist_count,
        shared_artist_id_sample=samples,
    )


def _shared_artist_sample(
    database_path: Path, left_name: str, right_name: str, source_hash: str
) -> tuple[str, ...]:
    query = """
        SELECT left_observation.source_artist_id
        FROM historical_genre_artist_observations AS left_observation
        JOIN genres AS left_genre ON left_genre.id = left_observation.genre_id
        JOIN historical_genre_artist_observations AS right_observation
          ON right_observation.source_artist_id = left_observation.source_artist_id
        JOIN genres AS right_genre ON right_genre.id = right_observation.genre_id
        WHERE left_genre.name = ? COLLATE NOCASE
          AND right_genre.name = ? COLLATE NOCASE
          AND left_observation.observation_role = 'genre_page_member'
          AND right_observation.observation_role = 'genre_page_member'
          AND left_observation.source_artifact_sha256 = ?
          AND right_observation.source_artifact_sha256 = ?
        ORDER BY left_observation.source_artist_id
        LIMIT 3
    """
    with sqlite3.connect(f"file:{database_path}?mode=ro", uri=True) as connection:
        rows = connection.execute(query, (left_name, right_name, source_hash, source_hash))
        return tuple(str(row[0]) for row in rows)


def _normalized_duplicate_names(artifact: HistoricalSignalArtifact) -> int:
    names = [
        " ".join(unicodedata.normalize("NFKC", node.name).casefold().split())
        for node in artifact.nodes
    ]
    return len(names) - len(set(names))


def _histogram(values: list[int], bounds: tuple[int, ...]) -> tuple[AuditBucket, ...]:
    """Return disjoint bounded buckets with an explicit final tail."""
    result: list[AuditBucket] = []
    for index, lower in enumerate(bounds):
        upper = bounds[index + 1] - 1 if index + 1 < len(bounds) else None
        label = f"{lower}+" if upper is None else f"{lower}-{upper}"
        result.append(
            AuditBucket(
                label=label,
                count=sum(value >= lower and (upper is None or value <= upper) for value in values),
            )
        )
    return tuple(result)
