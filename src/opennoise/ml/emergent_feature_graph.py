"""Source musical-feature graph initialization, an explicitly separate experiment."""

from __future__ import annotations

import heapq
from collections import Counter, defaultdict
from typing import cast

import numpy as np
from scipy import sparse
from scipy.sparse.csgraph import connected_components

from opennoise.ml.emergent_topics import (
    GENERIC,
    MIN_MUSIC_FEATURES,
    FeatureMatrix,
    TopicSettings,
    _centroid,
    _descriptors,
    _Node,
    _node_id,
    _split_node,
)

REVISION = "emergent-source-feature-graph-v1"
NEIGHBORS = 20
MINIMUM_SHARED_ARTISTS = 2
MODULARITY_PASSES = 30
AGGREGATION_ROUNDS = 10


def musical_feature_graph(data: FeatureMatrix) -> tuple[tuple[str, ...], sparse.csr_matrix]:
    """Collapse facets, downweight high-degree artists, and retain mutual cosine neighbors."""
    values = tuple(sorted({value for profile in data.group_keys for value in profile}))
    lookup = {value: column for column, value in enumerate(values)}
    rows, columns = [], []
    for group, profile in enumerate(data.group_keys):
        for value in profile:
            rows.append(group)
            columns.append(lookup[value])
    binary = sparse.csr_matrix(
        (np.ones(len(rows)), (rows, columns)), shape=(len(data.group_keys), len(values))
    )
    degree = np.maximum(1, np.diff(binary.indptr) - 1)
    counts = data.group_counts.astype(float)
    raw = (binary.T @ sparse.diags(counts) @ binary).tocsr()
    corrected = (binary.T @ sparse.diags(counts / degree) @ binary).tocsr()
    scale = 1 / np.sqrt(np.maximum(1e-12, corrected.diagonal()))
    affinity = (sparse.diags(scale) @ corrected @ sparse.diags(scale)).tocsr()
    affinity = affinity.multiply(raw >= MINIMUM_SHARED_ARTISTS).tocsr()
    affinity.setdiag(0)
    affinity.eliminate_zeros()
    selected_rows, selected_columns, selected_weights = [], [], []
    for row in range(len(values)):
        start, end = affinity.indptr[row : row + 2]
        candidates, weights = affinity.indices[start:end], affinity.data[start:end]
        keep = np.lexsort((candidates, -weights))[:NEIGHBORS]
        selected_rows.extend([row] * len(keep))
        selected_columns.extend(candidates[keep])
        selected_weights.extend(weights[keep])
    directed = sparse.csr_matrix(
        (selected_weights, (selected_rows, selected_columns)), shape=affinity.shape
    )
    graph = directed.minimum(directed.T).tocsr()
    graph.eliminate_zeros()
    return values, cast("sparse.csr_matrix", graph)


def _local_partition(graph: sparse.csr_matrix) -> np.ndarray:
    """Optimize weighted modularity at fixed resolution one using deterministic sweeps."""
    labels = np.arange(graph.shape[0])
    strength = np.asarray(graph.sum(axis=1)).ravel()
    totals = strength.copy()
    mass = float(strength.sum())
    if mass == 0:
        return labels
    for _ in range(MODULARITY_PASSES):
        moved = False
        for node in range(graph.shape[0]):
            old = int(labels[node])
            totals[old] -= strength[node]
            support: dict[int, float] = defaultdict(float)
            start, end = graph.indptr[node : node + 2]
            for neighbor, weight in zip(
                graph.indices[start:end], graph.data[start:end], strict=True
            ):
                if neighbor != node:
                    support[int(labels[neighbor])] += float(weight)
            support.setdefault(old, 0.0)
            scores = {
                community: weight - strength[node] * totals[community] / mass
                for community, weight in support.items()
            }
            best = min(scores, key=lambda community: (-scores[community], community))
            # Equal objective leaves the current label, preventing zero-gain churn.
            if scores[best] <= scores[old] + 1e-12:
                best = old
            labels[node] = best
            totals[best] += strength[node]
            moved |= best != old
        if not moved:
            break
    remap = {old: new for new, old in enumerate(sorted(set(labels)))}
    return np.array([remap[int(label)] for label in labels], dtype=np.int32)


