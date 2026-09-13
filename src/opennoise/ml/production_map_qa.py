"""Fail-closed acceptance gates for the single production semantic-zoom map."""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass
from hashlib import sha256
from itertools import pairwise
from pathlib import Path
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from collections.abc import Iterable

    from opennoise.models.production_qa import (
        ProductionMapAcceptanceInput,
        ProductionMapLabelBox,
        ProductionMapLod,
        ProductionMapRegion,
    )

_DESKTOP = (1366, 768)
_MOBILE = (390, 844)
_GRID_COLUMNS = 16
_GRID_ROWS = 9
_MIN_CENTRAL_SPAN = 0.45
_MIN_OCCUPIED_FRACTION = 0.20
_MAX_DENSEST_CELL_FRACTION = 0.15
_MAX_ISOLATED_NODE_FRACTION = 0.05
_MAX_REGION_ESCAPE_FRACTION = 0.02
_MAX_DESKTOP_LABEL_OVERLAP_FRACTION = 0.02
_MAX_MOBILE_LABEL_OVERLAP_FRACTION = 0.03
_MAX_DESKTOP_LABELS_BY_LOD = (48, 80, 128, 180)
_MAX_MOBILE_LABELS_BY_LOD = (24, 40, 64, 80)
_MIN_DESKTOP_LABEL_FONT_SIZE_PX = 12.0
_MIN_MOBILE_LABEL_FONT_SIZE_PX = 12.0
_MIN_NORMALIZED_TOP_10_QUALITY = 0.98
_MIN_TOP_10_ABSOLUTE_LIFT_ABOVE_RANDOM = 0.15
_MIN_EVALUATED_ENTITIES = 2
_FIFTH_NEIGHBOR_INDEX = 5
_MAX_FIFTH_NEIGHBOR_DISTANCE = 0.45


class ProductionMapAcceptanceError(ValueError):
    """Raised when a production map has incomplete or failing evidence."""


@dataclass(frozen=True, slots=True)
class LabelCollisionSummary:
    """Complete collision measurement for one LOD and viewport."""

    label_count: int
    overlapping_label_count: int
    overlapping_pair_count: int

    @property
    def overlap_fraction(self) -> float:
        """Return the fraction of labels involved in at least one collision."""
        return self.overlapping_label_count / self.label_count if self.label_count else 0.0


@dataclass(frozen=True, slots=True)
class ProductionMapAcceptanceResult:
    """Numeric gates plus every rejection reason for a proposed production artifact."""

    accepted: bool
    failures: tuple[str, ...]
    central_span_x: float
    central_span_y: float
    occupied_cell_fraction: float
    densest_cell_fraction: float
    isolated_node_fraction: float
    minimum_region_containment: float
    root_region_overlap_count: int
    desktop_label_collisions: tuple[LabelCollisionSummary, ...]
    mobile_label_collisions: tuple[LabelCollisionSummary, ...]
    lod_persistent: bool
    top_10_recall: float
    top_25_recall: float
    normalized_top_10_quality: float


