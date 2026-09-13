"""Bounded, model-neutral measurements for published point layouts."""

from __future__ import annotations

import hashlib
import heapq
import math
import struct
from collections import defaultdict
from typing import TYPE_CHECKING

from pydantic import Field, FiniteFloat, model_validator

from opennoise.models import FrozenModel

if TYPE_CHECKING:
    from collections.abc import Iterable

MAX_ENTITY_ID = 9_223_372_036_854_775_807


class LayoutMetricPoint(FrozenModel):
    """One stable entity coordinate in a versioned layout."""

    entity_id: int = Field(ge=1, le=MAX_ENTITY_ID)
    x: FiniteFloat
    y: FiniteFloat


class VersionedPointLayout(FrozenModel):
    """Typed coordinates and provenance for one immutable layout revision."""

    layout_key: str = Field(min_length=1, max_length=100)
    revision: int = Field(ge=1)
    input_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    points: tuple[LayoutMetricPoint, ...] = Field(min_length=1, max_length=100_000)

    @model_validator(mode="after")
    def _require_unique_entity_ids(self) -> VersionedPointLayout:
        entity_ids = {point.entity_id for point in self.points}
        if len(entity_ids) != len(self.points):
            raise ValueError("layout points must have unique entity IDs")
        return self


class ReferenceNeighborList(FrozenModel):
    """A source-space neighbor ranking for one mapped entity."""

    entity_id: int = Field(ge=1, le=MAX_ENTITY_ID)
    neighbor_ids: tuple[int, ...] = Field(min_length=1, max_length=100_000)

    @model_validator(mode="after")
    def _require_unique_neighbors(self) -> ReferenceNeighborList:
        if self.entity_id in self.neighbor_ids:
            raise ValueError("a reference neighbor list cannot contain its entity ID")
        if len(set(self.neighbor_ids)) != len(self.neighbor_ids):
            raise ValueError("reference neighbor IDs must be unique")
        return self


class LabelBox(FrozenModel):
    """A screen-space label rectangle used only for collision measurement."""

    entity_id: int = Field(ge=1, le=MAX_ENTITY_ID)
    min_x: FiniteFloat
    min_y: FiniteFloat
    max_x: FiniteFloat
    max_y: FiniteFloat

    @model_validator(mode="after")
    def _require_nonempty_box(self) -> LabelBox:
        if self.min_x >= self.max_x or self.min_y >= self.max_y:
            raise ValueError("label boxes must have positive width and height")
        return self


class MetricViewport(FrozenModel):
    """A coordinate-space viewport for density measurement."""

    min_x: FiniteFloat
    min_y: FiniteFloat
    max_x: FiniteFloat
    max_y: FiniteFloat

    @model_validator(mode="after")
    def _require_nonempty_viewport(self) -> MetricViewport:
        if self.min_x >= self.max_x or self.min_y >= self.max_y:
            raise ValueError("viewports must have positive width and height")
        return self


class DensityGrid(FrozenModel):
    """Bounded grid settings for a viewport density summary."""

    columns: int = Field(default=16, ge=1, le=128)
    rows: int = Field(default=16, ge=1, le=128)
    viewport: MetricViewport | None = None


class CommunityMembership(FrozenModel):
    """One entity's membership in a supplied graph community."""

    entity_id: int = Field(ge=1, le=MAX_ENTITY_ID)
    community_id: str = Field(min_length=1, max_length=200)


class CommunityEdge(FrozenModel):
    """An undirected graph edge used for within-community connectivity."""

    source_entity_id: int = Field(ge=1, le=MAX_ENTITY_ID)
    target_entity_id: int = Field(ge=1, le=MAX_ENTITY_ID)

    @model_validator(mode="after")
    def _require_distinct_endpoints(self) -> CommunityEdge:
        if self.source_entity_id == self.target_entity_id:
            raise ValueError("community edges must connect distinct entity IDs")
        return self


class RenderBudgetInput(FrozenModel):
    """Renderer choices needed to estimate simple DOM and draw budgets."""

    label_count: int = Field(default=0, ge=0, le=100_000)
    label_character_count: int = Field(default=0, ge=0, le=10_000_000)
    edge_count: int = Field(default=0, ge=0, le=1_000_000)
    interactive_point_count: int | None = Field(default=None, ge=0, le=100_000)


