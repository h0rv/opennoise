"""Build small, deterministic SVG maps from already verified Open v2 coordinates."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Protocol

_CANVAS_WIDTH: Final = 1600.0
_CANVAS_HEIGHT: Final = 900.0
_ASPECT_RATIO: Final = _CANVAS_WIDTH / _CANVAS_HEIGHT
_MINIMUM_SPAN: Final = 320.0
_PADDING_RATIO: Final = 0.08
_LABEL_HEIGHT: Final = 18.0
_LABEL_CHARACTER_WIDTH: Final = 7.0


class _MapNode(Protocol):
    @property
    def node_id(self) -> str: ...

    @property
    def name(self) -> str: ...

    @property
    def x(self) -> float: ...

    @property
    def y(self) -> float: ...

    @property
    def degree(self) -> int: ...

    @property
    def hierarchy_depth(self) -> int: ...


class _MapEdge(Protocol):
    @property
    def source(self) -> str: ...

    @property
    def target(self) -> str: ...

    @property
    def factual_relationship(self) -> bool: ...


@dataclass(frozen=True, slots=True)
class StaticOpenMapNode:
    """One linkable point in a small server-rendered SVG map."""

    node: _MapNode
    x: float
    y: float
    label_visible: bool
    focused: bool


@dataclass(frozen=True, slots=True)
class StaticOpenMapEdge:
    """One typed edge whose endpoints are visible in the SVG map."""

    source: _MapNode
    target: _MapNode
    factual: bool
    source_x: float
    source_y: float
    target_x: float
    target_y: float


@dataclass(frozen=True, slots=True)
class StaticOpenMap:
    """A rectangular, bounded SVG map with collision-culled labels."""

    nodes: tuple[StaticOpenMapNode, ...]
    edges: tuple[StaticOpenMapEdge, ...]
    total_node_count: int
    label_count: int
    view_box: str = "0 0 1600 900"


@dataclass(frozen=True, slots=True)
class _LabelBox:
    minimum_x: float
    minimum_y: float
    maximum_x: float
    maximum_y: float

    def intersects(self, other: _LabelBox) -> bool:
        return (
            self.minimum_x < other.maximum_x
            and self.maximum_x > other.minimum_x
            and self.minimum_y < other.maximum_y
            and self.maximum_y > other.minimum_y
        )


def build_static_open_map(
    nodes: tuple[_MapNode, ...],
    edges: tuple[_MapEdge, ...] = (),
    *,
    total_node_count: int,
    focused_node_id: str | None = None,
    label_budget: int,
) -> StaticOpenMap:
    """Return a static map without client-side layout, simulation, or culling."""
    if not nodes:
        raise ValueError("static Open map requires at least one node")
    if label_budget < 1:
        raise ValueError("static Open map label budget must be positive")
    if total_node_count < len(nodes):
        raise ValueError("static Open map total node count cannot be smaller than visible nodes")

    positions = _normalized_positions(nodes)
    visible_by_id = {node.node_id: node for node in nodes}
    static_edges = tuple(
        StaticOpenMapEdge(
            source=visible_by_id[edge.source],
            target=visible_by_id[edge.target],
            factual=edge.factual_relationship,
            source_x=positions[edge.source][0],
            source_y=positions[edge.source][1],
            target_x=positions[edge.target][0],
            target_y=positions[edge.target][1],
        )
        for edge in edges
        if edge.source in visible_by_id and edge.target in visible_by_id
    )
    labels = _visible_labels(
        nodes, positions, focused_node_id=focused_node_id, label_budget=label_budget
    )
    static_nodes = tuple(
        StaticOpenMapNode(
            node=node,
            x=positions[node.node_id][0],
            y=positions[node.node_id][1],
            label_visible=node.node_id in labels,
            focused=node.node_id == focused_node_id,
        )
        for node in nodes
    )
    return StaticOpenMap(
        nodes=static_nodes,
        edges=static_edges,
        total_node_count=total_node_count,
        label_count=len(labels),
    )


def _normalized_positions(nodes: tuple[_MapNode, ...]) -> dict[str, tuple[float, float]]:
    """Map source-neutral artifact coordinates into one fixed rectangular SVG space."""
    minimum_x = min(node.x for node in nodes)
    maximum_x = max(node.x for node in nodes)
    minimum_y = min(node.y for node in nodes)
    maximum_y = max(node.y for node in nodes)
    width = max(_MINIMUM_SPAN, maximum_x - minimum_x)
    height = max(_MINIMUM_SPAN, maximum_y - minimum_y)
    width *= 1 + 2 * _PADDING_RATIO
    height *= 1 + 2 * _PADDING_RATIO
    if width / height < _ASPECT_RATIO:
        width = height * _ASPECT_RATIO
    else:
        height = width / _ASPECT_RATIO
    center_x = (minimum_x + maximum_x) / 2
    center_y = (minimum_y + maximum_y) / 2
    scale = min(_CANVAS_WIDTH / width, _CANVAS_HEIGHT / height)
    return {
        node.node_id: (
            round((node.x - center_x) * scale + _CANVAS_WIDTH / 2, 3),
            round((node.y - center_y) * scale + _CANVAS_HEIGHT / 2, 3),
        )
        for node in nodes
    }


def _visible_labels(
    nodes: tuple[_MapNode, ...],
    positions: dict[str, tuple[float, float]],
    *,
    focused_node_id: str | None,
    label_budget: int,
) -> frozenset[str]:
    ordered = sorted(
        nodes,
        key=lambda node: (
            node.node_id != focused_node_id,
            -node.degree,
            node.hierarchy_depth,
            node.name.casefold(),
            node.node_id,
        ),
    )
    accepted: list[_LabelBox] = []
    labels: set[str] = set()
    for node in ordered:
        if len(labels) == label_budget:
            break
        width = max(72.0, min(260.0, len(node.name) * _LABEL_CHARACTER_WIDTH))
        candidate = _LabelBox(
            minimum_x=positions[node.node_id][0] + 9.0,
            minimum_y=positions[node.node_id][1] - _LABEL_HEIGHT / 2,
            maximum_x=positions[node.node_id][0] + 9.0 + width,
            maximum_y=positions[node.node_id][1] + _LABEL_HEIGHT / 2,
        )
        if node.node_id != focused_node_id and any(
            candidate.intersects(existing) for existing in accepted
        ):
            continue
        accepted.append(candidate)
        labels.add(node.node_id)
    return frozenset(labels)
