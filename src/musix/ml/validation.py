"""Deterministic public graph experiments and validation."""

import hashlib
import json
import math
import resource
import time
from collections import defaultdict
from itertools import combinations

import numpy as np
from pydantic import BaseModel

from musix.ml.public_graph import build_public_model
from musix.models.modeling import (
    ArtistPairEvidence,
    GenreNeighbor,
    PublicArtifact,
    PublicModelArtifact,
    PublicModelInput,
    PublicModelSettings,
)
from musix.models.validation import (
    CommunityAssignment,
    CommunityExperiment,
    CommunityStability,
    GenreHierarchyEdge,
    GraphValidationArtifact,
    GraphValidationInput,
    GraphValidationSettings,
    NeighborhoodValidation,
    SourceHoldoutValidation,
    TemporalPairWindow,
    TemporalValidation,
    ValidationResources,
)

_MINIMUM_SOURCE_FACETS = 2


def _canonical_bytes(value: BaseModel | dict[str, object]) -> bytes:
    payload = value.model_dump(mode="json") if isinstance(value, BaseModel) else value
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode()


def _sha256(value: BaseModel | dict[str, object]) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _peak_rss_bytes() -> int:
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024


def _aggregate_pairs(windows: tuple[TemporalPairWindow, ...]) -> tuple[ArtistPairEvidence, ...]:
    supports: dict[tuple[str, str], int] = defaultdict(int)
    window_counts: dict[tuple[str, str], int] = defaultdict(int)
    references: dict[tuple[str, str], set[str]] = defaultdict(set)
    for window in windows:
        for pair in window.pairs:
            key = (pair.left_artist_id, pair.right_artist_id)
            supports[key] += pair.listener_day_support
            window_counts[key] += pair.supporting_windows
            references[key].update(pair.evidence_refs)
    return tuple(
        ArtistPairEvidence(
            left_artist_id=key[0],
            right_artist_id=key[1],
            listener_day_support=supports[key],
            supporting_windows=window_counts[key],
            evidence_refs=tuple(sorted(references[key])),
        )
        for key in sorted(supports, key=lambda value: (-supports[value], value))
    )


def _stage_input(
    base: PublicModelInput,
    source_artifacts: tuple[PublicArtifact, ...],
    windows: tuple[TemporalPairWindow, ...],
) -> PublicModelInput:
    artifacts = tuple(artifact for artifact in base.artifacts if artifact.source != "listenbrainz")
    return PublicModelInput(
        artifacts=tuple(
            sorted(
                (*artifacts, *source_artifacts),
                key=lambda artifact: (artifact.source, artifact.snapshot, artifact.artifact_key),
            )
        ),
        genres=base.genres,
        direct_memberships=base.direct_memberships,
        artist_pairs=_aggregate_pairs(windows),
        metadata_candidates=base.metadata_candidates,
    )


def _selected_neighbors(artifact: PublicModelArtifact) -> tuple[GenreNeighbor, ...]:
    return tuple(
        item
        for item in artifact.neighbors
        if item.profile_kind == "one_hop" and item.metric == "weighted_jaccard"
    )


def _weighted_graph(artifact: PublicModelArtifact) -> dict[str, dict[str, float]]:
    result: dict[str, dict[str, float]] = defaultdict(dict)
    for item in _selected_neighbors(artifact):
        current = result[item.genre_id].get(item.neighbor_genre_id, 0.0)
        result[item.genre_id][item.neighbor_genre_id] = max(current, float(item.score))
        reverse = result[item.neighbor_genre_id].get(item.genre_id, 0.0)
        result[item.neighbor_genre_id][item.genre_id] = max(reverse, float(item.score))
    return {genre: dict(sorted(neighbors.items())) for genre, neighbors in sorted(result.items())}


def _tie_key(seed: int, label: str) -> tuple[str, str]:
    digest = hashlib.sha256(f"{seed}\0{label}".encode()).hexdigest()
    return digest, label