def graph_partition(graph: sparse.csr_matrix) -> np.ndarray:
    """Aggregate locally optimized feature communities without crossing graph components."""
    labels = np.arange(graph.shape[0], dtype=np.int32)
    current = graph
    for _ in range(AGGREGATION_ROUNDS):
        local = _local_partition(current)
        labels = local[labels]
        size = int(local.max()) + 1 if len(local) else 0
        if size == current.shape[0]:
            break
        projector = sparse.csr_matrix(
            (np.ones(len(local)), (np.arange(len(local)), local)), shape=(len(local), size)
        )
        current = (projector.T @ current @ projector).tocsr()
    return labels


def _frontiers(  # noqa: C901 - graph construction and bounded refinement share source groups.
    data: FeatureMatrix, settings: TopicSettings
) -> tuple[list[list[_Node]], dict[str, object]]:
    values, graph = musical_feature_graph(data)
    labels = graph_partition(graph)
    lookup = {value: column for column, value in enumerate(values)}
    support: Counter[str] = Counter()
    # Count canonical values once per artist, irrespective of duplicated source facets.
    for group, profile in enumerate(data.group_keys):
        support.update({value: int(data.group_counts[group]) for value in profile})
    idf = {
        value: 1 + np.log((len(data.artists) + 1) / (count + 1)) for value, count in support.items()
    }
    groups_by_basin: dict[int, list[int]] = defaultdict(list)
    for group, profile in enumerate(data.group_keys):
        scores: dict[int, float] = defaultdict(float)
        for value in profile:
            scores[int(labels[lookup[value]])] += idf[value] * (0.35 if value in GENERIC else 1)
        if scores:
            basin = min(scores, key=lambda label: (-scores[label], label))
            groups_by_basin[basin].append(group)
    roots = []
    for groups in groups_by_basin.values():
        selected = np.array(groups, dtype=np.int32)
        if data.group_counts[selected].sum() >= settings.minimum_artists:
            roots.append(
                _Node(
                    selected,
                    _centroid(data.group_matrix[selected], data.group_counts[selected]),
                    0,
                    None,
                )
            )
    roots.sort(key=lambda node: int(node.groups.min()))
    frontier = {id(node): node for node in roots}
    queue: list[tuple[float, int, _Node]] = []

    def enqueue(node: _Node) -> None:
        affinity = np.asarray(data.group_matrix[node.groups] @ node.centroid).ravel()
        dispersion = float(np.sum(data.group_counts[node.groups] * np.maximum(0, 1 - affinity)))
        heapq.heappush(queue, (-dispersion, int(node.groups.min()), node))

    for root in roots:
        enqueue(root)
    cuts = [roots]
    for power in settings.depths[1:]:
        while queue and len(frontier) < 2**power:
            _priority, _tie, node = heapq.heappop(queue)
            _split_node(node, data, settings)
            if node.children:
                del frontier[id(node)]
                for child in node.children:
                    frontier[id(child)] = child
                    enqueue(child)
        cuts.append(sorted(frontier.values(), key=lambda node: int(node.groups.min())))
    return cuts, {
        "canonical_musical_feature_count": len(values),
        "undirected_edge_count": graph.nnz // 2,
        "connected_component_count": int(connected_components(graph, directed=False)[0]),
        "feature_basin_count": len(set(labels)),
        "supported_artist_basin_count": len(roots),
        "mutual_neighbors": NEIGHBORS,
        "minimum_shared_artists": MINIMUM_SHARED_ARTISTS,
        "degree_correction": "one_over_max_one_artist_canonical_degree_minus_one",
        "modularity_resolution": 1,
        "broad_count_is_graph_derived_not_fixed_budget": True,
    }


