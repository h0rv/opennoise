"""Build a compact landscape map from public structural evidence only."""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from collections import Counter, defaultdict
from contextlib import closing
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, cast

import numpy as np
from scipy.spatial import KDTree

from opennoise.ml.layout_lenses import build_weighted_spectral_coordinates
from opennoise.ml.semantic_layout.atlas import AtlasPoint, AtlasSettings, build_rectangular_atlas

from .contracts import (
    CameraBounds,
    EvidenceKind,
    GeometryMetrics,
    InputBinding,
    OverviewCommunity,
    SemanticCoordinate,
    SemanticLayoutArtifact,
    SemanticLayoutError,
    SemanticLayoutInputs,
    SemanticLayoutSettings,
    StructuralEdge,
    UnplacedSeed,
    semantic_layout_settings_sha256,
    semantic_layout_sha256,
    verify_semantic_map_layout,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping
    from pathlib import Path

type Edge = tuple[str, str]
type EdgeKinds = frozenset[str]

_SHA256_LENGTH = 64
_SEED_COUNT = 6_291
_PAIR_NODE_COUNT = 2
_LOD_TWO_IMPORTANCE_FRACTION = 0.1
_MINIMUM_PEER_KNN = 0.16
_MINIMUM_COLISTEN_SEEDS = 400
_MINIMUM_COLISTEN_KNN = 0.10
_MAXIMUM_HIERARCHY_DISTANCE = 0.16
_MINIMUM_WIDTH_OCCUPANCY = 0.70
_MINIMUM_HEIGHT_OCCUPANCY = 0.65
_MAXIMUM_OCCUPANCY = 0.90
_QUALITY_GATE_MINIMUM_SEEDS = 100
_MINIMUM_OVERVIEW_ROOT_COVERAGE = 0.75
_INITIAL_CAMERA_PADDING_FRACTION = 0.04
_MINIMUM_OVERVIEW_ANCHORS = 2
_ATLAS_MARGIN = 0.11


@dataclass(frozen=True, slots=True)
class _Region:
    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def width(self) -> float:
        return self.x1 - self.x0

    @property
    def height(self) -> float:
        return self.y1 - self.y0


@dataclass(frozen=True, slots=True)
class _OverviewSelectionContext:
    names: Mapping[str, str]
    positions: Mapping[str, tuple[float, float]]
    roots: Mapping[str, str | None]
    depths: Mapping[str, int]
    degree: Mapping[str, float]
    world_width: float
    budget: int


@dataclass(frozen=True, slots=True)
class _SemanticRegion:
    """One non-geometric map region with a real structural membership rule.

    Hierarchy regions contain an entire display-tree family rooted at an
    evidenced umbrella.  Remaining nodes have no display-tree family and are
    grouped only by their existing peer-manifold component.  Neither case is
    a screen-space partition: a region cannot be created by slicing a
    rectangle into equally sized cells.
    """

    kind: Literal["hierarchy", "component"]
    key: str
    members: tuple[str, ...]
    anchor: str


def _canonical_sha256(value: object) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, allow_nan=False, separators=(",", ":"), sort_keys=True
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def _file_binding(role: str, path: Path, logical_sha256: str | None = None) -> InputBinding:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
            size += len(block)
    return InputBinding(
        role=role,
        byte_sha256=digest.hexdigest(),
        byte_count=size,
        logical_sha256=logical_sha256,
    )


def _verified_json(path: Path, *, digest_key: str = "output_sha256") -> dict[str, object]:
    try:
        value = json.loads(path.read_bytes())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise SemanticLayoutError(f"cannot parse JSON artifact: {path}") from error
    if not isinstance(value, dict):
        raise SemanticLayoutError(f"JSON artifact must be an object: {path}")
    claimed = value.get(digest_key)
    without_digest = {key: item for key, item in value.items() if key != digest_key}
    if not isinstance(claimed, str) or claimed != _canonical_sha256(without_digest):
        raise SemanticLayoutError(f"JSON artifact digest does not replay: {path}")
    return {str(key): item for key, item in value.items()}


def _canonical_edge(left: str, right: str) -> Edge:
    if left == right:
        raise SemanticLayoutError("self relations are not drawable structural edges")
    return (left, right) if left < right else (right, left)


def _peer_input(path: Path) -> tuple[dict[str, str], dict[Edge, float], InputBinding]:
    """Read only stable seeds and peer scores, not any historical-evaluation metadata."""
    try:
        with closing(sqlite3.connect(f"file:{path.resolve()}?mode=ro&immutable=1", uri=True)) as db:
            metadata = {
                str(key): str(value) for key, value in db.execute("SELECT key, value FROM metadata")
            }
            if metadata.get("non_production_candidate") != "true":
                raise SemanticLayoutError("peer index must identify itself as a bounded candidate")
            logical = metadata.get("artifact_output_sha256")
            if logical is None or len(logical) != _SHA256_LENGTH:
                raise SemanticLayoutError("peer index has no valid source logical digest")
            names = {
                str(seed_id): str(name)
                for seed_id, name in db.execute("SELECT source_item_id, seed_name FROM seed")
            }
            weights = {
                _canonical_edge(str(left), str(right)): math.sqrt(float(score))
                for left, right, score in db.execute(
                    "SELECT source_genre_id, target_genre_id, score FROM peer_edge"
                )
                if math.isfinite(float(score)) and float(score) > 0.0
            }
    except sqlite3.Error as error:
        raise SemanticLayoutError("peer index schema or rows are invalid") from error
    if len(names) != _SEED_COUNT:
        raise SemanticLayoutError(
            f"peer index must contain exactly 6291 stable seeds, got {len(names)}"
        )
    if len(weights) == 0:
        raise SemanticLayoutError("peer index has no positive structural edges")
    return names, weights, _file_binding("peer_index", path, logical)


def _hierarchy_input(
    path: Path, seed_ids: set[str], settings: SemanticLayoutSettings
) -> tuple[dict[Edge, float], dict[str, dict[str, float]], InputBinding]:
    value = _verified_json(path)
    if value.get("historical_inputs_used_for_construction") is not False:
        raise SemanticLayoutError("hierarchy artifact is not source-neutral")
    claimed = str(value["output_sha256"])
    raw_edges = value.get("edges")
    if not isinstance(raw_edges, list):
        raise SemanticLayoutError("hierarchy artifact has no edge list")
    weights: dict[Edge, float] = {}
    directed: dict[str, dict[str, float]] = defaultdict(dict)
    for raw in raw_edges:
        if not isinstance(raw, dict) or raw.get("included_in_dag") is not True:
            continue
        child = raw.get("child_seed_id")
        parent = raw.get("parent_seed_id")
        score = raw.get("review_score")
        if (
            not isinstance(child, str)
            or not isinstance(parent, str)
            or child not in seed_ids
            or parent not in seed_ids
        ):
            raise SemanticLayoutError("hierarchy edge endpoint is outside stable seed universe")
        if not isinstance(score, (int, float)) or not math.isfinite(float(score)):
            raise SemanticLayoutError("hierarchy edge score is invalid")
        edge = _canonical_edge(child, parent)
        weight = settings.hierarchy_weight_floor + settings.hierarchy_weight_scale * float(score)
        weights[edge] = max(weights.get(edge, 0.0), weight)
        directed[child][parent] = max(directed[child].get(parent, 0.0), weight)
    if not weights:
        raise SemanticLayoutError("hierarchy artifact has no included DAG relations")
    return weights, directed, _file_binding("hierarchy_artifact", path, claimed)


def _colisten_input(
    artifact_path: Path, cache_path: Path, seed_ids: set[str], scale: float
) -> tuple[dict[Edge, float], InputBinding, InputBinding]:
    value = _verified_json(artifact_path)
    if (
        value.get("historical_inputs_read_for_construction") is not False
        or value.get("audio_read_for_construction") is not False
        or value.get("listener_identifiers_read_for_construction") is not False
    ):
        raise SemanticLayoutError("co-listen artifact violates the open structural input policy")
    cache_hash = value.get("cache_database_sha256")
    if (
        not isinstance(cache_hash, str)
        or _file_binding("cache", cache_path).byte_sha256 != cache_hash
    ):
        raise SemanticLayoutError("co-listen cache bytes do not bind the sealed artifact")
    claimed = str(value["output_sha256"])
    try:
        with closing(
            sqlite3.connect(f"file:{cache_path.resolve()}?mode=ro&immutable=1", uri=True)
        ) as db:
            rows = db.execute(
                "SELECT seed_id, neighbor_seed_id, shrunk_npmi FROM neighbor "
                "WHERE channel = 'artist_direct'"
            )
            weights: dict[Edge, float] = {}
            for left, right, score in rows:
                left_id, right_id, raw_score = str(left), str(right), float(score)
                if left_id not in seed_ids or right_id not in seed_ids:
                    raise SemanticLayoutError("co-listen relation endpoint is outside stable seeds")
                if raw_score <= 0.0 or not math.isfinite(raw_score):
                    continue
                edge = _canonical_edge(left_id, right_id)
                weights[edge] = max(weights.get(edge, 0.0), scale * math.sqrt(raw_score))
    except sqlite3.Error as error:
        raise SemanticLayoutError("co-listen cache schema or rows are invalid") from error
    if not weights:
        raise SemanticLayoutError("co-listen cache contains no usable direct channel relations")
    return (
        weights,
        _file_binding("colisten_artifact", artifact_path, claimed),
        _file_binding("colisten_cache", cache_path, cache_hash),
    )


def _peer_manifold_input(
    path: Path, names: Mapping[str, str], peer_binding: InputBinding
) -> tuple[dict[str, tuple[float, float, int]], InputBinding]:
    """Read the peer-only manifold, which is public-evidence layout input, not history."""
    value = _verified_json(path)
    if (
        value.get("publication_scope") != "local_research_only"
        or value.get("export_allowed") is not False
    ):
        raise SemanticLayoutError("peer manifold must be the sealed local research artifact")
    if value.get("source_index_sha256") != peer_binding.byte_sha256:
        raise SemanticLayoutError("peer manifold was not built from the bound peer index bytes")
    if value.get("source_peer_similarity_output_sha256") != peer_binding.logical_sha256:
        raise SemanticLayoutError("peer manifold logical source does not match peer index")
    rows = value.get("coordinates")
    if not isinstance(rows, list):
        raise SemanticLayoutError("peer manifold has no coordinate rows")
    positions: dict[str, tuple[float, float, int]] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise SemanticLayoutError("peer manifold coordinate is not an object")
        node, x, y, component = (
            row.get("genre_id"),
            row.get("x"),
            row.get("y"),
            row.get("component"),
        )
        if (
            not isinstance(node, str)
            or node not in names
            or not isinstance(x, (int, float))
            or not isinstance(y, (int, float))
            or not isinstance(component, int)
            or not math.isfinite(float(x))
            or not math.isfinite(float(y))
            or not 0.0 <= float(x) <= 1.0
            or not 0.0 <= float(y) <= 1.0
            or node in positions
        ):
            raise SemanticLayoutError("peer manifold coordinate is invalid")
        positions[node] = (float(x), float(y), component)
    if len(positions) < _PAIR_NODE_COUNT:
        raise SemanticLayoutError("peer manifold has insufficient placed seeds")
    return positions, _file_binding("peer_manifold_artifact", path, str(value["output_sha256"]))


def _components(nodes: Iterable[str], weights: Mapping[Edge, float]) -> tuple[tuple[str, ...], ...]:
    adjacency: dict[str, set[str]] = {node: set() for node in nodes}
    for left, right in weights:
        adjacency[left].add(right)
        adjacency[right].add(left)
    remaining = set(adjacency)
    output: list[tuple[str, ...]] = []
    while remaining:
        pending = [min(remaining)]
        component: set[str] = set()
        while pending:
            node = pending.pop()
            if node in component:
                continue
            component.add(node)
            remaining.discard(node)
            pending.extend(sorted(adjacency[node] - component, reverse=True))
        output.append(tuple(sorted(component)))
    return tuple(sorted(output, key=lambda item: (-len(item), item[0])))


def _communities(
    nodes: tuple[str, ...],
    weights: Mapping[Edge, float],
    maximum_iterations: int,
    tie_seed: int,
) -> dict[str, str]:
    """Deterministic weighted label propagation, used only as map partitioning."""
    adjacency: dict[str, dict[str, float]] = {node: {} for node in nodes}
    for (left, right), weight in weights.items():
        if left in adjacency and right in adjacency:
            adjacency[left][right] = weight
            adjacency[right][left] = weight
    labels = {node: node for node in nodes}

    def tie_key(value: str) -> tuple[str, str]:
        return hashlib.sha256(f"{tie_seed}\0{value}".encode()).hexdigest(), value

    for _ in range(maximum_iterations):
        changed = False
        for node in sorted(nodes, key=tie_key):
            scores: dict[str, float] = defaultdict(float)
            for neighbor, weight in adjacency[node].items():
                scores[labels[neighbor]] += weight
            if scores:
                maximum = max(scores.values())
                selected = min(
                    (label for label, score in scores.items() if score == maximum), key=tie_key
                )
                if selected != labels[node]:
                    labels[node] = selected
                    changed = True
        if not changed:
            break
    return labels


def _attach_empty_communities(
    labels: dict[str, str], weights: Mapping[Edge, float]
) -> dict[str, str]:
    """Attach hierarchy-only leaves to an evidenced neighbor community, never a synthetic cell."""
    adjacency: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for (left, right), weight in weights.items():
        adjacency[left].append((right, weight))
        adjacency[right].append((left, weight))
    for _ in range(len(labels)):
        changed = False
        for node in sorted(labels):
            neighbors = adjacency[node]
            if any(labels[neighbor] == labels[node] for neighbor, _weight in neighbors):
                continue
            if not neighbors:
                raise SemanticLayoutError("community has no relation to an evidenced neighbor")
            labels[node] = min(
                (-weight, labels[neighbor], neighbor) for neighbor, weight in neighbors
            )[1]
            changed = True
        if not changed:
            break
    groups: dict[str, set[str]] = defaultdict(set)
    for node, label in labels.items():
        groups[label].add(node)
    if any(not _induced_weights(nodes, weights) for nodes in groups.values()):
        raise SemanticLayoutError("community attachment did not create internal evidence")
    return labels


def _separate_coincident_points(
    coordinates: Mapping[str, tuple[float, float]],
) -> dict[str, tuple[float, float]]:
    """Apply a tiny deterministic readability offset only where structural points coincide."""
    groups: dict[tuple[float, float], list[str]] = defaultdict(list)
    for node, point in coordinates.items():
        # Artifact coordinates round to 12 decimals. Split near-coincident source points first.
        groups[(round(point[0], 10), round(point[1], 10))].append(node)
    output = dict(coordinates)
    for point, nodes in groups.items():
        if len(nodes) < _PAIR_NODE_COUNT:
            continue
        radius = min(0.03, 0.004 * math.sqrt(len(nodes)))
        for index, node in enumerate(sorted(nodes)):
            angle = 2.0 * math.pi * index / len(nodes)
            output[node] = (
                point[0] + radius * math.cos(angle),
                point[1] + radius * math.sin(angle),
            )
    return output


def _split_large_communities(
    groups: Mapping[str, list[str]], weights: Mapping[Edge, float], maximum_size: int
) -> dict[str, list[str]]:
    """Recursively expose coarse-to-fine structural neighborhoods from spectral order."""
    output: dict[str, list[str]] = {}
    for label, members in sorted(groups.items()):
        if len(members) <= maximum_size:
            output[label] = members
            continue
        ordered = sorted(
            _local_coordinates(tuple(sorted(members)), _induced_weights(members, weights)).items(),
            key=lambda item: (item[1][0], item[1][1], item[0]),
        )
        blocks = [
            [node for node, _point in ordered[index : index + maximum_size]]
            for index in range(0, len(ordered), maximum_size)
        ]
        connected = [
            part
            for block in blocks
            for part in _components(tuple(block), _induced_weights(block, weights))
        ]
        connected_groups = [list(part) for part in connected if len(part) > 1]
        singletons = [part[0] for part in connected if len(part) == 1]
        if not connected_groups:
            raise SemanticLayoutError("spectral community split has no connected local groups")
        membership = {node: index for index, group in enumerate(connected_groups) for node in group}
        adjacency: dict[str, list[tuple[str, float]]] = defaultdict(list)
        for (left, right), weight in weights.items():
            adjacency[left].append((right, weight))
            adjacency[right].append((left, weight))
        for node in singletons:
            candidates = [
                (-weight, membership[neighbor], neighbor)
                for neighbor, weight in adjacency[node]
                if neighbor in membership
            ]
            if not candidates:
                raise SemanticLayoutError("isolated spectral split node has no structural group")
            group_index = min(candidates)[1]
            connected_groups[group_index].append(node)
            membership[node] = group_index
        for index, block in enumerate(connected_groups):
            if not _induced_weights(block, weights):
                raise SemanticLayoutError(
                    "spectral community split lost its bounded local evidence"
                )
            output[f"{label}:{index}"] = block
    return output


def _preserve_hierarchy_only_clusters(
    labels: dict[str, str],
    component: tuple[str, ...],
    community_signal: Mapping[Edge, float],
    hierarchy: Mapping[Edge, float],
) -> dict[str, str]:
    """Keep hierarchy-only branches as map neighborhoods instead of one peer hub."""
    peer_supported = {node for edge in community_signal for node in edge}
    hierarchy_only = tuple(sorted(set(component) - peer_supported))
    for branch in _components(hierarchy_only, _induced_weights(hierarchy_only, hierarchy)):
        if len(branch) > 1:
            branch_label = f"hierarchy:{branch[0]}"
            for node in branch:
                labels[node] = branch_label
    return labels


def _pack(
    region: _Region, ordered: tuple[str, ...], masses: Mapping[str, float]
) -> dict[str, _Region]:
    """Bisect weighted items across the longest visual side, avoiding thin strips."""
    if not ordered:
        return {}
    if len(ordered) == 1:
        return {ordered[0]: region}
    total = sum(masses[item] for item in ordered)
    if total <= 0.0:
        raise SemanticLayoutError("layout pack requires positive component mass")
    target, cumulative, split, best = total / 2.0, 0.0, 1, math.inf
    for index, item in enumerate(ordered[:-1], start=1):
        cumulative += masses[item]
        distance = abs(target - cumulative)
        if distance <= best:
            split, best = index, distance
    left, right = ordered[:split], ordered[split:]
    left_mass = sum(masses[item] for item in left)
    if region.width / 1.777777777778 >= region.height:
        boundary = region.x0 + region.width * left_mass / total
        left_region = _Region(region.x0, region.y0, boundary, region.y1)
        right_region = _Region(boundary, region.y0, region.x1, region.y1)
    else:
        boundary = region.y0 + region.height * left_mass / total
        left_region = _Region(region.x0, region.y0, region.x1, boundary)
        right_region = _Region(region.x0, boundary, region.x1, region.y1)
    return _pack(left_region, left, masses) | _pack(right_region, right, masses)


def _induced_weights(nodes: Iterable[str], weights: Mapping[Edge, float]) -> dict[Edge, float]:
    included = set(nodes)
    return {
        edge: weight
        for edge, weight in weights.items()
        if edge[0] in included and edge[1] in included
    }


def _local_coordinates(
    nodes: tuple[str, ...], weights: Mapping[Edge, float]
) -> dict[str, tuple[float, float]]:
    """Use structural spectral coordinates; no grid, random, or hash placement exists."""
    if len(nodes) == _PAIR_NODE_COUNT:
        return {nodes[0]: (0.2, 0.5), nodes[1]: (0.8, 0.5)}
    coordinates = build_weighted_spectral_coordinates(nodes, weights)
    return {item.genre_id: (float(item.x), float(item.y)) for item in coordinates}


def _place_in_region(point: tuple[float, float], region: _Region) -> tuple[float, float]:
    """Preserve a local square's visual scale inside a landscape sub-region."""
    side = min(region.width, region.height)
    x_pad = (region.width - side) / 2.0
    y_pad = (region.height - side) / 2.0
    return region.x0 + x_pad + point[0] * side, region.y0 + y_pad + point[1] * side


def _neighbor_preservation(
    coordinates: Mapping[str, tuple[float, float]],
    weights: Mapping[Edge, float],
    world_width: float,
    limit: int,
) -> float | None:
    nodes = tuple(sorted(coordinates))
    if len(nodes) < _PAIR_NODE_COUNT:
        return None
    source: dict[str, list[tuple[float, str]]] = defaultdict(list)
    for (left, right), weight in weights.items():
        if left in coordinates and right in coordinates:
            source[left].append((weight, right))
            source[right].append((weight, left))
    points = np.array(
        [(coordinates[node][0] / world_width, coordinates[node][1]) for node in nodes]
    )
    indexes = KDTree(points).query(points, k=min(limit + 1, len(nodes)))[1]
    if indexes.ndim == 1:
        indexes = indexes[:, np.newaxis]
    values: list[float] = []
    for index, node in enumerate(nodes):
        expected = tuple(
            neighbor
            for _weight, neighbor in sorted(source[node], key=lambda item: (-item[0], item[1]))[
                :limit
            ]
        )
        if not expected:
            continue
        actual = tuple(
            nodes[int(candidate)] for candidate in indexes[index] if nodes[int(candidate)] != node
        )[:limit]
        values.append(
            len(set(expected) & set(actual)) / min(len(expected), len(actual))
        ) if actual else None
    return sum(values) / len(values) if values else None


def _hierarchy_distance(
    coordinates: Mapping[str, tuple[float, float]],
    hierarchy: Mapping[Edge, float],
    world_width: float,
) -> float | None:
    values = [
        math.dist(
            (coordinates[left][0] / world_width, coordinates[left][1]),
            (coordinates[right][0] / world_width, coordinates[right][1]),
        )
        for left, right in hierarchy
        if left in coordinates and right in coordinates
    ]
    return sum(values) / len(values) if values else None


def _coordinate_collisions(coordinates: Mapping[str, tuple[float, float]]) -> int:
    return len(coordinates) - len({(round(x, 12), round(y, 12)) for x, y in coordinates.values()})


def _label_collisions(
    communities: tuple[OverviewCommunity, ...], world_width: float, budget: int
) -> int:
    selected = sorted(
        communities, key=lambda item: (-item.member_count, item.label, item.community_id)
    )[:budget]
    boxes: list[tuple[float, float, float, float]] = []
    collisions = 0
    for item in selected:
        width = min(len(item.label), 42) * 0.0105
        box = (item.x / world_width, item.y, item.x / world_width + width, item.y + 0.025)
        if any(
            box[0] < other[2] and box[2] > other[0] and box[1] < other[3] and box[3] > other[1]
            for other in boxes
        ):
            collisions += 1
        else:
            boxes.append(box)
    return collisions


def _merge_weighted_edges(
    combined: dict[Edge, float],
    kinds: dict[Edge, set[EvidenceKind]],
    source: Mapping[Edge, float],
    scale: float,
    kind: EvidenceKind,
) -> None:
    """Add one visibly named evidence channel without erasing its provenance."""
    for edge, value in source.items():
        combined[edge] = combined.get(edge, 0.0) + value * scale
        kinds[edge].add(kind)


def _place_branch_children(
    anchor: tuple[float, float],
    children: Iterable[str],
    *,
    bounds: tuple[float, float, float, float],
) -> dict[str, tuple[float, float]]:
    """Place a branch as a compact deterministic phyllotactic neighborhood.

    This is local packing, not a force simulation: a stable hash determines
    the order and rotation, while a golden-angle spiral avoids conspicuous rows
    and columns. Every child remains close enough to read as part of its parent.
    """
    ordered = tuple(
        sorted(children, key=lambda node: (hashlib.sha256(node.encode()).digest(), node))
    )
    if not ordered:
        return {}
    outer_radius = min(0.034, 0.009 + 0.0055 * math.sqrt(len(ordered)))
    center_x = min(max(anchor[0], bounds[0] + outer_radius), bounds[2] - outer_radius)
    center_y = min(max(anchor[1], bounds[1] + outer_radius), bounds[3] - outer_radius)
    rotation = int.from_bytes(hashlib.sha256("\0".join(ordered).encode()).digest()[:8], "big")
    rotation = rotation / 2**64 * 2.0 * math.pi
    golden_angle = math.pi * (3.0 - math.sqrt(5.0))
    output: dict[str, tuple[float, float]] = {}
    for index, node in enumerate(ordered):
        radius = outer_radius * math.sqrt((index + 0.5) / len(ordered))
        angle = rotation + index * golden_angle
        output[node] = (
            min(max(center_x + radius * math.cos(angle), bounds[0]), bounds[2]),
            min(max(center_y + radius * math.sin(angle), bounds[1]), bounds[3]),
        )
    return output


def _display_hierarchy(
    nodes: Iterable[str], directed: Mapping[str, Mapping[str, float]]
) -> tuple[dict[str, str | None], dict[str, str | None], dict[str, int]]:
    """Choose one factual/review parent for navigation without flattening the source DAG."""
    parents: dict[str, str | None] = {}
    for node in sorted(nodes):
        candidates = directed.get(node, {})
        parents[node] = (
            min(candidates, key=lambda parent: (-candidates[parent], parent))
            if candidates
            else None
        )
    roots: dict[str, str | None] = {}
    depths: dict[str, int] = {}

    def resolve(node: str, visiting: set[str]) -> tuple[str | None, int]:
        if node in roots:
            return roots[node], depths[node]
        parent = parents[node]
        if parent is None:
            roots[node], depths[node] = None, 0
        elif parent in visiting:
            raise SemanticLayoutError("display parent selection introduced a hierarchy cycle")
        else:
            root, depth = resolve(parent, visiting | {node})
            roots[node] = parent if root is None else root
            depths[node] = depth + 1
        return roots[node], depths[node]

    for node in sorted(parents):
        resolve(node, set())
    return parents, roots, depths


def _hierarchy_region_members(
    node_set: set[str], parents: Mapping[str, str | None]
) -> tuple[dict[str, list[str]], set[str]]:
    """Return complete display-tree families and nodes not in any such family."""
    children: dict[str, set[str]] = defaultdict(set)
    for node, parent in parents.items():
        if parent is None:
            continue
        if parent not in node_set:
            raise SemanticLayoutError("semantic region parent is outside positioned nodes")
        children[parent].add(node)

    def family_root(node: str) -> str | None:
        current = node
        seen: set[str] = set()
        while (parent := parents[current]) is not None:
            if current in seen:
                raise SemanticLayoutError("semantic region display parents contain a cycle")
            seen.add(current)
            current = parent
        return current if current in children else None

    hierarchy_members: dict[str, list[str]] = defaultdict(list)
    residual: set[str] = set()
    for node in sorted(node_set):
        root = family_root(node)
        if root is None:
            residual.add(node)
        else:
            hierarchy_members[root].append(node)
    return hierarchy_members, residual


def _component_regions(
    residual: Iterable[str], components: Mapping[str, int], degree: Mapping[str, float]
) -> list[_SemanticRegion]:
    """Keep rootless positioned nodes in their pre-existing structural components."""
    residual_by_component: dict[int, list[str]] = defaultdict(list)
    for node in sorted(residual):
        residual_by_component[components[node]].append(node)
    return [
        _SemanticRegion(
            kind="component",
            key=str(component_id),
            members=(ordered := tuple(sorted(members))),
            anchor=min(ordered, key=lambda node: (-degree[node], node)),
        )
        for component_id, members in residual_by_component.items()
    ]


def _semantic_regions(
    nodes: Iterable[str],
    parents: Mapping[str, str | None],
    components: Mapping[str, int],
    degree: Mapping[str, float],
) -> tuple[_SemanticRegion, ...]:
    """Build hierarchy families, then residual peer components, never spatial tiles.

    A display-tree root is eligible only when it actually has a child.  This
    keeps a real umbrella and every descendant together.  Nodes without a
    display-tree relation are not made into synthetic parents: they retain the
    connected peer-manifold component that supplied their position.
    """
    node_set = set(nodes)
    if node_set != set(parents) or node_set != set(components):
        raise SemanticLayoutError("semantic region inputs must cover identical nodes")
    hierarchy_members, residual = _hierarchy_region_members(node_set, parents)
    regions: list[_SemanticRegion] = [
        _SemanticRegion(
            kind="hierarchy",
            key=root,
            members=tuple(sorted(members)),
            anchor=root,
        )
        for root, members in hierarchy_members.items()
    ]
    regions.extend(_component_regions(residual, components, degree))
    if set().union(*(set(region.members) for region in regions)) != node_set:
        raise SemanticLayoutError("semantic regions must partition positioned nodes")
    if sum(len(region.members) for region in regions) != len(node_set):
        raise SemanticLayoutError("semantic regions overlap")
    return tuple(
        sorted(
            regions,
            key=lambda region: (region.kind, region.key, region.members),
        )
    )


def _overview_visibility(  # noqa: C901
    records: list[OverviewCommunity],
    groups: tuple[tuple[str, ...], ...],
    context: _OverviewSelectionContext,
) -> list[OverviewCommunity]:
    """Select sparse overview labels by evidence roots and spatial diversity.

    Every candidate is a real point in its spatial bucket. Root novelty is weighted
    first, then evidence importance and max-min distance, so one large genre family
    cannot consume the overview budget. No genre names or families are special-cased.
    """
    root_breadth: Counter[str] = Counter(context.roots[node] or node for node in context.positions)
    max_degree = max(context.degree.values(), default=1.0)
    candidates: list[tuple[float, str, int, str]] = []
    for record, group in zip(records, groups, strict=True):
        root_candidates = [node for node in group if context.depths[node] == 0] or list(group)
        for node in root_candidates:
            root = context.roots[node] or node
            root_score = math.log1p(root_breadth[root])
            importance = context.degree[node] / max_degree
            shallow = 1.0 / (1.0 + context.depths[node])
            # Favor specific, evidenced labels without turning names into rules.
            specificity = min(len(context.names[node].split()), 6) / 6.0
            base = 0.55 * root_score + 0.30 * importance + 0.10 * shallow + 0.05 * specificity
            candidates.append((base, node, record.community_id, root))
    candidates.sort(key=lambda item: (-item[0], item[1], item[2], item[3]))
    selected: list[tuple[float, str, int, str]] = []
    selected_communities: set[int] = set()
    selected_roots: set[str] = set()
    boxes: list[tuple[float, float, float, float]] = []

    def label_box(node: str) -> tuple[float, float, float, float]:
        x, y = context.positions[node]
        label_width = min(len(context.names[node]), 42) * 0.0105
        return (x / context.world_width, y, x / context.world_width + label_width, y + 0.025)

    def collides(box: tuple[float, float, float, float]) -> bool:
        return any(
            box[0] < old[2] and box[2] > old[0] and box[1] < old[3] and box[3] > old[1]
            for old in boxes
        )

    # Keep the first frame geographically legible even when structural-family
    # anchors are heavily skewed. These are still real region candidates; the
    # boundary pass only reserves deterministic edge coverage before evidence
    # and root diversity fill the remaining label budget.
    boundary_candidates: list[tuple[float, str, int, str]] = []
    for axis, direction in ((1, False), (1, True), (0, False), (0, True)):
        ordered = sorted(
            candidates,
            key=lambda item: (
                context.positions[item[1]][axis] * (-1 if direction else 1),
                item[1],
                item[2],
                item[3],
            ),
        )
        for candidate in ordered:
            if candidate[2] not in {item[2] for item in boundary_candidates}:
                boundary_candidates.append(candidate)
                break

    for candidate in boundary_candidates:
        if len(selected) >= context.budget or candidate[2] in selected_communities:
            continue
        if collides(label_box(candidate[1])):
            continue
        selected.append(candidate)
        selected_communities.add(candidate[2])
        selected_roots.add(candidate[3])
        boxes.append(label_box(candidate[1]))

    while len(selected) < context.budget:
        eligible = [
            item
            for item in candidates
            if item[2] not in selected_communities and not collides(label_box(item[1]))
        ]
        if not eligible:
            break
        best = max(
            eligible,
            key=lambda item: (
                item[3] not in selected_roots,
                item[0],
                min(
                    math.dist(
                        (
                            context.positions[item[1]][0] / context.world_width,
                            context.positions[item[1]][1],
                        ),
                        (
                            context.positions[other[1]][0] / context.world_width,
                            context.positions[other[1]][1],
                        ),
                    )
                    for other in selected
                )
                if selected
                else 1.0,
                item[1],
                -item[2],
            ),
        )
        selected.append(best)
        selected_communities.add(best[2])
        selected_roots.add(best[3])
        boxes.append(label_box(best[1]))
    chosen = {community_id: node for _score, node, community_id, _root in selected}
    return [
        record.model_copy(
            update={
                "overview_visible": record.community_id in chosen,
                "anchor_seed_id": chosen.get(record.community_id, record.anchor_seed_id),
                "label": context.names[chosen[record.community_id]]
                if record.community_id in chosen
                else record.label,
                "x": round(context.positions[chosen[record.community_id]][0], 12)
                if record.community_id in chosen
                else record.x,
                "y": round(context.positions[chosen[record.community_id]][1], 12)
                if record.community_id in chosen
                else record.y,
            }
        )
        for record in records
    ]


def _initial_camera(
    anchors: Iterable[tuple[float, float]], world_width: float, world_height: float
) -> CameraBounds:
    """Fit overview anchors into a padded camera while preserving world aspect."""
    points = tuple(anchors)
    if not points:
        return CameraBounds(x0=0.0, y0=0.0, x1=world_width, y1=world_height)
    min_x, max_x = min(point[0] for point in points), max(point[0] for point in points)
    min_y, max_y = min(point[1] for point in points), max(point[1] for point in points)
    padding_x = max((max_x - min_x) * _INITIAL_CAMERA_PADDING_FRACTION, world_width * 0.01)
    padding_y = max((max_y - min_y) * _INITIAL_CAMERA_PADDING_FRACTION, world_height * 0.01)
    width = max(max_x - min_x + 2.0 * padding_x, (max_y - min_y + 2.0 * padding_y) * world_width)
    height = width / world_width
    if width > world_width or height > world_height:
        width, height = world_width, world_height
    center_x, center_y = (min_x + max_x) / 2.0, (min_y + max_y) / 2.0
    x0 = min(max(center_x - width / 2.0, 0.0), world_width - width)
    y0 = min(max(center_y - height / 2.0, 0.0), world_height - height)
    return CameraBounds(x0=x0, y0=y0, x1=x0 + width, y1=y0 + height)


def _content_bounds(
    positions: Mapping[str, tuple[float, float]], world_width: float, world_height: float
) -> CameraBounds:
    """Return the padded content box without allowing an outlier to set the view."""
    if not positions:
        return CameraBounds(x0=0.0, y0=0.0, x1=world_width, y1=world_height)
    minimum_x = min(point[0] for point in positions.values())
    maximum_x = max(point[0] for point in positions.values())
    minimum_y = min(point[1] for point in positions.values())
    maximum_y = max(point[1] for point in positions.values())
    padding_x = max((maximum_x - minimum_x) * 0.02, world_width * 0.01)
    padding_y = max((maximum_y - minimum_y) * 0.02, world_height * 0.01)
    return CameraBounds(
        x0=max(0.0, minimum_x - padding_x),
        y0=max(0.0, minimum_y - padding_y),
        x1=min(world_width, maximum_x + padding_x),
        y1=min(world_height, maximum_y + padding_y),
    )


def _quality_gate(metrics: GeometryMetrics) -> None:
    if (
        metrics.mean_peer_knn_preservation is None
        or metrics.mean_peer_knn_preservation < _MINIMUM_PEER_KNN
    ):
        raise SemanticLayoutError("peer manifold kNN preservation gate failed")
    if (
        metrics.colisten_evaluable_seed_count < _MINIMUM_COLISTEN_SEEDS
        or metrics.mean_colisten_knn_preservation is None
        or metrics.mean_colisten_knn_preservation < _MINIMUM_COLISTEN_KNN
    ):
        raise SemanticLayoutError("co-listen structural preservation gate failed")
    if (
        metrics.mean_hierarchy_endpoint_distance is None
        or metrics.mean_hierarchy_endpoint_distance > _MAXIMUM_HIERARCHY_DISTANCE
    ):
        raise SemanticLayoutError("hierarchy-anchor coherence gate failed")
    if metrics.exact_coordinate_collision_count or metrics.overview_label_collision_count:
        raise SemanticLayoutError("coordinate or overview-label collision gate failed")
    if not _MINIMUM_WIDTH_OCCUPANCY <= metrics.occupied_world_width_fraction <= _MAXIMUM_OCCUPANCY:
        raise SemanticLayoutError("landscape width utilization gate failed")
    if (
        not _MINIMUM_HEIGHT_OCCUPANCY
        <= metrics.occupied_world_height_fraction
        <= _MAXIMUM_OCCUPANCY
    ):
        raise SemanticLayoutError("landscape height utilization gate failed")
    if (
        metrics.overview_visible_count >= _MINIMUM_OVERVIEW_ANCHORS
        and metrics.overview_root_coverage_fraction < _MINIMUM_OVERVIEW_ROOT_COVERAGE
    ):
        raise SemanticLayoutError("overview root diversity gate failed")


def build_semantic_map_layout(  # noqa: C901, PLR0912, PLR0915
    inputs: SemanticLayoutInputs, *, settings: SemanticLayoutSettings | None = None
) -> SemanticLayoutArtifact:
    """Preserve the peer-only open manifold; add other evidence as local anchors only."""
    resolved = settings or SemanticLayoutSettings()
    names, peer, peer_binding = _peer_input(inputs.peer_index)
    manifold, manifold_binding = _peer_manifold_input(
        inputs.peer_manifold_artifact, names, peer_binding
    )
    seeds = set(names)
    hierarchy, directed, hierarchy_binding = _hierarchy_input(
        inputs.hierarchy_artifact, seeds, resolved
    )
    colisten, colisten_artifact_binding, colisten_cache_binding = _colisten_input(
        inputs.colisten_artifact, inputs.colisten_cache, seeds, resolved.colisten_weight_scale
    )
    combined: dict[Edge, float] = {}
    kinds: dict[Edge, set[EvidenceKind]] = defaultdict(set)
    _merge_weighted_edges(combined, kinds, peer, resolved.peer_weight_scale, "peer")
    _merge_weighted_edges(combined, kinds, colisten, 1.0, "colisten")
    _merge_weighted_edges(combined, kinds, hierarchy, 1.0, "hierarchy")
    supported = tuple(sorted({node for edge in combined for node in edge}))
    parents, roots, depths = _display_hierarchy(supported, directed)
    degree: dict[str, float] = defaultdict(float)
    evidence: dict[str, set[EvidenceKind]] = defaultdict(set)
    neighbors: dict[str, list[tuple[str, float, EvidenceKind]]] = defaultdict(list)
    for (left, right), weight in combined.items():
        degree[left] += weight
        degree[right] += weight
        evidence[left].update(kinds[(left, right)])
        evidence[right].update(kinds[(left, right)])
        preferred: EvidenceKind = (
            "hierarchy"
            if "hierarchy" in kinds[(left, right)]
            else "colisten"
            if "colisten" in kinds[(left, right)]
            else "peer"
        )
        neighbors[left].append((right, weight, preferred))
        neighbors[right].append((left, weight, preferred))
    # Fit the peer manifold into a centered landscape atlas before attaching
    # hierarchy-only points.  This keeps the initial view broad and makes each
    # peer component a bounded visual neighborhood without force simulation.
    atlas_margin = max(resolved.margin, _ATLAS_MARGIN)
    atlas = build_rectangular_atlas(
        tuple(
            AtlasPoint(node_id=node, x=x, y=y, group_id=f"component:{component_id}")
            for node, (x, y, component_id) in sorted(manifold.items())
        ),
        settings=AtlasSettings(
            world_width=resolved.world_width,
            world_height=resolved.world_height,
            margin=atlas_margin,
        ),
    )
    positions = dict(atlas.positions)
    placement: dict[
        str, Literal["peer_manifold", "hierarchy_anchor", "colisten_anchor", "structural_component"]
    ] = dict.fromkeys(positions, "peer_manifold")
    component = {node: item[2] for node, item in manifold.items()}
    waiting = set(supported) - set(positions)
    for _ in range(len(waiting) + 1):
        attach: dict[str, tuple[str, Literal["hierarchy_anchor", "colisten_anchor"]]] = {}
        for node in sorted(waiting):
            parent = parents[node]
            if parent is not None and parent in positions:
                attach[node] = (parent, "hierarchy_anchor")
                continue
            candidates = [item for item in neighbors[node] if item[0] in positions]
            if candidates:
                anchor, _weight, kind = min(
                    candidates, key=lambda item: (item[2] != "colisten", -item[1], item[0])
                )
                attach[node] = (
                    anchor,
                    "colisten_anchor" if kind == "colisten" else "hierarchy_anchor",
                )
        if not attach:
            break
        children: dict[str, list[str]] = defaultdict(list)
        for node, (anchor, _kind) in attach.items():
            children[anchor].append(node)
        for anchor, child_nodes in children.items():
            branch_positions = _place_branch_children(
                positions[anchor],
                child_nodes,
                bounds=(
                    atlas_margin,
                    atlas_margin,
                    resolved.world_width - atlas_margin,
                    resolved.world_height - atlas_margin,
                ),
            )
            for node, position in branch_positions.items():
                positions[node] = position
                component[node], placement[node] = component[anchor], attach[node][1]
        waiting -= set(attach)
    # Unsupported seeds stay unplaced; independent components are bounded evidence islands.
    for index, members in enumerate(
        _components(tuple(sorted(waiting)), _induced_weights(waiting, combined)), start=1
    ):
        local = _separate_coincident_points(
            _local_coordinates(members, _induced_weights(members, combined))
        )
        region = _Region(0.13 + 0.14 * (index - 1), 0.74, 0.23 + 0.14 * (index - 1), 0.84)
        for node, point in local.items():
            positions[node] = _place_in_region(point, region)
            component[node], placement[node] = (
                max(component.values(), default=-1) + index,
                "structural_component",
            )
    positions = _separate_coincident_points(positions)
    regions = _semantic_regions(positions, parents, component, degree)
    community = {node: index for index, region in enumerate(regions) for node in region.members}
    records = []
    for index, region in enumerate(regions):
        anchor = region.anchor
        records.append(
            OverviewCommunity(
                community_id=index,
                label=names[anchor],
                anchor_seed_id=anchor,
                member_count=len(region.members),
                component_id=min(component[node] for node in region.members),
                x=round(positions[anchor][0], 12),
                y=round(positions[anchor][1], 12),
                overview_visible=False,
            )
        )
    records = _overview_visibility(
        records,
        tuple(region.members for region in regions),
        _OverviewSelectionContext(
            names=names,
            positions=positions,
            roots=roots,
            depths=depths,
            degree=degree,
            world_width=resolved.world_width,
            budget=resolved.overview_label_budget,
        ),
    )
    overview_anchors = {record.anchor_seed_id for record in records if record.overview_visible}
    max_degree = max(degree.values(), default=1.0)
    priority = {
        node: index
        for index, node in enumerate(
            sorted(positions, key=lambda node: (-degree[node], names[node].casefold(), node))
        )
    }
    region_anchors = {record.anchor_seed_id for record in records}
    lod_by_node: dict[str, Literal[0, 1, 2, 3]] = {}
    for node in sorted(positions, key=lambda item: (depths[item], priority[item], item)):
        if node in overview_anchors:
            lod: Literal[0, 1, 2, 3] = 0
        elif parents[node] is not None:
            lod = min(3, max(1, depths[node] + 1))
        elif node in region_anchors or degree[node] / max_degree >= _LOD_TWO_IMPORTANCE_FRACTION:
            lod = 1
        else:
            lod = 3
        parent = parents[node]
        if parent is not None:
            lod = cast("Literal[0, 1, 2, 3]", max(lod, lod_by_node[parent]))
        lod_by_node[node] = cast("Literal[0, 1, 2, 3]", lod)
    records = [
        record.model_copy(
            update={
                "overview_visible": record.overview_visible
                and lod_by_node[record.anchor_seed_id] == 0
            }
        )
        for record in records
    ]
    coordinates = tuple(
        SemanticCoordinate(
            seed_id=node,
            name=names[node],
            x=round(positions[node][0], 12),
            y=round(positions[node][1], 12),
            component_id=component[node],
            community_id=community[node],
            lod=lod_by_node[node],
            importance=round(degree[node], 12),
            label_priority=priority[node],
            evidence_kinds=tuple(sorted(evidence[node])),
            display_parent_id=parents[node],
            hierarchy_root_id=roots[node],
            hierarchy_depth=depths[node],
            placement_kind=placement[node],
        )
        for node in sorted(positions)
    )
    unplaced = tuple(
        UnplacedSeed(seed_id=node, name=names[node]) for node in sorted(seeds - set(positions))
    )
    structural_edges = tuple(
        StructuralEdge(
            left_seed_id=left,
            right_seed_id=right,
            weight=round(weight, 12),
            evidence_kinds=tuple(sorted(kinds[(left, right)])),
        )
        for (left, right), weight in sorted(combined.items())
    )
    overview_communities = tuple(record for record in records if record.overview_visible)
    overview_anchors = tuple(
        (
            round(positions[record.anchor_seed_id][0], 12),
            round(positions[record.anchor_seed_id][1], 12),
        )
        for record in overview_communities
    )
    # Fit the overview anchors. Deeper nodes remain available through zoom, but
    # must not inflate the first viewport and make the headings look vertically
    # compressed.
    initial_camera = _initial_camera(overview_anchors, resolved.world_width, resolved.world_height)
    overview_root_ids = {
        roots[record.anchor_seed_id] or record.anchor_seed_id for record in overview_communities
    }
    anchor_width = max((point[0] for point in overview_anchors), default=0.0) - min(
        (point[0] for point in overview_anchors), default=0.0
    )
    anchor_height = max((point[1] for point in overview_anchors), default=0.0) - min(
        (point[1] for point in overview_anchors), default=0.0
    )
    peer_positions = {node: positions[node] for node in manifold}
    colisten_nodes = {node for edge in colisten for node in edge} & set(positions)
    metrics = GeometryMetrics(
        placed_seed_count=len(coordinates),
        unplaced_seed_count=len(unplaced),
        component_count=len(set(component.values())),
        community_count=len(records),
        source_peer_edge_count=len(peer),
        source_colisten_edge_count=len(colisten),
        source_hierarchy_edge_count=len(hierarchy),
        mean_peer_knn_preservation=_neighbor_preservation(
            peer_positions, peer, resolved.world_width, resolved.peers_per_genre
        ),
        peer_manifold_seed_count=len(peer_positions),
        mean_colisten_knn_preservation=_neighbor_preservation(
            {node: positions[node] for node in colisten_nodes},
            colisten,
            resolved.world_width,
            resolved.peers_per_genre,
        ),
        colisten_evaluable_seed_count=len(colisten_nodes),
        mean_hierarchy_endpoint_distance=_hierarchy_distance(
            positions, hierarchy, resolved.world_width
        ),
        occupied_world_width_fraction=(
            max(x for x, _y in positions.values()) - min(x for x, _y in positions.values())
        )
        / resolved.world_width,
        occupied_world_height_fraction=max(y for _x, y in positions.values())
        - min(y for _x, y in positions.values()),
        exact_coordinate_collision_count=_coordinate_collisions(positions),
        overview_label_collision_count=_label_collisions(
            tuple(record for record in records if record.overview_visible),
            resolved.world_width,
            resolved.overview_label_budget,
        ),
        largest_community_member_count=max(record.member_count for record in records),
        overview_visible_count=len(overview_communities),
        overview_root_count=len(overview_root_ids),
        overview_root_coverage_fraction=(
            len(overview_root_ids) / len(overview_communities) if overview_communities else 0.0
        ),
        initial_camera_anchor_width_fraction=anchor_width / (initial_camera.x1 - initial_camera.x0),
        initial_camera_anchor_height_fraction=anchor_height
        / (initial_camera.y1 - initial_camera.y0),
    )
    if len(manifold) >= _QUALITY_GATE_MINIMUM_SEEDS:
        _quality_gate(metrics)
    preliminary = SemanticLayoutArtifact(
        inputs=(
            peer_binding,
            manifold_binding,
            hierarchy_binding,
            colisten_artifact_binding,
            colisten_cache_binding,
        ),
        settings=resolved,
        settings_sha256=semantic_layout_settings_sha256(resolved),
        coordinates=coordinates,
        unplaced=unplaced,
        communities=tuple(records),
        structural_edges=structural_edges,
        world_bounds=CameraBounds(
            x0=0.0, y0=0.0, x1=resolved.world_width, y1=resolved.world_height
        ),
        content_bounds=_content_bounds(positions, resolved.world_width, resolved.world_height),
        initial_camera=initial_camera,
        metrics=metrics,
        output_sha256="0" * 64,
    )
    artifact = preliminary.model_copy(update={"output_sha256": semantic_layout_sha256(preliminary)})
    verify_semantic_map_layout(artifact)
    return artifact


def _rejected_packed_layout(  # noqa: PLR0915
    inputs: SemanticLayoutInputs, *, settings: SemanticLayoutSettings | None = None
) -> SemanticLayoutArtifact:
    """Build a stable 16:9 structural map from receipt-bound open-evidence adapters."""
    resolved = settings or SemanticLayoutSettings()
    names, peer, peer_binding = _peer_input(inputs.peer_index)
    seed_ids = set(names)
    hierarchy, directed_hierarchy, hierarchy_binding = _hierarchy_input(
        inputs.hierarchy_artifact, seed_ids, resolved
    )
    colisten, colisten_artifact_binding, colisten_cache_binding = _colisten_input(
        inputs.colisten_artifact, inputs.colisten_cache, seed_ids, resolved.colisten_weight_scale
    )
    combined: dict[Edge, float] = {}
    kinds: dict[Edge, set[EvidenceKind]] = defaultdict(set)
    _merge_weighted_edges(combined, kinds, peer, resolved.peer_weight_scale, "peer")
    _merge_weighted_edges(
        combined,
        kinds,
        colisten,
        1.0,
        "colisten",
    )
    _merge_weighted_edges(combined, kinds, hierarchy, 1.0, "hierarchy")
    community_signal: dict[Edge, float] = dict(peer)
    for edge, weight in colisten.items():
        community_signal[edge] = community_signal.get(edge, 0.0) + weight
    supported = tuple(sorted({node for edge in combined for node in edge}))
    components = _components(supported, combined)
    world = _Region(
        resolved.margin * resolved.world_width,
        resolved.margin,
        resolved.world_width * (1.0 - resolved.margin),
        1.0 - resolved.margin,
    )
    component_keys = tuple(f"component:{index}" for index in range(len(components)))
    component_mass = {
        key: float(len(components[index])) for index, key in enumerate(component_keys)
    }
    component_regions = _pack(world, component_keys, component_mass)
    raw_positions: dict[str, tuple[float, float]] = {}
    community_records: list[OverviewCommunity] = []
    community_ids: dict[str, int] = {}
    component_ids: dict[str, int] = {}
    degree: dict[str, float] = defaultdict(float)
    evidence: dict[str, set[EvidenceKind]] = defaultdict(set)
    for edge, weight in combined.items():
        degree[edge[0]] += weight
        degree[edge[1]] += weight
        evidence[edge[0]].update(kinds[edge])
        evidence[edge[1]].update(kinds[edge])
    next_community_id = 0
    for component_id, component in enumerate(components):
        local_weights = _induced_weights(component, combined)
        labels = _communities(
            component,
            _induced_weights(component, community_signal),
            resolved.maximum_community_iterations,
            resolved.community_tie_seed,
        )
        labels = _preserve_hierarchy_only_clusters(
            labels,
            component,
            _induced_weights(component, community_signal),
            _induced_weights(component, hierarchy),
        )
        labels = _attach_empty_communities(labels, local_weights)
        groups: dict[str, list[str]] = defaultdict(list)
        for node in component:
            groups[labels[node]].append(node)
        groups = _split_large_communities(groups, local_weights, resolved.maximum_community_size)
        ordered_groups = tuple(
            sorted(groups, key=lambda label: (-len(groups[label]), min(groups[label])))
        )
        key_for_label = {
            label: f"community:{component_id}:{index}" for index, label in enumerate(ordered_groups)
        }
        group_mass = {key_for_label[label]: float(len(groups[label])) for label in ordered_groups}
        group_regions = _pack(
            component_regions[component_keys[component_id]], tuple(group_mass), group_mass
        )
        for label in ordered_groups:
            members = tuple(sorted(groups[label]))
            group_weights = _induced_weights(members, local_weights)
            if not group_weights:
                # Label propagation cannot create a disconnected group.
                raise SemanticLayoutError("community has no internal evidence edges")
            local = _separate_coincident_points(_local_coordinates(members, group_weights))
            region = group_regions[key_for_label[label]]
            community_id = next_community_id
            next_community_id += 1
            for node in members:
                raw_positions[node] = _place_in_region(local[node], region)
                community_ids[node] = community_id
                component_ids[node] = component_id
            parents = {right for left, right in hierarchy if left in members and right in members}
            label_node = min(
                members,
                key=lambda node: (
                    node not in parents,
                    -degree[node],
                    len(names[node]),
                    names[node].casefold(),
                    node,
                ),
            )
            center_x = sum(raw_positions[node][0] for node in members) / len(members)
            center_y = sum(raw_positions[node][1] for node in members) / len(members)
            community_records.append(
                OverviewCommunity(
                    community_id=community_id,
                    label=names[label_node],
                    member_count=len(members),
                    component_id=component_id,
                    x=round(center_x, 12),
                    y=round(center_y, 12),
                )
            )
    max_degree = max(degree.values(), default=1.0)
    display_parents, hierarchy_roots, hierarchy_depths = _display_hierarchy(
        raw_positions, directed_hierarchy
    )
    ordered_nodes = sorted(
        raw_positions, key=lambda node: (-degree[node], names[node].casefold(), node)
    )
    label_priority = {node: rank for rank, node in enumerate(ordered_nodes)}
    coordinates = tuple(
        SemanticCoordinate(
            seed_id=node,
            name=names[node],
            x=round(raw_positions[node][0], 12),
            y=round(raw_positions[node][1], 12),
            component_id=component_ids[node],
            community_id=community_ids[node],
            lod=1
            if label_priority[node] < len(community_records)
            else 2
            if degree[node] / max_degree >= _LOD_TWO_IMPORTANCE_FRACTION
            else 3,
            importance=round(degree[node], 12),
            label_priority=label_priority[node],
            evidence_kinds=tuple(sorted(evidence[node])),
            display_parent_id=display_parents[node],
            hierarchy_root_id=hierarchy_roots[node],
            hierarchy_depth=hierarchy_depths[node],
        )
        for node in sorted(raw_positions)
    )
    unplaced = tuple(
        UnplacedSeed(seed_id=node, name=names[node])
        for node in sorted(seed_ids - set(raw_positions))
    )
    positions = {item.seed_id: (float(item.x), float(item.y)) for item in coordinates}
    structural_edges = tuple(
        StructuralEdge(
            left_seed_id=left,
            right_seed_id=right,
            weight=round(weight, 12),
            evidence_kinds=tuple(sorted(kinds[(left, right)])),
        )
        for (left, right), weight in sorted(combined.items())
    )
    x_values = [point[0] for point in positions.values()]
    y_values = [point[1] for point in positions.values()]
    width = resolved.world_width
    height = resolved.world_height
    metrics = GeometryMetrics(
        placed_seed_count=len(coordinates),
        unplaced_seed_count=len(unplaced),
        component_count=len(components),
        community_count=len(community_records),
        source_peer_edge_count=len(peer),
        source_colisten_edge_count=len(colisten),
        source_hierarchy_edge_count=len(hierarchy),
        mean_peer_knn_preservation=_neighbor_preservation(
            positions, peer, resolved.world_width, resolved.peers_per_genre
        ),
        mean_colisten_knn_preservation=_neighbor_preservation(
            positions, colisten, resolved.world_width, resolved.peers_per_genre
        ),
        mean_hierarchy_endpoint_distance=_hierarchy_distance(
            positions, hierarchy, resolved.world_width
        ),
        occupied_world_width_fraction=(max(x_values) - min(x_values)) / width if x_values else 0.0,
        occupied_world_height_fraction=(max(y_values) - min(y_values)) / height
        if y_values
        else 0.0,
        exact_coordinate_collision_count=_coordinate_collisions(positions),
        overview_label_collision_count=_label_collisions(
            tuple(community_records), resolved.world_width, resolved.overview_label_budget
        ),
        largest_community_member_count=max(
            (item.member_count for item in community_records), default=0
        ),
    )
    preliminary = SemanticLayoutArtifact(
        inputs=(peer_binding, hierarchy_binding, colisten_artifact_binding, colisten_cache_binding),
        settings=resolved,
        settings_sha256=semantic_layout_settings_sha256(resolved),
        coordinates=coordinates,
        unplaced=unplaced,
        communities=tuple(sorted(community_records, key=lambda item: item.community_id)),
        structural_edges=structural_edges,
        world_bounds=CameraBounds(
            x0=0.0, y0=0.0, x1=resolved.world_width, y1=resolved.world_height
        ),
        content_bounds=CameraBounds(
            x0=0.0, y0=0.0, x1=resolved.world_width, y1=resolved.world_height
        ),
        initial_camera=CameraBounds(
            x0=0.0, y0=0.0, x1=resolved.world_width, y1=resolved.world_height
        ),
        metrics=metrics,
        output_sha256="0" * 64,
    )
    artifact = preliminary.model_copy(update={"output_sha256": semantic_layout_sha256(preliminary)})
    verify_semantic_map_layout(artifact)
    return artifact


def write_semantic_map_layout(output: Path, artifact: SemanticLayoutArtifact) -> None:
    """Write one canonical JSON artifact after replaying its logical digest."""
    verify_semantic_map_layout(artifact)
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(
        artifact.model_dump(mode="json"), ensure_ascii=False, separators=(",", ":"), sort_keys=True
    )
    temporary = output.with_suffix(f"{output.suffix}.tmp")
    temporary.write_text(payload, encoding="utf-8")
    temporary.replace(output)