class LayoutMetricRequest(FrozenModel):
    """Optional evidence supplied to evaluate one published layout revision."""

    layout: VersionedPointLayout
    reference_neighbors: tuple[ReferenceNeighborList, ...] = Field(default=(), max_length=100_000)
    neighbor_count: int = Field(default=10, ge=1, le=128)
    neighbor_sample_limit: int = Field(default=256, ge=1, le=1_024)
    label_boxes: tuple[LabelBox, ...] | None = Field(default=None, max_length=4_096)
    label_comparison_limit: int = Field(default=500_000, ge=1, le=5_000_000)
    density_grid: DensityGrid = Field(default_factory=DensityGrid)
    community_memberships: tuple[CommunityMembership, ...] | None = Field(
        default=None, max_length=100_000
    )
    community_edges: tuple[CommunityEdge, ...] | None = Field(default=None, max_length=1_000_000)
    previous_layout: VersionedPointLayout | None = None
    repeat_layout: VersionedPointLayout | None = None
    render_budget: RenderBudgetInput = Field(default_factory=RenderBudgetInput)

    @model_validator(mode="after")
    def _require_consistent_references(self) -> LayoutMetricRequest:
        point_ids = {point.entity_id for point in self.layout.points}
        if self.reference_neighbors and self.neighbor_count >= len(point_ids):
            raise ValueError("neighbor_count must be smaller than the layout point count")
        _validate_reference_neighbors(point_ids, self.reference_neighbors)
        _validate_label_boxes(self.label_boxes)
        _validate_community_inputs(point_ids, self.community_memberships, self.community_edges)
        return self


class NeighborPreservationMetrics(FrozenModel):
    """Local-neighbor agreement with an optional source-space ranking."""

    sampled_entity_count: int = Field(ge=0)
    neighbor_count: int = Field(ge=0)
    reference_neighbor_recall: float = Field(ge=0.0, le=1.0)
    trustworthiness: float = Field(ge=0.0, le=1.0)
    trustworthiness_is_exact: bool
    reference_depth_min: int = Field(ge=0)
    reference_depth_max: int = Field(ge=0)


class LabelOverlapMetrics(FrozenModel):
    """A bounded lower-bound summary of supplied label collisions."""

    label_count: int = Field(ge=0)
    compared_pair_count: int = Field(ge=0)
    comparison_complete: bool
    overlapping_pair_count_lower_bound: int = Field(ge=0)
    overlapping_label_count_lower_bound: int = Field(ge=0)
    overlap_area_lower_bound: float = Field(ge=0.0)


class ViewportDensityMetrics(FrozenModel):
    """A spatial density summary for one bounded viewport."""

    viewport: MetricViewport
    columns: int = Field(ge=1)
    rows: int = Field(ge=1)
    visible_point_count: int = Field(ge=0)
    outside_viewport_point_count: int = Field(ge=0)
    occupied_cell_count: int = Field(ge=0)
    max_cell_point_count: int = Field(ge=0)
    normalized_entropy: float = Field(ge=0.0, le=1.0)


class CommunityFragmentationMetrics(FrozenModel):
    """Connected-component fragmentation within supplied communities."""

    community_count: int = Field(ge=0)
    fragmented_community_count: int = Field(ge=0)
    component_count: int = Field(ge=0)
    largest_component_fraction: float = Field(ge=0.0, le=1.0)


class TemporalDisplacementMetrics(FrozenModel):
    """Direct coordinate movement between two published revisions."""

    common_entity_count: int = Field(ge=0)
    added_entity_count: int = Field(ge=0)
    removed_entity_count: int = Field(ge=0)
    mean_displacement: float = Field(ge=0.0)
    median_displacement: float = Field(ge=0.0)
    percentile_95_displacement: float = Field(ge=0.0)