def evaluate_production_map(value: ProductionMapAcceptanceInput) -> ProductionMapAcceptanceResult:
    """Evaluate geometry, LOD, visual evidence, and interaction evidence without a browser."""
    coordinates = {item.entity_id: (float(item.x), float(item.y)) for item in value.coordinates}
    failures: list[str] = []
    span_x = _central_span(point[0] for point in coordinates.values())
    span_y = _central_span(point[1] for point in coordinates.values())
    if span_x < _MIN_CENTRAL_SPAN or span_y < _MIN_CENTRAL_SPAN:
        failures.append(
            f"central p05-p95 span must be >= {_MIN_CENTRAL_SPAN:.2f} on both axes; "
            f"got {span_x:.4f}, {span_y:.4f}"
        )
    occupied_fraction, densest_fraction = _grid_coverage(tuple(coordinates.values()))
    if occupied_fraction < _MIN_OCCUPIED_FRACTION:
        failures.append(
            f"16x9 viewport occupancy must be >= {_MIN_OCCUPIED_FRACTION:.2f}; "
            f"got {occupied_fraction:.4f}"
        )
    if densest_fraction > _MAX_DENSEST_CELL_FRACTION:
        failures.append(
            f"densest 16x9 cell must hold <= {_MAX_DENSEST_CELL_FRACTION:.2f} of nodes; "
            f"got {densest_fraction:.4f}"
        )
    duplicate_count = len(coordinates) - len(set(coordinates.values()))
    if duplicate_count:
        failures.append(f"coordinates contain {duplicate_count} duplicate positions")
    isolated_fraction = _isolated_node_fraction(tuple(coordinates.values()))
    if isolated_fraction > _MAX_ISOLATED_NODE_FRACTION:
        failures.append(
            f"spatial outliers must be <= {_MAX_ISOLATED_NODE_FRACTION:.2f}; "
            f"got {isolated_fraction:.4f}"
        )

    _presentation_parent_failures(value, coordinates, failures)
    _taxonomy_failures(value, coordinates, failures)
    minimum_containment = _region_containment(value.regions, coordinates)
    if value.regions and minimum_containment < 1.0 - _MAX_REGION_ESCAPE_FRACTION:
        failures.append(
            "each emitted hierarchy region must contain >= "
            f"{1.0 - _MAX_REGION_ESCAPE_FRACTION:.2f} "
            f"of declared nodes; got {minimum_containment:.4f}"
        )
    root_overlap_count = _root_region_overlap_count(value.regions)
    if root_overlap_count:
        failures.append(f"root hierarchy regions overlap in {root_overlap_count} pair(s)")

    lod_persistent = _lod_failures(value, coordinates, failures)
    desktop_collisions, mobile_collisions = _label_collision_failures(value, failures)
    _similarity_failures(value, failures)
    _screenshot_failures(value, failures)
    _interaction_failures(value, failures)

    return ProductionMapAcceptanceResult(
        accepted=not failures,
        failures=tuple(failures),
        central_span_x=span_x,
        central_span_y=span_y,
        occupied_cell_fraction=occupied_fraction,
        densest_cell_fraction=densest_fraction,
        isolated_node_fraction=isolated_fraction,
        minimum_region_containment=minimum_containment,
        root_region_overlap_count=root_overlap_count,
        desktop_label_collisions=desktop_collisions,
        mobile_label_collisions=mobile_collisions,
        lod_persistent=lod_persistent,
        top_10_recall=float(value.similarity.top_10_recall),
        top_25_recall=float(value.similarity.top_25_recall),
        normalized_top_10_quality=_normalized_top_10_quality(value),
    )


def require_accepted_production_map(
    value: ProductionMapAcceptanceInput,
) -> ProductionMapAcceptanceResult:
    """Return the complete report, or stop publication with every failing gate."""
    result = evaluate_production_map(value)
    if not result.accepted:
        raise ProductionMapAcceptanceError("\n".join(result.failures))
    return result


def _central_span(values: Iterable[float]) -> float:
    ordered = sorted(values)
    count = len(ordered)
    lower = ordered[math.floor((count - 1) * 0.05)]
    upper = ordered[math.ceil((count - 1) * 0.95)]
    return upper - lower


def _grid_coverage(points: tuple[tuple[float, float], ...]) -> tuple[float, float]:
    cells: Counter[tuple[int, int]] = Counter()
    for x, y in points:
        column = min(_GRID_COLUMNS - 1, int(x * _GRID_COLUMNS))
        row = min(_GRID_ROWS - 1, int(y * _GRID_ROWS))
        cells[column, row] += 1
    return (
        len(cells) / (_GRID_COLUMNS * _GRID_ROWS),
        max(cells.values()) / len(points),
    )


def _isolated_node_fraction(points: tuple[tuple[float, float], ...]) -> float:
    """Count nodes whose fifth spatial neighbor is beyond 45% of map width/height."""
    if len(points) <= _FIFTH_NEIGHBOR_INDEX:
        return 1.0
    distances: list[float] = []
    for x, y in points:
        ranked = sorted(math.hypot(x - other_x, y - other_y) for other_x, other_y in points)
        distances.append(ranked[_FIFTH_NEIGHBOR_INDEX])
    return sum(distance > _MAX_FIFTH_NEIGHBOR_DISTANCE for distance in distances) / len(distances)


def _presentation_parent_failures(
    value: ProductionMapAcceptanceInput,
    coordinates: dict[str, tuple[float, float]],
    failures: list[str],
) -> None:
    parents = {item.child_id: item for item in value.presentation_parents}
    if len(parents) != len(value.presentation_parents):
        failures.append("presentation-parent choices must be unique per child")
    missing = sorted(set(coordinates) - set(parents))
    if missing:
        failures.append(f"{len(missing)} coordinates lack an explicit presentation-parent choice")
    taxonomy = set(value.taxonomy_edges)
    failures.extend(
        f"taxonomy presentation parent for {parent.child_id} is not in full taxonomy"
        for parent in value.presentation_parents
        if parent.relation == "taxonomy" and (parent.child_id, parent.parent_id) not in taxonomy
    )