def _modularity(graph: dict[str, dict[str, float]], labels: dict[str, str]) -> float:
    total_weight = sum(sum(neighbors.values()) for neighbors in graph.values()) / 2.0
    if total_weight <= 0.0:
        return 0.0
    degrees = {genre: sum(neighbors.values()) for genre, neighbors in graph.items()}
    value = 0.0
    for left, neighbors in graph.items():
        for right, weight in neighbors.items():
            if labels[left] == labels[right]:
                value += weight - degrees[left] * degrees[right] / (2.0 * total_weight)
    return value / (2.0 * total_weight)


def _community_experiment(
    artifact: PublicModelArtifact,
    *,
    seed: int,
    maximum_iterations: int,
) -> CommunityExperiment:
    graph = _weighted_graph(artifact)
    labels = {genre: genre for genre in graph}
    order = sorted(graph, key=lambda genre: _tie_key(seed, genre))
    converged = False
    iterations = 0
    for iteration in range(1, maximum_iterations + 1):
        iterations = iteration
        changed = False
        for genre in order:
            scores: dict[str, float] = defaultdict(float)
            for neighbor, weight in graph[genre].items():
                scores[labels[neighbor]] += weight
            if not scores:
                continue
            best_score = max(scores.values())
            best_label = min(
                (label for label, score in scores.items() if score == best_score),
                key=lambda label: _tie_key(seed, label),
            )
            if best_label != labels[genre]:
                labels[genre] = best_label
                changed = True
        if not changed:
            converged = True
            break
    groups: dict[str, list[str]] = defaultdict(list)
    for genre, label in labels.items():
        groups[label].append(genre)
    canonical = {label: min(members) for label, members in groups.items()}
    assignments = tuple(
        CommunityAssignment(genre_id=genre, community_id=canonical[label])
        for genre, label in sorted(labels.items())
    )
    canonical_labels = {item.genre_id: item.community_id for item in assignments}
    return CommunityExperiment(
        algorithm="seeded_weighted_label_propagation_v1",
        seed=seed,
        iterations=iterations,
        converged=converged,
        community_count=len(set(canonical_labels.values())),
        modularity=round(_modularity(graph, canonical_labels), 12),
        assignments=assignments,
    )


def _coassigned(experiment: CommunityExperiment) -> set[tuple[str, str]]:
    groups: dict[str, list[str]] = defaultdict(list)
    for item in experiment.assignments:
        groups[item.community_id].append(item.genre_id)
    return {pair for members in groups.values() for pair in combinations(sorted(members), 2)}


def _community_stability(experiments: tuple[CommunityExperiment, ...]) -> CommunityStability:
    scores: list[float] = []
    for left, right in combinations(experiments, 2):
        left_pairs = _coassigned(left)
        right_pairs = _coassigned(right)
        union = left_pairs | right_pairs
        scores.append(len(left_pairs & right_pairs) / len(union) if union else 1.0)
    return CommunityStability(
        experiment_count=len(experiments),
        mean_pairwise_coassignment_jaccard=round(sum(scores) / len(scores), 12) if scores else 1.0,
    )


def _euclidean_neighbors(
    artifact: PublicModelArtifact, neighbors_per_genre: int
) -> dict[str, tuple[str, ...]]:
    coordinates = {item.genre_id: (float(item.x), float(item.y)) for item in artifact.coordinates}
    return {
        genre: tuple(
            other
            for _distance, other in sorted(
                (
                    (math.dist(point, other_point), other)
                    for other, other_point in coordinates.items()
                    if other != genre
                ),
                key=lambda item: (item[0], item[1]),
            )[:neighbors_per_genre]
        )
        for genre, point in sorted(coordinates.items())
    }


def _source_neighbors(
    artifact: PublicModelArtifact, neighbors_per_genre: int
) -> dict[str, tuple[str, ...]]:
    grouped: dict[str, list[GenreNeighbor]] = defaultdict(list)
    for item in _selected_neighbors(artifact):
        grouped[item.genre_id].append(item)
    return {
        genre: tuple(
            item.neighbor_genre_id
            for item in sorted(items, key=lambda item: (item.rank, item.neighbor_genre_id))[
                :neighbors_per_genre
            ]
        )
        for genre, items in sorted(grouped.items())
    }