class DeterminismMetrics(FrozenModel):
    """Canonical coordinate hashes and an optional repeat comparison."""

    coordinate_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    repeat_coordinate_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    exact_repeat_match: bool | None = None
    changed_or_missing_entity_count: int | None = Field(default=None, ge=0)


class DomRenderBudgetMetrics(FrozenModel):
    """Simple renderer-neutral estimates for a point and label view."""

    interactive_point_count: int = Field(ge=0)
    label_count: int = Field(ge=0)
    edge_count: int = Field(ge=0)
    estimated_svg_element_count: int = Field(ge=0)
    estimated_svg_keyboard_stop_count: int = Field(ge=0)
    estimated_canvas_draw_operations: int = Field(ge=0)
    label_character_count: int = Field(ge=0)


class LayoutMetricResult(FrozenModel):
    """Complete evaluation output for one immutable layout revision."""

    layout_key: str
    revision: int = Field(ge=1)
    point_count: int = Field(ge=1)
    neighbor_preservation: NeighborPreservationMetrics | None = None
    label_overlap: LabelOverlapMetrics | None = None
    viewport_density: ViewportDensityMetrics
    community_fragmentation: CommunityFragmentationMetrics | None = None
    temporal_displacement: TemporalDisplacementMetrics | None = None
    determinism: DeterminismMetrics
    render_budget: DomRenderBudgetMetrics


def _validate_reference_neighbors(
    point_ids: set[int], reference_neighbors: tuple[ReferenceNeighborList, ...]
) -> None:
    reference_ids = [item.entity_id for item in reference_neighbors]
    if len(set(reference_ids)) != len(reference_ids):
        raise ValueError("reference neighbor lists must have unique entity IDs")
    for item in reference_neighbors:
        if item.entity_id not in point_ids or not set(item.neighbor_ids).issubset(point_ids):
            raise ValueError("reference neighbors must refer to mapped layout entities")


def _validate_label_boxes(label_boxes: tuple[LabelBox, ...] | None) -> None:
    if label_boxes is None:
        return
    label_ids = [box.entity_id for box in label_boxes]
    if len(set(label_ids)) != len(label_ids):
        raise ValueError("label boxes must have unique entity IDs")


def _validate_community_inputs(
    point_ids: set[int],
    memberships: tuple[CommunityMembership, ...] | None,
    edges: tuple[CommunityEdge, ...] | None,
) -> None:
    if (memberships is None) != (edges is None):
        raise ValueError("community memberships and edges must be supplied together")
    if memberships is None:
        return
    membership_ids = [item.entity_id for item in memberships]
    if len(set(membership_ids)) != len(membership_ids):
        raise ValueError("community memberships must have unique entity IDs")
    if not set(membership_ids).issubset(point_ids):
        raise ValueError("community memberships must refer to mapped layout entities")


def evaluate_layout(request: LayoutMetricRequest) -> LayoutMetricResult:
    """Calculate bounded metrics without selecting or training a layout method."""
    points_by_id = {point.entity_id: point for point in request.layout.points}
    return LayoutMetricResult(
        layout_key=request.layout.layout_key,
        revision=request.layout.revision,
        point_count=len(points_by_id),
        neighbor_preservation=_neighbor_preservation(
            points_by_id,
            request.reference_neighbors,
            neighbor_count=request.neighbor_count,
            sample_limit=request.neighbor_sample_limit,
        ),
        label_overlap=_label_overlap(
            request.label_boxes,
            comparison_limit=request.label_comparison_limit,
        ),
        viewport_density=_viewport_density(points_by_id.values(), request.density_grid),
        community_fragmentation=_community_fragmentation(
            request.community_memberships,
            request.community_edges,
        ),
        temporal_displacement=_temporal_displacement(points_by_id, request.previous_layout),
        determinism=_determinism(request.layout, request.repeat_layout),
        render_budget=_render_budget(len(points_by_id), request.render_budget),
    )


