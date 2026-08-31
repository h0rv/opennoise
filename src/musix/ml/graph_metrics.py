"""Small deterministic metrics for bounded undirected graphs."""

import math
from collections import defaultdict
from collections.abc import Mapping


def weighted_undirected_modularity(
    weights: Mapping[tuple[str, str], float],
    labels: Mapping[str, str],
) -> float:
    """Return standard weighted modularity for a simple undirected graph."""
    total_weight = 0.0
    internal_weights: dict[str, float] = defaultdict(float)
    community_degrees: dict[str, float] = defaultdict(float)
    for (left, right), weight in weights.items():
        if left == right:
            raise ValueError("modularity graph must not contain self edges")
        if left > right:
            raise ValueError("modularity edges must use canonical endpoint order")
        if not math.isfinite(weight) or weight <= 0.0:
            raise ValueError("modularity edge weights must be finite and positive")
        left_label = labels[left]
        right_label = labels[right]
        total_weight += weight
        community_degrees[left_label] += weight
        community_degrees[right_label] += weight
        if left_label == right_label:
            internal_weights[left_label] += weight
    if total_weight == 0.0:
        return 0.0
    communities = set(community_degrees) | set(labels.values())
    return sum(
        internal_weights[community] / total_weight
        - (community_degrees[community] / (2.0 * total_weight)) ** 2
        for community in sorted(communities)
    )