def _taxonomy_failures(
    value: ProductionMapAcceptanceInput,
    coordinates: dict[str, tuple[float, float]],
    failures: list[str],
) -> None:
    edges = set(value.taxonomy_edges)
    if len(edges) != len(value.taxonomy_edges):
        failures.append("full taxonomy edges must be unique")
    unknown = {entity_id for edge in edges for entity_id in edge if entity_id not in coordinates}
    if unknown:
        failures.append(
            f"full taxonomy includes {len(unknown)} nodes without production coordinates"
        )
    parents: dict[str, set[str]] = {}
    for child, parent in edges:
        parents.setdefault(child, set()).add(parent)
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(entity_id: str) -> bool:
        if entity_id in visited:
            return False
        if entity_id in visiting:
            return True
        visiting.add(entity_id)
        has_cycle = any(visit(parent) for parent in parents.get(entity_id, ()))
        visiting.remove(entity_id)
        visited.add(entity_id)
        return has_cycle

    if any(visit(entity_id) for entity_id in parents):
        failures.append("full taxonomy contains a directed cycle")


def _region_containment(
    regions: tuple[ProductionMapRegion, ...], coordinates: dict[str, tuple[float, float]]
) -> float:
    if not regions:
        return 1.0
    fractions: list[float] = []
    for region in regions:
        contained = sum(
            region.min_x <= coordinates[entity_id][0] <= region.max_x
            and region.min_y <= coordinates[entity_id][1] <= region.max_y
            for entity_id in region.entity_ids
        )
        fractions.append(contained / len(region.entity_ids))
    return min(fractions)


def _root_region_overlap_count(regions: tuple[ProductionMapRegion, ...]) -> int:
    total = 0
    non_overlapping = [region for region in regions if region.is_root and not region.allow_overlap]
    for index, first in enumerate(non_overlapping):
        for second in non_overlapping[index + 1 :]:
            horizontal_overlap = first.min_x < second.max_x and second.min_x < first.max_x
            vertical_overlap = first.min_y < second.max_y and second.min_y < first.max_y
            if horizontal_overlap and vertical_overlap:
                total += 1
    return total


def _lod_failures(
    value: ProductionMapAcceptanceInput,
    coordinates: dict[str, tuple[float, float]],
    failures: list[str],
) -> bool:
    lods = tuple(sorted(value.lods, key=lambda lod: lod.level))
    expected_levels = tuple(range(len(lods)))
    if tuple(lod.level for lod in lods) != expected_levels:
        failures.append("LOD levels must start at zero and be contiguous")
        return False
    persistent = all(
        set(previous.visible_entity_ids).issubset(current.visible_entity_ids)
        for previous, current in pairwise(lods)
    )
    if not persistent:
        failures.append("semantic-zoom nodes must persist from every LOD into the next")
    if set(lods[-1].visible_entity_ids) != set(coordinates):
        failures.append("final semantic-zoom LOD must expose every mapped coordinate")
    return persistent


def _label_collision_failures(
    value: ProductionMapAcceptanceInput, failures: list[str]
) -> tuple[tuple[LabelCollisionSummary, ...], tuple[LabelCollisionSummary, ...]]:
    lods = tuple(sorted(value.lods, key=lambda lod: lod.level))
    desktop = tuple(_label_collisions(lod.desktop_labels) for lod in lods)
    mobile = tuple(_label_collisions(lod.mobile_labels) for lod in lods)
    if any(item.overlap_fraction > _MAX_DESKTOP_LABEL_OVERLAP_FRACTION for item in desktop):
        failures.append(
            "desktop labels overlap above "
            f"{_MAX_DESKTOP_LABEL_OVERLAP_FRACTION:.2f} at one or more LODs"
        )
    if any(item.overlap_fraction > _MAX_MOBILE_LABEL_OVERLAP_FRACTION for item in mobile):
        failures.append(
            "mobile labels overlap above "
            f"{_MAX_MOBILE_LABEL_OVERLAP_FRACTION:.2f} at one or more LODs"
        )
    _label_readability_failures(
        lods,
        viewport="desktop",
        label_budgets=_MAX_DESKTOP_LABELS_BY_LOD,
        minimum_font_size_px=_MIN_DESKTOP_LABEL_FONT_SIZE_PX,
        failures=failures,
    )
    _label_readability_failures(
        lods,
        viewport="mobile",
        label_budgets=_MAX_MOBILE_LABELS_BY_LOD,
        minimum_font_size_px=_MIN_MOBILE_LABEL_FONT_SIZE_PX,
        failures=failures,
    )
    return desktop, mobile