def _neighbor_preservation(
    points_by_id: dict[int, LayoutMetricPoint],
    reference_neighbors: tuple[ReferenceNeighborList, ...],
    *,
    neighbor_count: int,
    sample_limit: int,
) -> NeighborPreservationMetrics | None:
    if not reference_neighbors:
        return None
    selected = _evenly_spaced_sample(
        tuple(sorted(reference_neighbors, key=lambda item: item.entity_id)), sample_limit
    )
    point_count = len(points_by_id)
    reference_depths = [len(item.neighbor_ids) for item in selected]
    shared_neighbor_count = 0
    trustworthiness_penalty = 0
    exact = all(depth == point_count - 1 for depth in reference_depths)

    for reference in selected:
        mapped_neighbors = _nearest_point_ids(
            points_by_id,
            source_entity_id=reference.entity_id,
            neighbor_count=neighbor_count,
        )
        source_top_neighbors = set(reference.neighbor_ids[:neighbor_count])
        shared_neighbor_count += len(source_top_neighbors.intersection(mapped_neighbors))
        source_ranks = {entity_id: rank for rank, entity_id in enumerate(reference.neighbor_ids, 1)}
        for entity_id in mapped_neighbors:
            rank = source_ranks.get(entity_id, point_count - 1)
            trustworthiness_penalty += max(0, rank - neighbor_count)

    sample_count = len(selected)
    denominator = sample_count * neighbor_count * (2 * point_count - 3 * neighbor_count - 1)
    if denominator <= 0:
        raise ValueError("neighbor_count is too large for trustworthiness")
    trustworthiness = max(0.0, 1.0 - (2.0 * trustworthiness_penalty / denominator))
    return NeighborPreservationMetrics(
        sampled_entity_count=sample_count,
        neighbor_count=neighbor_count,
        reference_neighbor_recall=shared_neighbor_count / (sample_count * neighbor_count),
        trustworthiness=trustworthiness,
        trustworthiness_is_exact=exact,
        reference_depth_min=min(reference_depths),
        reference_depth_max=max(reference_depths),
    )