def _neighborhood_validation(
    artifact: PublicModelArtifact,
    hierarchy: tuple[GenreHierarchyEdge, ...],
    neighbors_per_genre: int,
) -> NeighborhoodValidation:
    source = _source_neighbors(artifact, neighbors_per_genre)
    embedded = _euclidean_neighbors(artifact, neighbors_per_genre)
    genres = sorted(source.keys() & embedded.keys())
    preservation: list[float] = []
    for genre in genres:
        denominator = min(neighbors_per_genre, len(source[genre]), len(embedded[genre]))
        if denominator:
            preservation.append(len(set(source[genre]) & set(embedded[genre])) / denominator)
    directed = {(genre, neighbor) for genre, neighbors in source.items() for neighbor in neighbors}
    mutual = sum((right, left) in directed for left, right in directed)
    evaluated_hierarchy = tuple(
        item
        for item in hierarchy
        if item.child_genre_id in source and item.parent_genre_id in source
    )
    hierarchy_hits = sum(
        item.parent_genre_id in source[item.child_genre_id]
        or item.child_genre_id in source[item.parent_genre_id]
        for item in evaluated_hierarchy
    )
    return NeighborhoodValidation(
        neighbors_per_genre=neighbors_per_genre,
        genres_evaluated=len(genres),
        mean_knn_preservation=round(sum(preservation) / len(preservation), 12)
        if preservation
        else 0.0,
        mutual_neighbor_fraction=round(mutual / len(directed), 12) if directed else 0.0,
        hierarchy_edges_evaluated=len(evaluated_hierarchy),
        hierarchy_recall_at_k=round(hierarchy_hits / len(evaluated_hierarchy), 12)
        if evaluated_hierarchy
        else 0.0,
    )


def _neighbor_edges(artifact: PublicModelArtifact) -> set[tuple[str, str]]:
    return {(item.genre_id, item.neighbor_genre_id) for item in _selected_neighbors(artifact)}


def _aligned_coordinate_rms(
    left: PublicModelArtifact, right: PublicModelArtifact
) -> tuple[int, float]:
    left_values = {item.genre_id: (float(item.x), float(item.y)) for item in left.coordinates}
    right_values = {item.genre_id: (float(item.x), float(item.y)) for item in right.coordinates}
    genres = sorted(left_values.keys() & right_values.keys())
    if not genres:
        return 0, 0.0
    left_matrix = np.array([left_values[genre] for genre in genres], dtype=np.float64)
    right_matrix = np.array([right_values[genre] for genre in genres], dtype=np.float64)
    left_matrix -= left_matrix.mean(axis=0)
    right_matrix -= right_matrix.mean(axis=0)
    left_norm = float(np.linalg.norm(left_matrix))
    right_norm = float(np.linalg.norm(right_matrix))
    if left_norm == 0.0 or right_norm == 0.0:
        return len(genres), 0.0
    left_matrix /= left_norm
    right_matrix /= right_norm
    left_vectors, _singular_values, right_vectors = np.linalg.svd(left_matrix.T @ right_matrix)
    rotation = left_vectors @ right_vectors
    aligned = left_matrix @ rotation
    rms = math.sqrt(float(np.mean(np.sum((aligned - right_matrix) ** 2, axis=1))))
    return len(genres), rms


def _temporal_validation(
    left: PublicModelArtifact,
    right: PublicModelArtifact,
    left_window_end: int,
    right_window_end: int,
) -> TemporalValidation:
    left_edges = _neighbor_edges(left)
    right_edges = _neighbor_edges(right)
    union = left_edges | right_edges
    common_genres, coordinate_rms = _aligned_coordinate_rms(left, right)
    return TemporalValidation(
        left_window_end=left_window_end,
        right_window_end=right_window_end,
        common_genres=common_genres,
        directed_neighbor_jaccard=round(len(left_edges & right_edges) / len(union), 12)
        if union
        else 1.0,
        aligned_coordinate_rms=round(coordinate_rms, 12),
    )


def _source_holdout(inputs: PublicModelInput) -> SourceHoldoutValidation:
    facets: dict[str, int] = defaultdict(int)
    for item in inputs.direct_memberships:
        facets[item.facet] += 1
    if len(facets) < _MINIMUM_SOURCE_FACETS:
        only = next(iter(facets), "none")
        return SourceHoldoutValidation(
            status="unavailable",
            reason=f"only one embed-allowed direct facet is present: {only}",
            training_observations=sum(facets.values()),
            held_out_observations=0,
        )
    ordered = sorted(facets.items(), key=lambda item: (-item[1], item[0]))
    return SourceHoldoutValidation(
        status="available",
        reason="two independent embed-allowed direct facets are available for a later held-out run",
        training_observations=ordered[0][1],
        held_out_observations=sum(value for _facet, value in ordered[1:]),
    )


