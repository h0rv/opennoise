"""Build independently versioned, bounded genre layout lenses."""

import hashlib
import json
import math
import resource
import time
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np
from scipy import sparse
from scipy.linalg import eigh
from scipy.sparse.csgraph import connected_components, laplacian
from scipy.sparse.linalg import eigsh
from scipy.spatial import KDTree

from musix.models.modeling import (
    CommunityLayoutResult,
    GenreCoordinate,
    GenreHierarchyEdge,
    GenreNeighbor,
    LayoutInputKind,
    LayoutLens,
    LayoutLensKey,
    LayoutMethod,
    LayoutMetric,
    LayoutQuality,
    LayoutStability,
    ModelResources,
    ProfileKind,
    PublicModelSettings,
    UnplacedGenre,
    UnplacedReason,
)

_DENSE_EIGEN_LIMIT = 64
_PAIR_COMPONENT_SIZE = 2
_MINIMUM_NEIGHBOR_SET = 2
_SPECTRAL_SEED = 0

type EdgeWeights = dict[tuple[str, str], float]


@dataclass(frozen=True, slots=True)
class _QualityContext:
    layout_weights: Mapping[tuple[str, str], float]
    input_weights: Mapping[tuple[str, str], float]
    neighbors_per_genre: int
    one_hop_weights: Mapping[tuple[str, str], float] | None


def _edge_key(left: str, right: str) -> tuple[str, str]:
    return (left, right) if left < right else (right, left)