def _label_readability_failures(
    lods: tuple[ProductionMapLod, ...],
    *,
    viewport: Literal["desktop", "mobile"],
    label_budgets: tuple[int, ...],
    minimum_font_size_px: float,
    failures: list[str],
) -> None:
    """Reject unreadably dense or undersized labels at each semantic zoom level."""
    for lod in lods:
        labels = lod.desktop_labels if viewport == "desktop" else lod.mobile_labels
        budget = label_budgets[min(lod.level, len(label_budgets) - 1)]
        if len(labels) > budget:
            failures.append(
                f"{viewport} LOD {lod.level} shows {len(labels)} labels; maximum is {budget}"
            )
        if any(float(label.font_size_px) < minimum_font_size_px for label in labels):
            failures.append(
                f"{viewport} LOD {lod.level} uses labels below {minimum_font_size_px:.0f}px"
            )


def _label_collisions(labels: tuple[ProductionMapLabelBox, ...]) -> LabelCollisionSummary:
    active: list[ProductionMapLabelBox] = []
    overlapping_ids: set[str] = set()
    pairs = 0
    for label in sorted(labels, key=lambda item: (item.min_x, item.entity_id)):
        active = [candidate for candidate in active if candidate.max_x > label.min_x]
        for candidate in active:
            if candidate.min_y < label.max_y and label.min_y < candidate.max_y:
                pairs += 1
                overlapping_ids.add(candidate.entity_id)
                overlapping_ids.add(label.entity_id)
        active.append(label)
    return LabelCollisionSummary(len(labels), len(overlapping_ids), pairs)


def _similarity_failures(value: ProductionMapAcceptanceInput, failures: list[str]) -> None:
    similarity = value.similarity
    normalized_quality = _normalized_top_10_quality(value)
    if normalized_quality < _MIN_NORMALIZED_TOP_10_QUALITY:
        failures.append(
            "one-hop top-10 normalized quality against the same-scope canonical spectral baseline "
            f"must be >= {_MIN_NORMALIZED_TOP_10_QUALITY:.2f}; got {normalized_quality:.4f}"
        )
    lift = similarity.top_10_recall - similarity.random_top_10_recall
    if lift < _MIN_TOP_10_ABSOLUTE_LIFT_ABOVE_RANDOM:
        failures.append(
            "one-hop top-10 recall must exceed the exact random null by "
            f">= {_MIN_TOP_10_ABSOLUTE_LIFT_ABOVE_RANDOM:.2f}; got {lift:.4f}"
        )
    if similarity.evaluated_entity_count < _MIN_EVALUATED_ENTITIES:
        failures.append("similarity evidence needs at least two eligible mapped entities")


def _normalized_top_10_quality(value: ProductionMapAcceptanceInput) -> float:
    similarity = value.similarity
    return (similarity.top_10_recall - similarity.random_top_10_recall) / (
        similarity.canonical_baseline_top_10_recall - similarity.random_top_10_recall
    )


def _screenshot_failures(value: ProductionMapAcceptanceInput, failures: list[str]) -> None:
    expected = {
        ("desktop", "light", *_DESKTOP),
        ("desktop", "dark", *_DESKTOP),
        ("desktop", "system", *_DESKTOP),
        ("mobile", "light", *_MOBILE),
        ("mobile", "dark", *_MOBILE),
        ("mobile", "system", *_MOBILE),
    }
    actual = {
        (item.viewport, item.color_scheme, item.width, item.height) for item in value.screenshots
    }
    if not expected.issubset(actual):
        failures.append(
            "missing deterministic desktop/mobile light/dark/system screenshot evidence"
        )
    for screenshot in value.screenshots:
        path = Path(screenshot.path)
        if not path.is_file():
            failures.append(f"generated screenshot is missing: {path}")
            continue
        if path.stat().st_size != screenshot.byte_size:
            failures.append(f"generated screenshot byte size differs from evidence: {path}")
        digest = sha256(path.read_bytes()).hexdigest()
        if digest != screenshot.sha256:
            failures.append(f"generated screenshot hash differs from evidence: {path}")


def _interaction_failures(value: ProductionMapAcceptanceInput, failures: list[str]) -> None:
    if value.interactions is None:
        failures.append("missing deterministic interaction/accessibility evidence")
        return
    failed = [
        name
        for name, passed in value.interactions.model_dump(mode="python").items()
        if isinstance(passed, bool) and not passed
    ]
    if failed:
        failures.append(f"failed interaction/accessibility checks: {', '.join(failed)}")