def build_graph_validation(
    inputs: GraphValidationInput,
    model_settings: PublicModelSettings,
    validation_settings: GraphValidationSettings,
) -> GraphValidationArtifact:
    """Build train/validation/test artifacts and validate the frozen test graph."""
    started = time.monotonic()
    base_inputs = inputs.base_inputs
    source_artifacts = inputs.source_artifacts
    windows = inputs.event_windows
    hierarchy = inputs.hierarchy
    if len(base_inputs.genres) > validation_settings.maximum_validation_genres:
        raise ValueError("validation genres exceed the declared quadratic-work limit")
    train_windows = windows[:-2]
    validation_windows = windows[:-1]
    train = build_public_model(
        _stage_input(base_inputs, source_artifacts, train_windows), model_settings
    )
    validation = build_public_model(
        _stage_input(base_inputs, source_artifacts, validation_windows), model_settings
    )
    test_input = _stage_input(base_inputs, source_artifacts, windows)
    test = build_public_model(test_input, model_settings)
    repeated = build_public_model(test_input, model_settings)
    experiments = tuple(
        _community_experiment(
            test,
            seed=seed,
            maximum_iterations=validation_settings.maximum_community_iterations,
        )
        for seed in validation_settings.community_seeds
    )
    temporal = (
        _temporal_validation(
            train,
            validation,
            train_windows[-1].window_end,
            validation_windows[-1].window_end,
        ),
        _temporal_validation(
            validation,
            test,
            validation_windows[-1].window_end,
            windows[-1].window_end,
        ),
    )
    input_payload: dict[str, object] = {
        "base": base_inputs.model_dump(mode="json"),
        "source_artifacts": [artifact.model_dump(mode="json") for artifact in source_artifacts],
        "event_windows": [window.model_dump(mode="json") for window in windows],
        "corpus_run": inputs.corpus_run.model_dump(
            mode="json", exclude={"elapsed_ms", "peak_rss_bytes"}
        ),
        "hierarchy": [edge.model_dump(mode="json") for edge in hierarchy],
    }
    output_payload: dict[str, object] = {
        "communities": [item.model_dump(mode="json") for item in experiments],
        "community_stability": _community_stability(experiments).model_dump(mode="json"),
        "neighborhood": _neighborhood_validation(
            test, hierarchy, validation_settings.neighbors_per_genre
        ).model_dump(mode="json"),
        "temporal": [item.model_dump(mode="json") for item in temporal],
        "source_holdout": _source_holdout(test_input).model_dump(mode="json"),
        "deterministic_rerun": test.output_sha256 == repeated.output_sha256,
        "model_output_sha256": test.output_sha256,
    }
    return GraphValidationArtifact(
        input_sha256=_sha256(input_payload),
        settings_sha256=_sha256(
            {
                "model": model_settings.model_dump(mode="json"),
                "validation": validation_settings.model_dump(mode="json"),
            }
        ),
        output_sha256=_sha256(output_payload),
        export_allowed=test.export_allowed,
        source_artifacts=source_artifacts,
        event_windows=len(windows),
        corpus_run=inputs.corpus_run,
        hierarchy_edges=len(hierarchy),
        communities=experiments,
        community_stability=_community_stability(experiments),
        neighborhood=_neighborhood_validation(
            test, hierarchy, validation_settings.neighbors_per_genre
        ),
        temporal=temporal,
        source_holdout=_source_holdout(test_input),
        deterministic_rerun=test.output_sha256 == repeated.output_sha256,
        model_output_sha256=test.output_sha256,
        resources=ValidationResources(
            elapsed_ms=round((time.monotonic() - started) * 1_000),
            peak_rss_bytes=_peak_rss_bytes(),
            input_database_bytes=inputs.input_database_bytes,
            input_artifact_bytes=inputs.input_artifact_bytes,
        ),
    )