def _evenly_spaced_sample[T](items: tuple[T, ...], limit: int) -> tuple[T, ...]:
    if len(items) <= limit:
        return items
    return tuple(items[index * len(items) // limit] for index in range(limit))


def _nearest_point_ids(
    points_by_id: dict[int, LayoutMetricPoint],
    *,
    source_entity_id: int,
    neighbor_count: int,
) -> tuple[int, ...]:
    source = points_by_id[source_entity_id]
    distances = (
        ((point.x - source.x) ** 2 + (point.y - source.y) ** 2, entity_id)
        for entity_id, point in points_by_id.items()
        if entity_id != source_entity_id
    )
    nearest = heapq.nsmallest(neighbor_count, distances, key=lambda item: (item[0], item[1]))
    return tuple(entity_id for _, entity_id in nearest)


def _label_overlap(
    label_boxes: tuple[LabelBox, ...] | None,
    *,
    comparison_limit: int,
) -> LabelOverlapMetrics | None:
    if label_boxes is None:
        return None
    active: list[LabelBox] = []
    compared_pair_count = 0
    overlapping_pair_count = 0
    overlapping_entities: set[int] = set()
    overlap_area = 0.0
    complete = True

    for box in sorted(label_boxes, key=lambda item: (item.min_x, item.entity_id)):
        active = [candidate for candidate in active if candidate.max_x > box.min_x]
        for candidate in active:
            compared_pair_count += 1
            if compared_pair_count > comparison_limit:
                complete = False
                break
            if candidate.min_y < box.max_y and box.min_y < candidate.max_y:
                overlapping_pair_count += 1
                overlapping_entities.add(candidate.entity_id)
                overlapping_entities.add(box.entity_id)
                overlap_area += _overlap_area(candidate, box)
        if not complete:
            break
        active.append(box)

    return LabelOverlapMetrics(
        label_count=len(label_boxes),
        compared_pair_count=min(compared_pair_count, comparison_limit),
        comparison_complete=complete,
        overlapping_pair_count_lower_bound=overlapping_pair_count,
        overlapping_label_count_lower_bound=len(overlapping_entities),
        overlap_area_lower_bound=overlap_area,
    )


def _overlap_area(first: LabelBox, second: LabelBox) -> float:
    width = min(first.max_x, second.max_x) - max(first.min_x, second.min_x)
    height = min(first.max_y, second.max_y) - max(first.min_y, second.min_y)
    return max(0.0, width) * max(0.0, height)


def _viewport_density(
    points: Iterable[LayoutMetricPoint], density_grid: DensityGrid
) -> ViewportDensityMetrics:
    point_values = tuple(points)
    viewport = density_grid.viewport or _point_bounds(point_values)
    cell_counts = [0] * (density_grid.columns * density_grid.rows)
    outside_count = 0
    for point in point_values:
        if not _contains(viewport, point):
            outside_count += 1
            continue
        column = min(
            density_grid.columns - 1,
            int(
                (point.x - viewport.min_x)
                / (viewport.max_x - viewport.min_x)
                * density_grid.columns
            ),
        )
        row = min(
            density_grid.rows - 1,
            int((point.y - viewport.min_y) / (viewport.max_y - viewport.min_y) * density_grid.rows),
        )
        cell_counts[row * density_grid.columns + column] += 1

    visible_count = len(point_values) - outside_count
    occupied_count = sum(count > 0 for count in cell_counts)
    entropy = 0.0
    if visible_count > 0:
        for count in cell_counts:
            if count:
                probability = count / visible_count
                entropy -= probability * math.log(probability)
    max_entropy = math.log(len(cell_counts)) if len(cell_counts) > 1 else 0.0
    normalized_entropy = entropy / max_entropy if max_entropy else 0.0
    return ViewportDensityMetrics(
        viewport=viewport,
        columns=density_grid.columns,
        rows=density_grid.rows,
        visible_point_count=visible_count,
        outside_viewport_point_count=outside_count,
        occupied_cell_count=occupied_count,
        max_cell_point_count=max(cell_counts, default=0),
        normalized_entropy=normalized_entropy,
    )


def _point_bounds(points: tuple[LayoutMetricPoint, ...]) -> MetricViewport:
    min_x = min(point.x for point in points)
    max_x = max(point.x for point in points)
    min_y = min(point.y for point in points)
    max_y = max(point.y for point in points)
    if min_x == max_x:
        max_x += 1.0
    if min_y == max_y:
        max_y += 1.0
    return MetricViewport(min_x=min_x, min_y=min_y, max_x=max_x, max_y=max_y)


def _contains(viewport: MetricViewport, point: LayoutMetricPoint) -> bool:
    return (
        viewport.min_x <= point.x <= viewport.max_x and viewport.min_y <= point.y <= viewport.max_y
    )


def _community_fragmentation(
    memberships: tuple[CommunityMembership, ...] | None,
    edges: tuple[CommunityEdge, ...] | None,
) -> CommunityFragmentationMetrics | None:
    if memberships is None or edges is None:
        return None
    community_by_entity = {item.entity_id: item.community_id for item in memberships}
    parent = {entity_id: entity_id for entity_id in community_by_entity}
    _union_within_communities(parent, community_by_entity, edges)
    community_count, component_count, fragmented_count, largest_component_size = (
        _community_components(parent, memberships)
    )

    return CommunityFragmentationMetrics(
        community_count=community_count,
        fragmented_community_count=fragmented_count,
        component_count=component_count,
        largest_component_fraction=largest_component_size / len(memberships)
        if memberships
        else 0.0,
    )


def _union_within_communities(
    parent: dict[int, int], community_by_entity: dict[int, str], edges: tuple[CommunityEdge, ...]
) -> None:
    for edge in edges:
        source_community = community_by_entity.get(edge.source_entity_id)
        if source_community is None or source_community != community_by_entity.get(
            edge.target_entity_id
        ):
            continue
        source_root = _find(parent, edge.source_entity_id)
        target_root = _find(parent, edge.target_entity_id)
        if source_root != target_root:
            parent[target_root] = source_root


def _find(parent: dict[int, int], entity_id: int) -> int:
    root = entity_id
    while parent[root] != root:
        root = parent[root]
    while parent[entity_id] != entity_id:
        next_entity_id = parent[entity_id]
        parent[entity_id] = root
        entity_id = next_entity_id
    return root


def _community_components(
    parent: dict[int, int], memberships: tuple[CommunityMembership, ...]
) -> tuple[int, int, int, int]:
    entities_by_community: dict[str, list[int]] = defaultdict(list)
    for membership in memberships:
        entities_by_community[membership.community_id].append(membership.entity_id)
    component_count = 0
    fragmented_count = 0
    largest_component_size = 0
    for entities in entities_by_community.values():
        components: dict[int, int] = defaultdict(int)
        for entity_id in entities:
            components[_find(parent, entity_id)] += 1
        component_count += len(components)
        fragmented_count += len(components) > 1
        largest_component_size = max(largest_component_size, *components.values())
    return len(entities_by_community), component_count, fragmented_count, largest_component_size


def _temporal_displacement(
    points_by_id: dict[int, LayoutMetricPoint], previous_layout: VersionedPointLayout | None
) -> TemporalDisplacementMetrics | None:
    if previous_layout is None:
        return None
    previous_points = {point.entity_id: point for point in previous_layout.points}
    common_entity_ids = points_by_id.keys() & previous_points.keys()
    displacements = sorted(
        math.hypot(
            points_by_id[entity_id].x - previous_points[entity_id].x,
            points_by_id[entity_id].y - previous_points[entity_id].y,
        )
        for entity_id in common_entity_ids
    )
    return TemporalDisplacementMetrics(
        common_entity_count=len(common_entity_ids),
        added_entity_count=len(points_by_id.keys() - previous_points.keys()),
        removed_entity_count=len(previous_points.keys() - points_by_id.keys()),
        mean_displacement=sum(displacements) / len(displacements) if displacements else 0.0,
        median_displacement=_median(displacements),
        percentile_95_displacement=_percentile_95(displacements),
    )


def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    midpoint = len(values) // 2
    if len(values) % 2:
        return values[midpoint]
    return (values[midpoint - 1] + values[midpoint]) / 2.0


def _percentile_95(values: list[float]) -> float:
    if not values:
        return 0.0
    return values[math.ceil(len(values) * 0.95) - 1]


def _determinism(
    layout: VersionedPointLayout, repeat_layout: VersionedPointLayout | None
) -> DeterminismMetrics:
    coordinate_sha256 = _coordinate_sha256(layout.points)
    if repeat_layout is None:
        return DeterminismMetrics(coordinate_sha256=coordinate_sha256)
    repeat_sha256 = _coordinate_sha256(repeat_layout.points)
    current_points = {point.entity_id: point for point in layout.points}
    repeat_points = {point.entity_id: point for point in repeat_layout.points}
    changed_count = sum(
        current_points.get(entity_id) != repeat_points.get(entity_id)
        for entity_id in current_points.keys() | repeat_points.keys()
    )
    return DeterminismMetrics(
        coordinate_sha256=coordinate_sha256,
        repeat_coordinate_sha256=repeat_sha256,
        exact_repeat_match=coordinate_sha256 == repeat_sha256,
        changed_or_missing_entity_count=changed_count,
    )


def _coordinate_sha256(points: tuple[LayoutMetricPoint, ...]) -> str:
    digest = hashlib.sha256()
    for point in sorted(points, key=lambda item: item.entity_id):
        x = 0.0 if point.x == 0.0 else point.x
        y = 0.0 if point.y == 0.0 else point.y
        digest.update(struct.pack(">qdd", point.entity_id, x, y))
    return digest.hexdigest()


def _render_budget(point_count: int, render_input: RenderBudgetInput) -> DomRenderBudgetMetrics:
    interactive_point_count = (
        point_count
        if render_input.interactive_point_count is None
        else render_input.interactive_point_count
    )
    return DomRenderBudgetMetrics(
        interactive_point_count=interactive_point_count,
        label_count=render_input.label_count,
        edge_count=render_input.edge_count,
        estimated_svg_element_count=2 * interactive_point_count
        + render_input.label_count
        + render_input.edge_count,
        estimated_svg_keyboard_stop_count=interactive_point_count,
        estimated_canvas_draw_operations=point_count
        + render_input.label_count
        + render_input.edge_count,
        label_character_count=render_input.label_character_count,
    )
