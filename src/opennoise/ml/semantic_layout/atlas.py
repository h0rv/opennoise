"""Deterministic rectangular atlas geometry for the structural map.

This module owns only geometry.  It does not infer taxonomy, read historical
coordinates, or run a browser-time force simulation.  Group boundaries are
layout regions, not claims that groups are genres or parents.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from hashlib import sha256
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

_MIN_POINTS = 2
_MAX_MARGIN = 0.25


@dataclass(frozen=True, slots=True)
class AtlasSettings:
    """Small, explicit policy for a broad landscape atlas."""

    world_width: float = 16.0 / 9.0
    world_height: float = 1.0
    margin: float = 0.055
    clip_low: float = 0.01
    clip_high: float = 0.99
    group_gap: float = 0.012

    def __post_init__(self) -> None:
        """Reject dimensions and clipping policies that cannot make an atlas."""
        if not self.world_width > self.world_height > 0.0:
            raise ValueError("atlas dimensions must form a positive landscape")
        if not 0.0 < self.margin < _MAX_MARGIN:
            raise ValueError("atlas margin must be bounded")
        if not 0.0 <= self.clip_low < self.clip_high <= 1.0:
            raise ValueError("atlas clipping quantiles must be ordered")


@dataclass(frozen=True, slots=True)
class AtlasPoint:
    """A source coordinate and its deterministic layout neighborhood."""

    node_id: str
    x: float
    y: float
    group_id: str


@dataclass(frozen=True, slots=True)
class AtlasRegion:
    """A rectangular visual region occupied by one layout neighborhood."""

    group_id: str
    anchor_id: str
    x0: float
    y0: float
    x1: float
    y1: float


@dataclass(frozen=True, slots=True)
class AtlasResult:
    """Normalized positions and regions ready for a renderer-neutral artifact."""

    positions: Mapping[str, tuple[float, float]]
    regions: tuple[AtlasRegion, ...]
    local_neighbor_preservation: float | None


def build_rectangular_atlas(
    points: tuple[AtlasPoint, ...], *, settings: AtlasSettings | None = None
) -> AtlasResult:
    """Fit points into a centered 16:9 atlas with deterministic local packing.

    Robust quantile clipping prevents one outlier from consuming the viewport.
    Group regions are derived after placement, so they never erase global
    neighborhood relationships.  A stable hash resolves exact point collisions
    without random state or a runtime simulation.
    """
    resolved = settings or AtlasSettings()
    if not points:
        return AtlasResult(positions={}, regions=(), local_neighbor_preservation=None)
    if len({point.node_id for point in points}) != len(points):
        raise ValueError("atlas point IDs must be unique")
    if any(
        not point.node_id
        or not point.group_id
        or not math.isfinite(point.x)
        or not math.isfinite(point.y)
        for point in points
    ):
        raise ValueError("atlas points must have finite identities and coordinates")
    x_values = tuple(point.x for point in points)
    y_values = tuple(point.y for point in points)
    x_low, x_high = _quantile(x_values, resolved.clip_low), _quantile(x_values, resolved.clip_high)
    y_low, y_high = _quantile(y_values, resolved.clip_low), _quantile(y_values, resolved.clip_high)
    x0, x1 = resolved.margin, resolved.world_width - resolved.margin
    y0, y1 = resolved.margin, resolved.world_height - resolved.margin
    positions = {
        point.node_id: (
            _scale(_clip(point.x, x_low, x_high), x_low, x_high, x0, x1),
            _scale(_clip(point.y, y_low, y_high), y_low, y_high, y0, y1),
        )
        for point in points
    }
    positions = _separate_collisions(positions)
    regions = _derive_regions(points, positions, resolved)
    preservation = _local_neighbor_preservation(points, positions, resolved.world_width)
    return AtlasResult(
        positions=positions,
        regions=regions,
        local_neighbor_preservation=preservation,
    )


def _derive_regions(
    points: tuple[AtlasPoint, ...],
    positions: Mapping[str, tuple[float, float]],
    settings: AtlasSettings,
) -> tuple[AtlasRegion, ...]:
    """Describe neighborhoods after placement; regions never dictate placement."""
    grouped: dict[str, list[AtlasPoint]] = {}
    for point in points:
        grouped.setdefault(point.group_id, []).append(point)
    regions: list[AtlasRegion] = []
    for group_id, members in sorted(grouped.items()):
        member_positions = tuple(positions[item.node_id] for item in members)
        minimum_x = min(point[0] for point in member_positions)
        maximum_x = max(point[0] for point in member_positions)
        minimum_y = min(point[1] for point in member_positions)
        maximum_y = max(point[1] for point in member_positions)
        padding_x = max(settings.group_gap, (maximum_x - minimum_x) * 0.04)
        padding_y = max(settings.group_gap, (maximum_y - minimum_y) * 0.04)
        center_x = sum(point[0] for point in member_positions) / len(member_positions)
        center_y = sum(point[1] for point in member_positions) / len(member_positions)
        anchor = min(
            members,
            key=lambda item: (
                math.dist(positions[item.node_id], (center_x, center_y)),
                item.node_id,
            ),
        )
        regions.append(
            AtlasRegion(
                group_id=group_id,
                anchor_id=anchor.node_id,
                x0=max(0.0, minimum_x - padding_x),
                y0=max(0.0, minimum_y - padding_y),
                x1=min(settings.world_width, maximum_x + padding_x),
                y1=min(settings.world_height, maximum_y + padding_y),
            )
        )
    return tuple(regions)


def _quantile(values: tuple[float, ...], fraction: float) -> float:
    ordered = tuple(sorted(values))
    if len(ordered) == 1:
        return ordered[0]
    position = fraction * (len(ordered) - 1)
    lower = math.floor(position)
    upper = math.ceil(position)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _clip(value: float, minimum: float, maximum: float) -> float:
    return min(max(value, minimum), maximum)


def _scale(
    value: float,
    source_min: float,
    source_max: float,
    target_min: float,
    target_max: float,
) -> float:
    if math.isclose(source_min, source_max):
        return (target_min + target_max) / 2.0
    return target_min + (value - source_min) / (source_max - source_min) * (target_max - target_min)


def _local_neighbor_preservation(
    points: tuple[AtlasPoint, ...],
    positions: Mapping[str, tuple[float, float]],
    world_width: float,
    neighbors: int = 10,
) -> float | None:
    """Measure nearest-neighbor preservation after robust affine normalization."""
    if len(points) < _MIN_POINTS:
        return None
    limit = min(neighbors, len(points) - 1)
    raw = {point.node_id: (point.x, point.y) for point in points}

    def nearest(source: Mapping[str, tuple[float, float]], node_id: str) -> set[str]:
        x, y = source[node_id]
        ranked = sorted(
            (
                math.dist((x / world_width, y), (other_x / world_width, other_y)),
                other_id,
            )
            for other_id, (other_x, other_y) in source.items()
            if other_id != node_id
        )
        return {other_id for _distance, other_id in ranked[:limit]}

    values = [
        len(nearest(raw, point.node_id) & nearest(positions, point.node_id)) / limit
        for point in points
    ]
    return sum(values) / len(values)


def _separate_collisions(
    positions: Mapping[str, tuple[float, float]],
) -> dict[str, tuple[float, float]]:
    """Apply stable tiny rings only to exact collisions."""
    groups: dict[tuple[float, float], list[str]] = {}
    for node_id, point in positions.items():
        groups.setdefault((round(point[0], 12), round(point[1], 12)), []).append(node_id)
    output = dict(positions)
    for (x, y), node_ids in groups.items():
        if len(node_ids) < _MIN_POINTS:
            continue
        radius = min(0.012, 0.002 + 0.0005 * math.sqrt(len(node_ids)))
        for index, node_id in enumerate(sorted(node_ids)):
            digest = sha256(node_id.encode()).digest()
            offset = int.from_bytes(digest[:4], "big") / 2**32
            angle = 2.0 * math.pi * (index + offset) / len(node_ids)
            output[node_id] = (x + radius * math.cos(angle), y + radius * math.sin(angle))
    return output
