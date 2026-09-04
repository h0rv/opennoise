"""Build exact, same-scope map acceptance evidence from public artifacts."""

from __future__ import annotations

import json
import math
from hashlib import sha256
from typing import TYPE_CHECKING

from musix.models.production_qa import (
    ProductionMapAcceptanceInput,
    ProductionMapCoordinate,
    ProductionMapEligibleSet,
    ProductionMapLabelBox,
    ProductionMapLod,
    ProductionMapPresentationParent,
    ProductionMapSimilarityEvidence,
    hash_eligible_sets,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from musix.models.modeling import GenreNeighbor, PublicModelArtifact
    from musix.models.production import ProductionMapArtifact

_ELIGIBILITY_RULE_VERSION = "all-mapped-genres-except-query-v1"
_PROFILE_KIND = "one_hop"
_SIMILARITY_METRIC = "weighted_jaccard"
_MAX_REPORTED_NEIGHBORS = 25


def canonical_baseline_positions(
    source_model: PublicModelArtifact, genre_ids: Iterable[str]
) -> dict[str, tuple[float, float]]:
    """Cover every production genre with the default lens plus a fixed fallback grid.

    The public one-hop lens can legitimately leave sparse genres unplaced.  A
    production comparison must still use one identical population for the
    candidate and baseline, so each missing genre gets a deterministic fallback
    position.  This is a declared comparison baseline, not a claim about a
    historical Every Noise coordinate.
    """
    source_layout = next(layout for layout in source_model.layouts if layout.is_default)
    expected = tuple(sorted(genre_ids))
    positions = {
        coordinate.genre_id: (float(coordinate.x), float(coordinate.y))
        for coordinate in source_layout.coordinates
        if coordinate.genre_id in expected
    }
    unresolved = tuple(genre_id for genre_id in expected if genre_id not in positions)
    if unresolved:
        columns = math.ceil(math.sqrt(len(unresolved)))
        rows = math.ceil(len(unresolved) / columns)
        for index, genre_id in enumerate(unresolved):
            positions[genre_id] = (
                0.02 + 0.96 * (index % columns + 0.5) / columns,
                0.02 + 0.96 * (index // columns + 0.5) / rows,
            )
    return positions


def _canonical_hash(value: object) -> str:
    return sha256(
        json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()


def _coordinate_hash(coordinates: Mapping[str, tuple[float, float]]) -> str:
    return _canonical_hash(
        [
            {"entity_id": genre_id, "x": x, "y": y}
            for genre_id, (x, y) in sorted(coordinates.items())
        ]
    )


def _source_neighbors(
    source_model: PublicModelArtifact,
    mapped_ids: set[str],
    *,
    limit: int,
) -> dict[str, tuple[str, ...]]:
    """Read one exact ranked source relation, including genres with no neighbors."""
    grouped: dict[str, list[GenreNeighbor]] = {genre_id: [] for genre_id in mapped_ids}
    records: list[dict[str, object]] = []
    for item in source_model.neighbors:
        if (
            item.profile_kind != _PROFILE_KIND
            or item.metric != _SIMILARITY_METRIC
            or item.rank > limit
            or item.genre_id not in mapped_ids
            or item.neighbor_genre_id not in mapped_ids
        ):
            continue
        grouped[item.genre_id].append(item)
        records.append(
            {
                "genre_id": item.genre_id,
                "neighbor_genre_id": item.neighbor_genre_id,
                "rank": item.rank,
                "score": float(item.score),
                "shared_artist_count": item.shared_artist_count,
            }
        )
    return {
        genre_id: tuple(
            item.neighbor_genre_id
            for item in sorted(
                values,
                key=lambda item: (item.rank, -float(item.score), item.neighbor_genre_id),
            )
        )
        for genre_id, values in grouped.items()
    }


def _neighbor_hash(source_model: PublicModelArtifact, mapped_ids: set[str]) -> str:
    """Hash the exact top-25 source records, not an unrelated model envelope."""
    records = [
        {
            "genre_id": item.genre_id,
            "neighbor_genre_id": item.neighbor_genre_id,
            "rank": item.rank,
            "score": float(item.score),
            "shared_artist_count": item.shared_artist_count,
        }
        for item in source_model.neighbors
        if item.profile_kind == _PROFILE_KIND
        and item.metric == _SIMILARITY_METRIC
        and item.rank <= _MAX_REPORTED_NEIGHBORS
        and item.genre_id in mapped_ids
        and item.neighbor_genre_id in mapped_ids
    ]
    return _canonical_hash(
        sorted(records, key=lambda record: (str(record["genre_id"]), int(record["rank"])))
    )


def _mean_recall(
    coordinates: Mapping[str, tuple[float, float]], reference: Mapping[str, tuple[str, ...]]
) -> float:
    """Average recall across every mapped query; zero-source queries contribute zero."""
    mapped_ids = tuple(sorted(coordinates))
    recalls: list[float] = []
    for query_id in mapped_ids:
        expected = reference[query_id]
        if not expected:
            recalls.append(0.0)
            continue
        query_x, query_y = coordinates[query_id]
        observed = sorted(
            (candidate_id for candidate_id in mapped_ids if candidate_id != query_id),
            key=lambda candidate_id: (
                (query_x - coordinates[candidate_id][0]) ** 2
                + (query_y - coordinates[candidate_id][1]) ** 2,
                candidate_id,
            ),
        )[: len(expected)]
        recalls.append(len(set(expected) & set(observed)) / len(expected))
    return sum(recalls) / len(recalls)


def _eligible_sets(
    mapped_ids: tuple[str, ...], reference: Mapping[str, tuple[str, ...]]
) -> tuple[ProductionMapEligibleSet, ...]:
    """Declare the full candidate pool for each query, including zero-source queries."""
    return tuple(
        ProductionMapEligibleSet(
            query_entity_id=query_id,
            eligible_candidate_count=len(mapped_ids) - 1,
            reference_neighbor_count=len(reference[query_id]),
            eligible_candidate_ids_sha256=_canonical_hash(
                tuple(candidate_id for candidate_id in mapped_ids if candidate_id != query_id)
            ),
        )
        for query_id in mapped_ids
    )


def build_production_map_acceptance_evidence(
    artifact: ProductionMapArtifact, source_model: PublicModelArtifact
) -> ProductionMapAcceptanceInput:
    """Emit data-model certification evidence; renderer adds screenshots and interactions.

    The candidate and canonical baseline both evaluate every mapped genre with
    exactly the same source relation and variable eligible candidate sets.  No
    score from a prior report is copied into this record.
    """
    candidate_coordinates = {
        node.genre_id: (float(node.x), float(node.y)) for node in artifact.nodes
    }
    mapped_ids = tuple(sorted(candidate_coordinates))
    mapped_set = set(mapped_ids)
    baseline_coordinates = canonical_baseline_positions(source_model, mapped_ids)
    if set(baseline_coordinates) != mapped_set:
        raise ValueError("canonical baseline does not cover the production coordinate population")
    reference_top_10 = _source_neighbors(source_model, mapped_set, limit=10)
    reference_top_25 = _source_neighbors(source_model, mapped_set, limit=_MAX_REPORTED_NEIGHBORS)
    eligible_sets = _eligible_sets(mapped_ids, reference_top_10)
    eligible_sets_sha256 = hash_eligible_sets(eligible_sets)
    random_top_10 = sum(
        min(10, item.reference_neighbor_count) / item.eligible_candidate_count
        for item in eligible_sets
    ) / len(eligible_sets)
    neighbor_sha256 = _neighbor_hash(source_model, mapped_set)
    explanations = {item.genre_id: item for item in artifact.explanations}
    return ProductionMapAcceptanceInput(
        revision=artifact.revision,
        coordinate_sha256=_coordinate_hash(candidate_coordinates),
        coordinates=tuple(
            ProductionMapCoordinate(entity_id=genre_id, x=x, y=y)
            for genre_id, (x, y) in sorted(candidate_coordinates.items())
        ),
        taxonomy_edges=tuple(
            (edge.source_genre_id, edge.target_genre_id)
            for edge in artifact.edges
            if edge.kind == "taxonomy"
        ),
        presentation_parents=tuple(
            ProductionMapPresentationParent(
                child_id=node.genre_id,
                parent_id=node.display_parent_id,
                relation="taxonomy" if node.display_parent_id is not None else "none",
                reason=(
                    explanations[node.genre_id].parent_rule
                    if node.display_parent_id is not None
                    else "no selected taxonomy parent"
                ),
            )
            for node in artifact.nodes
        ),
        lods=tuple(
            ProductionMapLod(
                level=lod.level,
                visible_entity_ids=lod.visible_node_ids,
                desktop_labels=tuple(
                    ProductionMapLabelBox(
                        entity_id=label.genre_id,
                        min_x=float(label.x),
                        min_y=float(label.y),
                        max_x=float(label.x + label.width),
                        max_y=float(label.y + label.height),
                    )
                    for label in lod.desktop_labels
                    if label.shown
                ),
                mobile_labels=tuple(
                    ProductionMapLabelBox(
                        entity_id=label.genre_id,
                        min_x=float(label.x),
                        min_y=float(label.y),
                        max_x=float(label.x + label.width),
                        max_y=float(label.y + label.height),
                    )
                    for label in lod.mobile_labels
                    if label.shown
                ),
            )
            for lod in artifact.lods
        ),
        similarity=ProductionMapSimilarityEvidence(
            source_model_sha256=source_model.output_sha256,
            source_neighbor_sha256=neighbor_sha256,
            candidate_coordinate_sha256=_coordinate_hash(candidate_coordinates),
            canonical_baseline_model_sha256=source_model.output_sha256,
            canonical_baseline_neighbor_sha256=neighbor_sha256,
            canonical_baseline_coordinate_sha256=_coordinate_hash(baseline_coordinates),
            eligibility_rule_version=_ELIGIBILITY_RULE_VERSION,
            eligible_sets_sha256=eligible_sets_sha256,
            canonical_baseline_eligibility_rule_version=_ELIGIBILITY_RULE_VERSION,
            canonical_baseline_eligible_sets_sha256=eligible_sets_sha256,
            evaluated_entity_count=len(mapped_ids),
            eligible_sets=eligible_sets,
            top_10_recall=_mean_recall(candidate_coordinates, reference_top_10),
            top_25_recall=_mean_recall(candidate_coordinates, reference_top_25),
            canonical_baseline_top_10_recall=_mean_recall(baseline_coordinates, reference_top_10),
            random_top_10_recall=random_top_10,
        ),
    )
