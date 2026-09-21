"""Read-only holdout evaluation for conservative direct-artist peer edges.

This is a geometry diagnostic for a fixed, local-only edge candidate.  It does
not assert musical similarity, alter an atlas, or use a held target's own
coordinate while predicting that target.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable


@dataclass(frozen=True, slots=True)
class Point:
    """One immutable two-dimensional atlas anchor."""

    x: float
    y: float


@dataclass(frozen=True, slots=True)
class HoldoutSummary:
    """Aggregate geometry results for targets with at least one peer anchor."""

    evaluable_target_count: int
    mean_peer_error: float
    mean_global_baseline_error: float
    median_peer_error: float
    median_global_baseline_error: float
    peer_beats_baseline_count: int

    @property
    def mean_error_improvement(self) -> float:
        """Positive only when the direct-peer projection beats the baseline."""
        return self.mean_global_baseline_error - self.mean_peer_error


@dataclass(frozen=True, slots=True)
class ProjectionResult:
    """A coordinate proposal derived only from supplied placed peer anchors."""

    seed_id: str
    point: Point
    placed_peer_count: int


def _centroid(points: Iterable[Point]) -> Point:
    values = tuple(points)
    if not values:
        raise ValueError("a centroid requires at least one point")
    return Point(
        x=sum(point.x for point in values) / len(values),
        y=sum(point.y for point in values) / len(values),
    )


def _distance(left: Point, right: Point) -> float:
    return math.hypot(left.x - right.x, left.y - right.y)


def adjacency(edges: Iterable[tuple[str, str]]) -> dict[str, frozenset[str]]:
    """Canonicalize a candidate edge list into an undirected adjacency map."""
    result: dict[str, set[str]] = defaultdict(set)
    for left, right in edges:
        if left == right:
            raise ValueError("self edges cannot support a holdout prediction")
        result[left].add(right)
        result[right].add(left)
    return {seed_id: frozenset(neighbors) for seed_id, neighbors in result.items()}


def evaluate_holdout(
    *, anchors: dict[str, Point], peer_adjacency: dict[str, frozenset[str]]
) -> HoldoutSummary:
    """Predict each placed target only from other placed direct-peer anchors.

    The global centroid baseline is recomputed without the held target too, so
    neither method reads the evaluated coordinate as a prediction input.
    """
    peer_errors: list[float] = []
    baseline_errors: list[float] = []
    for seed_id, actual in anchors.items():
        neighbor_points = tuple(
            anchors[neighbor]
            for neighbor in peer_adjacency.get(seed_id, frozenset())
            if neighbor != seed_id and neighbor in anchors
        )
        if not neighbor_points:
            continue
        remaining_points = tuple(
            point for other_id, point in anchors.items() if other_id != seed_id
        )
        peer_errors.append(_distance(_centroid(neighbor_points), actual))
        baseline_errors.append(_distance(_centroid(remaining_points), actual))
    if not peer_errors:
        raise ValueError("no placed target has a placed conservative peer")
    ordered_peer = sorted(peer_errors)
    ordered_baseline = sorted(baseline_errors)
    middle = len(ordered_peer) // 2
    if len(ordered_peer) % 2:
        median_peer = ordered_peer[middle]
        median_baseline = ordered_baseline[middle]
    else:
        median_peer = (ordered_peer[middle - 1] + ordered_peer[middle]) / 2
        median_baseline = (ordered_baseline[middle - 1] + ordered_baseline[middle]) / 2
    return HoldoutSummary(
        evaluable_target_count=len(peer_errors),
        mean_peer_error=sum(peer_errors) / len(peer_errors),
        mean_global_baseline_error=sum(baseline_errors) / len(baseline_errors),
        median_peer_error=median_peer,
        median_global_baseline_error=median_baseline,
        peer_beats_baseline_count=sum(
            peer < baseline for peer, baseline in zip(peer_errors, baseline_errors, strict=True)
        ),
    )


def project_unplaced(
    *,
    unplaced_ids: Iterable[str],
    anchors: dict[str, Point],
    peer_adjacency: dict[str, frozenset[str]],
) -> tuple[ProjectionResult, ...]:
    """Return only direct-anchor projections, leaving unreachable IDs absent."""
    projections: list[ProjectionResult] = []
    for seed_id in sorted(set(unplaced_ids)):
        peer_points = tuple(
            anchors[neighbor]
            for neighbor in peer_adjacency.get(seed_id, frozenset())
            if neighbor in anchors
        )
        if peer_points:
            projections.append(
                ProjectionResult(
                    seed_id=seed_id,
                    point=_centroid(peer_points),
                    placed_peer_count=len(peer_points),
                )
            )
    return tuple(projections)