def _canonical_sha256(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def _peak_rss_bytes() -> int:
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1_024


def _fix_axis_sign(values: np.ndarray) -> np.ndarray:
    anchor = int(np.argmax(np.abs(values)))
    return -values if values[anchor] < 0.0 else values


def _scale_axis(values: np.ndarray) -> np.ndarray:
    minimum = float(values.min())
    maximum = float(values.max())
    if maximum == minimum:
        return np.full(values.shape, 0.5, dtype=np.float64)
    return (values - minimum) / (maximum - minimum)


def _component_coordinates(adjacency: sparse.csr_matrix) -> tuple[np.ndarray, np.ndarray]:
    count = adjacency.shape[0]
    if count == 1:
        return np.array([0.5]), np.array([0.5])
    if count == _PAIR_COMPONENT_SIZE:
        return np.array([0.0, 1.0]), np.array([0.5, 0.5])
    graph_laplacian = laplacian(adjacency, normed=True)
    if count <= _DENSE_EIGEN_LIMIT:
        _values, vectors = eigh(graph_laplacian.toarray(), subset_by_index=(0, 2))
    else:
        _values, vectors = eigsh(
            graph_laplacian,
            k=3,
            which="SM",
            tol=1e-10,
            v0=np.linspace(1.0, 2.0, count, dtype=np.float64),
        )
    return (
        _scale_axis(_fix_axis_sign(vectors[:, 1])),
        _scale_axis(_fix_axis_sign(vectors[:, 2])),
    )


def _coordinates(
    genres: tuple[str, ...], weights: Mapping[tuple[str, str], float]
) -> tuple[GenreCoordinate, ...]:
    if not genres:
        return ()
    index = {genre: position for position, genre in enumerate(genres)}
    rows: list[int] = []
    columns: list[int] = []
    values: list[float] = []
    for (left_genre, right_genre), value in sorted(weights.items()):
        left = index[left_genre]
        right = index[right_genre]
        rows.extend((left, right))
        columns.extend((right, left))
        values.extend((value, value))
    adjacency = sparse.csr_matrix((values, (rows, columns)), shape=(len(genres), len(genres)))
    component_count, labels = connected_components(adjacency, directed=False, return_labels=True)
    ordered_components = sorted(
        range(component_count),
        key=lambda component: (
            -int(np.count_nonzero(labels == component)),
            min(genres[index] for index in np.flatnonzero(labels == component)),
        ),
    )
    grid_width = math.ceil(math.sqrt(component_count))
    cell_scale = 0.8 / grid_width
    result: list[GenreCoordinate] = []
    for published_component, component in enumerate(ordered_components):
        selected = np.flatnonzero(labels == component)
        local = adjacency[selected][:, selected].tocsr()
        x, y = _component_coordinates(local)
        column = published_component % grid_width
        row = published_component // grid_width
        for offset, genre_index in enumerate(selected):
            result.append(
                GenreCoordinate(
                    genre_id=genres[int(genre_index)],
                    x=round(
                        0.1 / grid_width + column / grid_width + float(x[offset]) * cell_scale,
                        12,
                    ),
                    y=round(
                        0.1 / grid_width + row / grid_width + float(y[offset]) * cell_scale,
                        12,
                    ),
                    component=published_component,
                )
            )
    return tuple(sorted(result, key=lambda item: item.genre_id))


def _profile_edges(neighbors: tuple[GenreNeighbor, ...], profile_kind: ProfileKind) -> EdgeWeights:
    weights: EdgeWeights = {}
    for item in neighbors:
        if item.profile_kind != profile_kind or item.metric != "weighted_jaccard":
            continue
        key = _edge_key(item.genre_id, item.neighbor_genre_id)
        weights[key] = max(weights.get(key, 0.0), float(item.score))
    return weights


def _hierarchy_edges(hierarchy: tuple[GenreHierarchyEdge, ...]) -> EdgeWeights:
    return {_edge_key(item.child_genre_id, item.parent_genre_id): 1.0 for item in hierarchy}


def _source_neighbors(
    genres: tuple[str, ...],
    weights: Mapping[tuple[str, str], float],
    count: int,
) -> dict[str, tuple[str, ...]]:
    grouped: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for (left, right), value in weights.items():
        grouped[left].append((right, value))
        grouped[right].append((left, value))
    return {
        genre: tuple(
            neighbor
            for neighbor, _value in sorted(
                grouped.get(genre, ()), key=lambda item: (-item[1], item[0])
            )[:count]
        )
        for genre in genres
    }


def _coordinate_neighbors(
    coordinates: tuple[GenreCoordinate, ...], count: int
) -> dict[str, tuple[str, ...]]:
    if len(coordinates) < _MINIMUM_NEIGHBOR_SET:
        return {item.genre_id: () for item in coordinates}
    ordered = tuple(sorted(coordinates, key=lambda item: item.genre_id))
    points = np.array([(float(item.x), float(item.y)) for item in ordered], dtype=np.float64)
    query_count = min(count + 1, len(ordered))
    distances, indexes = KDTree(points).query(points, k=query_count)
    if query_count == 1:
        distances = distances[:, np.newaxis]
        indexes = indexes[:, np.newaxis]
    result: dict[str, tuple[str, ...]] = {}
    for position, item in enumerate(ordered):
        candidates = sorted(
            (
                (float(distance), ordered[int(index)].genre_id)
                for distance, index in zip(distances[position], indexes[position], strict=True)
                if int(index) != position
            ),
            key=lambda candidate: (candidate[0], candidate[1]),
        )
        result[item.genre_id] = tuple(genre for _distance, genre in candidates[:count])
    return result


def _quality(
    coordinates: tuple[GenreCoordinate, ...],
    unplaced: tuple[UnplacedGenre, ...],
    context: _QualityContext,
) -> LayoutQuality:
    genres = tuple(item.genre_id for item in coordinates)
    embedded = _coordinate_neighbors(coordinates, context.neighbors_per_genre)

    def preservation(weights: Mapping[tuple[str, str], float]) -> float:
        source = _source_neighbors(genres, weights, context.neighbors_per_genre)
        values: list[float] = []
        for genre in genres:
            denominator = min(
                context.neighbors_per_genre,
                len(source[genre]),
                len(embedded[genre]),
            )
            if denominator:
                values.append(len(set(source[genre]) & set(embedded[genre])) / denominator)
        return round(sum(values) / len(values), 12) if values else 0.0

    source = _source_neighbors(genres, context.input_weights, context.neighbors_per_genre)
    directed = {(genre, neighbor) for genre, values in source.items() for neighbor in values}
    mutual = sum((right, left) in directed for left, right in directed)
    return LayoutQuality(
        neighbors_per_genre=context.neighbors_per_genre,
        layout_graph_edges=len(context.layout_weights),
        input_graph_edges=len(context.input_weights),
        placed_genres=len(coordinates),
        unplaced_genres=len(unplaced),
        mean_knn_preservation=preservation(context.input_weights),
        one_hop_reference_knn_preservation=preservation(context.one_hop_weights)
        if context.one_hop_weights is not None
        else None,
        mutual_neighbor_fraction=round(mutual / len(directed), 12) if directed else 0.0,
    )


def _tie_key(seed: int, label: str) -> tuple[str, str]:
    return hashlib.sha256(f"{seed}\0{label}".encode()).hexdigest(), label


def _community_assignments(
    genres: tuple[str, ...],
    weights: Mapping[tuple[str, str], float],
    *,
    seed: int,
    maximum_iterations: int,
) -> tuple[dict[str, str], int, bool]:
    graph: dict[str, dict[str, float]] = {genre: {} for genre in genres}
    for (left, right), weight in weights.items():
        graph[left][right] = weight
        graph[right][left] = weight
    labels = {genre: genre for genre in genres}
    order = sorted(genres, key=lambda genre: _tie_key(seed, genre))
    iterations = 0
    converged = False
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
    return {genre: canonical[label] for genre, label in labels.items()}, iterations, converged


def _modularity(weights: Mapping[tuple[str, str], float], labels: Mapping[str, str]) -> float:
    total_weight = sum(weights.values())
    if total_weight <= 0.0:
        return 0.0
    degrees: dict[str, float] = defaultdict(float)
    for (left, right), weight in weights.items():
        degrees[left] += weight
        degrees[right] += weight
    value = sum(
        weight - degrees[left] * degrees[right] / (2.0 * total_weight)
        for (left, right), weight in weights.items()
        if labels[left] == labels[right]
    )
    return value / total_weight


def _community_edges(
    weights: Mapping[tuple[str, str], float], labels: Mapping[str, str]
) -> EdgeWeights:
    return {pair: weight for pair, weight in weights.items() if labels[pair[0]] == labels[pair[1]]}


def _unplaced(
    all_genres: tuple[str, ...], placed: tuple[str, ...], reason: UnplacedReason
) -> tuple[UnplacedGenre, ...]:
    placed_set = set(placed)
    return tuple(
        UnplacedGenre(genre_id=genre, reason=reason)
        for genre in all_genres
        if genre not in placed_set
    )


def _lens(  # noqa: PLR0913
    *,
    layout_key: LayoutLensKey,
    method: LayoutMethod,
    input_kind: LayoutInputKind,
    metric: LayoutMetric,
    seed: int,
    all_genres: tuple[str, ...],
    placed_genres: tuple[str, ...],
    unplaced_reason: UnplacedReason,
    weights: EdgeWeights,
    neighbors_per_genre: int,
    quality_weights: EdgeWeights | None = None,
    one_hop_weights: EdgeWeights | None = None,
    community: CommunityLayoutResult | None = None,
) -> LayoutLens:
    started = time.monotonic()
    measured_weights = weights if quality_weights is None else quality_weights
    coordinates = _coordinates(placed_genres, weights)
    repeated = _coordinates(placed_genres, weights)
    unplaced = _unplaced(all_genres, placed_genres, unplaced_reason)
    input_payload = {
        "method": method,
        "method_version": "1",
        "input_kind": input_kind,
        "metric": metric,
        "seed": seed,
        "genres": placed_genres,
        "edges": [(left, right, weight) for (left, right), weight in sorted(weights.items())],
        "quality_edges": [
            (left, right, weight) for (left, right), weight in sorted(measured_weights.items())
        ],
    }
    quality = _quality(
        coordinates,
        unplaced,
        _QualityContext(
            layout_weights=weights,
            input_weights=measured_weights,
            neighbors_per_genre=neighbors_per_genre,
            one_hop_weights=one_hop_weights,
        ),
    )
    stability = LayoutStability(
        exact_rerun=coordinates == repeated,
        aligned_coordinate_rms=round(
            math.sqrt(
                sum(
                    (float(left.x) - float(right.x)) ** 2 + (float(left.y) - float(right.y)) ** 2
                    for left, right in zip(coordinates, repeated, strict=True)
                )
                / len(coordinates)
            ),
            12,
        )
        if coordinates
        else 0.0,
    )
    output_payload = {
        "coordinates": [item.model_dump(mode="json") for item in coordinates],
        "unplaced": [item.model_dump(mode="json") for item in unplaced],
        "quality": quality.model_dump(mode="json"),
        "stability": stability.model_dump(mode="json"),
        "community": community.model_dump(mode="json") if community is not None else None,
    }
    return LayoutLens(
        layout_key=layout_key,
        is_default=layout_key == "public",
        method=method,
        input_kind=input_kind,
        metric=metric,
        seed=seed,
        input_sha256=_canonical_sha256(input_payload),
        output_sha256=_canonical_sha256(output_payload),
        coordinates=coordinates,
        unplaced=unplaced,
        quality=quality,
        stability=stability,
        community=community,
        resources=ModelResources(
            elapsed_ms=round((time.monotonic() - started) * 1_000),
            peak_rss_bytes=_peak_rss_bytes(),
        ),
    )


def build_layout_lenses(
    all_genres: tuple[str, ...],
    direct_genres: tuple[str, ...],
    neighbors: tuple[GenreNeighbor, ...],
    hierarchy: tuple[GenreHierarchyEdge, ...],
    settings: PublicModelSettings,
) -> tuple[LayoutLens, ...]:
    """Build direct, learned, community, and taxonomy lenses without mixing facets."""
    direct_edges = _profile_edges(neighbors, "direct")
    learned_edges = _profile_edges(neighbors, "one_hop")
    labels, iterations, converged = _community_assignments(
        direct_genres,
        learned_edges,
        seed=settings.community_seed,
        maximum_iterations=settings.maximum_community_iterations,
    )
    community_edges = _community_edges(learned_edges, labels)
    community = CommunityLayoutResult(
        community_count=len(set(labels.values())),
        iterations=iterations,
        converged=converged,
        modularity=round(_modularity(learned_edges, labels), 12),
    )
    taxonomy_edges = _hierarchy_edges(hierarchy)
    taxonomy_genres = tuple(sorted({genre for pair in taxonomy_edges for genre in pair}))
    count = settings.layout_neighbors_per_genre
    return (
        _lens(
            layout_key="public",
            method="normalized_laplacian_spectral",
            input_kind="one_hop",
            metric="weighted_jaccard",
            seed=_SPECTRAL_SEED,
            all_genres=all_genres,
            placed_genres=direct_genres,
            unplaced_reason="no_direct_membership",
            weights=learned_edges,
            neighbors_per_genre=count,
            one_hop_weights=learned_edges,
        ),
        _lens(
            layout_key="public-direct",
            method="normalized_laplacian_spectral",
            input_kind="direct",
            metric="weighted_jaccard",
            seed=_SPECTRAL_SEED,
            all_genres=all_genres,
            placed_genres=direct_genres,
            unplaced_reason="no_direct_membership",
            weights=direct_edges,
            neighbors_per_genre=count,
            one_hop_weights=learned_edges,
        ),
        _lens(
            layout_key="public-community",
            method="community_packed_spectral",
            input_kind="one_hop",
            metric="weighted_jaccard",
            seed=settings.community_seed,
            all_genres=all_genres,
            placed_genres=direct_genres,
            unplaced_reason="no_direct_membership",
            weights=community_edges,
            neighbors_per_genre=count,
            quality_weights=learned_edges,
            one_hop_weights=learned_edges,
            community=community,
        ),
        _lens(
            layout_key="public-taxonomy",
            method="taxonomy_spectral",
            input_kind="genre_hierarchy",
            metric="hierarchy_adjacency",
            seed=_SPECTRAL_SEED,
            all_genres=all_genres,
            placed_genres=taxonomy_genres,
            unplaced_reason="no_hierarchy_relation",
            weights=taxonomy_edges,
            neighbors_per_genre=count,
        ),
    )