def fit_graph_topics(  # noqa: C901, PLR0912 - one partition accounting boundary.
    data: FeatureMatrix, settings: TopicSettings | None = None, *, include_centroids: bool = False
) -> tuple[dict[str, object], dict[str, list[dict[str, object]]]]:
    """Fit graph-initialized hard partitions; overlapping proposals are deliberately absent."""
    resolved = settings or TopicSettings()
    frontiers, diagnostics = _frontiers(data, resolved)
    nodes: dict[str, _Node] = {}
    levels = {}
    for level, frontier in zip(("broad", "sub", "micro"), frontiers, strict=True):
        for node in frontier:
            key = _node_id(node, data)
            if key not in nodes and (
                level == "broad" or len(_descriptors(node, data)) >= MIN_MUSIC_FEATURES
            ):
                nodes[key], levels[key] = node, level
    node_ids = {id(node): key for key, node in nodes.items()}
    communities = []
    group_assignments: dict[int, list[dict[str, object]]] = defaultdict(list)
    primary: dict[str, dict[str, str | None]] = {level: {} for level in ("broad", "sub", "micro")}
    examples: dict[str, list[tuple[float, str]]] = defaultdict(list)
    for key, node in nodes.items():
        parent = node.parent
        while parent is not None and id(parent) not in node_ids:
            parent = parent.parent
        descriptors = _descriptors(node, data)
        affinities = np.asarray(data.group_matrix[node.groups] @ node.centroid).ravel()
        communities.append(
            {
                "id": key,
                "level": levels[key],
                "parent_id": node_ids.get(id(parent)),
                "label": " / ".join(str(item["value"]) for item in descriptors[:3]),
                "label_origin": "derived_feature_descriptors",
                "descriptors": descriptors,
                "core_artist_count": int(data.group_counts[node.groups].sum()),
                "core_mean_cosine": float(
                    np.average(affinities, weights=data.group_counts[node.groups])
                ),
                "distinct_profile_count": len(node.groups),
                "role": "inferred_music_community",
                "quality_evaluated": False,
                "child_ids": [],
                "artist_ids": [],
                "artist_count": 0,
            }
        )
        for local, group in enumerate(node.groups):
            if levels[key] != "broad" and len(data.group_keys[int(group)]) < MIN_MUSIC_FEATURES:
                continue
            group_assignments[int(group)].append(
                {
                    "community_id": key,
                    "level": levels[key],
                    "score": float(affinities[local]),
                    "role": "inferred_community_membership",
                    "assignment_reason": "graph_initialized_core_partition",
                }
            )
    assignments = {
        artist: group_assignments.get(int(data.artist_groups[row]), [])
        for row, artist in enumerate(data.artists)
    }
    for artist, memberships in assignments.items():
        for level, mapping in primary.items():
            mapping[artist] = next(
                (str(item["community_id"]) for item in memberships if item["level"] == level), None
            )
        for item in memberships:
            examples[str(item["community_id"])].append(
                (float(cast("float", item["score"])), artist)
            )
    indexed = {str(item["id"]): item for item in communities}
    for item in communities:
        key = str(item["id"])
        values = sorted(examples[key], key=lambda pair: (-pair[0], pair[1]))
        item["artist_count"] = len(values)
        item["artist_ids"] = [artist for _score, artist in values[: resolved.example_limit]]
        parent_id = item["parent_id"]
        if isinstance(parent_id, str):
            cast("list[str]", indexed[parent_id]["child_ids"]).append(key)
    model: dict[str, object] = {
        "revision": REVISION,
        "communities": communities,
        "primary_assignments": primary,
        "graph_diagnostics": diagnostics,
        "quality_evaluated": False,
        "scope": "local_research_only",
        "public_export_authorized": False,
        "assignment_rule": "hard_source_feature_graph_basin_then_spherical_refinement",
        "coverage": {
            "artist_count": len(data.artists),
            "assigned_artist_count": sum(bool(items) for items in assignments.values()),
            "assigned_by_level": {
                level: sum(value is not None for value in mapping.values())
                for level, mapping in primary.items()
            },
            "community_count_by_level": dict(Counter(levels.values())),
        },
    }
    if include_centroids:
        model["centroids"] = {key: node.centroid.tolist() for key, node in nodes.items()}
        model["core_group_ids"] = {key: node.groups.tolist() for key, node in nodes.items()}
    return model, assignments
