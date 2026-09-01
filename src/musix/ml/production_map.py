"""Build the one explainable, hierarchy-first production genre map.

This module deliberately does not reuse the experimental lens implementations.
The production geometry is a deterministic nested rectangle packing of the
display-parent forest. Similarity is used for parent tie breaks, communities,
and neighbor evaluation; it never invents a taxonomy edge or an audio feature.
"""

import hashlib
import json
import math
import resource
import time
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from pydantic import BaseModel

from musix.models.modeling import GenreNeighbor, PublicModelArtifact, PublicModelInput
from musix.models.production import (
    ParentCandidateExplanation,
    ProductionBranchAudit,
    ProductionCommunity,
    ProductionExplanation,
    ProductionGenreProfile,
    ProductionGeometryMetrics,
    ProductionLOD,
    ProductionMapArtifact,
    ProductionMapSettings,
    ProductionNeighbor,
    ProductionNode,
    ProductionRegion,
    ProductionScreenLabel,
    ProductionSimilarityEdge,
    ProductionTaxonomyEdge,
)
from musix.types import Sha256

type EdgeKey = tuple[str, str]

_MINIMUM_ORDERABLE_ITEMS = 2
_LOCAL_LAYOUT_ITERATIONS = 80
_LOCAL_LAYOUT_STEP = 0.035
_LOCAL_LAYOUT_REPULSION = 0.00018
_QA_GRID_COLUMNS = 16
_QA_GRID_ROWS = 9


class ProductionMapGeometryError(ValueError):
    """Raise when a production map cannot meet its declared geometry gates."""


@dataclass(frozen=True, slots=True)
class _TreeNode:
    genre_id: str
    parent_id: str | None
    root_id: str
    depth: int
    subtree_size: int


def _canonical_sha256(value: object) -> Sha256:
    """Hash canonical JSON so independent reruns have the same identity."""
    if isinstance(value, BaseModel):
        value = json.loads(value.model_dump_json())
    encoded = json.dumps(
        value, ensure_ascii=False, allow_nan=False, separators=(",", ":"), sort_keys=True
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _peak_rss_bytes() -> int:
    """Return the portable Linux resource high-water mark in bytes."""
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1_024


def _edge_key(left: str, right: str) -> EdgeKey:
    return (left, right) if left < right else (right, left)


def _similarity_lookup(
    neighbors: Iterable[GenreNeighbor], maximum_rank: int
) -> dict[EdgeKey, tuple[float, int]]:
    """Canonicalize ranked, public one-hop Jaccard neighbors into undirected edges."""
    result: dict[EdgeKey, tuple[float, int]] = {}
    for item in neighbors:
        if (
            item.profile_kind != "one_hop"
            or item.metric != "weighted_jaccard"
            or item.rank > maximum_rank
        ):
            continue
        key = _edge_key(item.genre_id, item.neighbor_genre_id)
        previous = result.get(key)
        candidate = (float(item.score), item.shared_artist_count)
        if previous is None or candidate > previous:
            result[key] = candidate
    return result


def _direct_counts(
    inputs: PublicModelInput,
) -> tuple[dict[str, int], dict[str, tuple[str, ...]]]:
    artists: dict[str, set[str]] = defaultdict(set)
    refs: dict[str, set[str]] = defaultdict(set)
    for item in inputs.direct_memberships:
        artists[item.genre_id].add(item.artist_id)
        refs[item.genre_id].add(item.evidence_ref)
    return (
        {genre_id: len(values) for genre_id, values in artists.items()},
        {genre_id: tuple(sorted(values)) for genre_id, values in refs.items()},
    )


def _profile_summary(
    artifact: PublicModelArtifact,
    genre_ids: Iterable[str],
) -> dict[str, tuple[int, float, int, float, tuple[str, ...]]]:
    """Return direct and propagated coverage without exposing listener identities."""
    direct: dict[str, list[float]] = defaultdict(list)
    propagated: dict[str, list[float]] = defaultdict(list)
    refs: dict[str, set[str]] = defaultdict(set)
    for profile in artifact.profiles:
        target = direct if profile.profile_kind == "direct" else propagated
        for membership in profile.memberships:
            target[profile.genre_id].append(float(membership.score))
            refs[profile.genre_id].update(membership.evidence_refs)
    return {
        genre_id: (
            len(direct[genre_id]),
            max(direct[genre_id], default=0.0),
            len(set(direct[genre_id]) | set(propagated[genre_id])),
            max((*direct[genre_id], *propagated[genre_id]), default=0.0),
            tuple(sorted(refs[genre_id])),
        )
        for genre_id in genre_ids
    }


def _would_cycle(child: str, parent: str, selected: Mapping[str, str]) -> bool:
    """Check a proposed child-to-parent link against the partial display forest."""
    cursor = parent
    seen: set[str] = set()
    while True:
        if cursor == child:
            return True
        if cursor in seen or cursor not in selected:
            return False
        seen.add(cursor)
        cursor = selected[cursor]


def _display_parents(
    inputs: PublicModelInput,
    similarity: Mapping[EdgeKey, tuple[float, int]],
    direct_counts: Mapping[str, int],
) -> tuple[dict[str, str], dict[str, tuple[ParentCandidateExplanation, ...]]]:
    """Choose exactly one parent per node with a documented, cycle-safe tie rule."""
    candidates: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for edge in inputs.hierarchy:
        candidates[edge.child_genre_id].append((edge.parent_genre_id, edge.evidence_ref))
    selected: dict[str, str] = {}
    explanations: dict[str, tuple[ParentCandidateExplanation, ...]] = {}
    for child, options in sorted(candidates.items()):
        sorted_options = sorted(
            options,
            key=lambda option: (
                -similarity.get(_edge_key(child, option[0]), (0.0, 0))[0],
                -similarity.get(_edge_key(child, option[0]), (0.0, 0))[1],
                -direct_counts.get(option[0], 0),
                option[0],
            ),
        )
        explanations[child] = tuple(
            ParentCandidateExplanation(
                parent_genre_id=parent,
                similarity_weight=round(similarity.get(_edge_key(child, parent), (0.0, 0))[0], 12),
                shared_artist_count=similarity.get(_edge_key(child, parent), (0.0, 0))[1],
                parent_direct_artist_count=direct_counts.get(parent, 0),
                taxonomy_evidence_refs=(evidence_ref,),
            )
            for parent, evidence_ref in sorted_options
        )
        for parent, _evidence_ref in sorted_options:
            if not _would_cycle(child, parent, selected):
                selected[child] = parent
                break
    return selected, explanations


def _tree(
    genre_ids: Iterable[str], selected: Mapping[str, str]
) -> tuple[dict[str, _TreeNode], dict[str, tuple[str, ...]]]:
    """Materialize root, depth, and subtree sizes from the selected parent forest."""
    children: dict[str, list[str]] = defaultdict(list)
    for child, parent in selected.items():
        children[parent].append(child)
    frozen_children = {key: tuple(sorted(value)) for key, value in children.items()}
    result: dict[str, _TreeNode] = {}

    def visit(genre_id: str, root_id: str, depth: int) -> int:
        subtotal = 1
        for child_id in frozen_children.get(genre_id, ()):
            subtotal += visit(child_id, root_id, depth + 1)
        result[genre_id] = _TreeNode(
            genre_id=genre_id,
            parent_id=selected.get(genre_id),
            root_id=root_id,
            depth=depth,
            subtree_size=subtotal,
        )
        return subtotal

    roots = sorted(genre_id for genre_id in genre_ids if genre_id not in selected)
    for root_id in roots:
        visit(root_id, root_id, 0)
    return result, frozen_children


def _community_tie_key(seed: int, genre_id: str) -> tuple[str, str]:
    return hashlib.sha256(f"{seed}\0{genre_id}".encode()).hexdigest(), genre_id


def _communities(
    genre_ids: Iterable[str],
    similarity: Mapping[EdgeKey, tuple[float, int]],
    settings: ProductionMapSettings,
) -> dict[str, str]:
    """Use deterministic weighted label propagation on privacy-safe similarity only."""
    graph: dict[str, dict[str, float]] = {genre_id: {} for genre_id in genre_ids}
    for (left, right), (weight, _shared) in similarity.items():
        graph[left][right] = weight
        graph[right][left] = weight
    labels = {genre_id: genre_id for genre_id in graph}
    order = sorted(
        graph, key=lambda genre_id: _community_tie_key(settings.community_seed, genre_id)
    )
    for _iteration in range(settings.maximum_community_iterations):
        changed = False
        for genre_id in order:
            scores: dict[str, float] = defaultdict(float)
            for neighbor, weight in graph[genre_id].items():
                scores[labels[neighbor]] += weight
            if not scores:
                continue
            maximum = max(scores.values())
            candidate = min(
                (label for label, value in scores.items() if value == maximum),
                key=lambda label: _community_tie_key(settings.community_seed, label),
            )
            if candidate != labels[genre_id]:
                labels[genre_id] = candidate
                changed = True
        if not changed:
            break
    return {genre_id: f"community:{labels[genre_id]}" for genre_id in sorted(labels)}


def _partition(
    region: ProductionRegion, items: tuple[str, ...], weights: Mapping[str, int], depth: int
) -> dict[str, ProductionRegion]:
    """Pack an ordered set in a rectangle; each recursive split preserves containment."""
    if not items:
        return {}
    total = sum(weights[item] for item in items)
    cursor = region.x0 if depth % 2 == 0 else region.y0
    span = (region.x1 - region.x0) if depth % 2 == 0 else (region.y1 - region.y0)
    result: dict[str, ProductionRegion] = {}
    for position, item in enumerate(items):
        fraction = weights[item] / total
        end = region.x1 if depth % 2 == 0 else region.y1
        if position < len(items) - 1:
            end = cursor + span * fraction
        if depth % 2 == 0:
            result[item] = ProductionRegion(x0=cursor, y0=region.y0, x1=end, y1=region.y1)
        else:
            result[item] = ProductionRegion(x0=region.x0, y0=cursor, x1=region.x1, y1=end)
        cursor = end
    return result


def _regions(
    tree: Mapping[str, _TreeNode],
    children: Mapping[str, tuple[str, ...]],
    communities: Mapping[str, str],
    similarity: Mapping[EdgeKey, tuple[float, int]],
) -> dict[str, ProductionRegion]:
    """Pack roots by community order, then recursively pack their real descendants."""
    roots = tuple(
        sorted(
            (item for item in tree.values() if item.parent_id is None),
            key=lambda item: (communities[item.genre_id], -item.subtree_size, item.genre_id),
        )
    )
    root_ids = _similarity_order(
        tuple(item.genre_id for item in roots), tree, similarity, communities
    )
    weights = {item.genre_id: item.subtree_size for item in tree.values()}
    regions = _partition(ProductionRegion(x0=0.02, y0=0.02, x1=0.98, y1=0.98), root_ids, weights, 0)

    def descend(parent_id: str) -> None:
        child_ids = _similarity_order(children.get(parent_id, ()), tree, similarity, communities)
        if not child_ids:
            return
        outer = regions[parent_id]
        inset_x = min((outer.x1 - outer.x0) * 0.035, 0.012)
        inset_y = min((outer.y1 - outer.y0) * 0.035, 0.012)
        inner = ProductionRegion(
            x0=outer.x0 + inset_x,
            y0=outer.y0 + inset_y,
            x1=outer.x1 - inset_x,
            y1=outer.y1 - inset_y,
        )
        regions.update(_partition(inner, child_ids, weights, tree[parent_id].depth + 1))
        for child_id in child_ids:
            descend(child_id)

    for root_id in root_ids:
        descend(root_id)
    return regions


def _similarity_order(
    items: tuple[str, ...],
    tree: Mapping[str, _TreeNode],
    similarity: Mapping[EdgeKey, tuple[float, int]],
    communities: Mapping[str, str],
) -> tuple[str, ...]:
    """Seriate one packed sibling set by public similarity, never by a latent axis."""
    if len(items) < _MINIMUM_ORDERABLE_ITEMS:
        return items
    remaining = set(items)
    first = min(
        remaining,
        key=lambda genre_id: (
            communities[genre_id],
            -tree[genre_id].subtree_size,
            genre_id,
        ),
    )
    ordered = [first]
    remaining.remove(first)
    while remaining:
        next_item = min(
            remaining,
            key=lambda genre_id: (
                -sum(
                    similarity.get(_edge_key(genre_id, placed), (0.0, 0))[0] for placed in ordered
                ),
                communities[genre_id],
                -tree[genre_id].subtree_size,
                genre_id,
            ),
        )
        ordered.append(next_item)
        remaining.remove(next_item)
    return tuple(ordered)


def _position_seed(genre_id: str, axis: str) -> float:
    """Return one stable pseudo-random fraction without a process RNG."""
    digest = hashlib.sha256(f"production-map-v1\0{axis}\0{genre_id}".encode()).digest()
    return int.from_bytes(digest[:8], "big") / ((1 << 64) - 1)


def _force_positions(  # noqa: C901
    tree: Mapping[str, _TreeNode],
    regions: Mapping[str, ProductionRegion],
    similarity: Mapping[EdgeKey, tuple[float, int]],
) -> dict[str, tuple[float, float]]:
    """Relax each umbrella locally on public similarity while preserving containment.

    Every descendant may move inside its stable root umbrella's position region.
    Compound rectangles remain hierarchy evidence, while point geometry gets the
    local similarity freedom needed for neighboring related genres.
    """
    groups: dict[str, list[str]] = defaultdict(list)
    for genre_id, node in tree.items():
        groups[node.root_id].append(genre_id)
    positions: dict[str, tuple[float, float]] = {}
    for root_id, members in sorted(groups.items()):
        bounds = regions[root_id]
        width = bounds.x1 - bounds.x0
        height = bounds.y1 - bounds.y0
        margin_x = min(width * 0.04, 0.015)
        margin_y = min(height * 0.04, 0.015)
        ordered = tuple(sorted(members))
        movable = tuple(item for item in ordered if item != root_id)
        local: dict[str, tuple[float, float]] = {
            root_id: ((bounds.x0 + bounds.x1) / 2, (bounds.y0 + bounds.y1) / 2)
        }
        for genre_id in movable:
            local[genre_id] = (
                bounds.x0 + margin_x + (width - 2 * margin_x) * _position_seed(genre_id, "x"),
                bounds.y0 + margin_y + (height - 2 * margin_y) * _position_seed(genre_id, "y"),
            )
        local_edges = tuple(
            (left, right, weight)
            for (left, right), (weight, _shared) in similarity.items()
            if tree[left].root_id == root_id and tree[right].root_id == root_id
        )
        for _iteration in range(_LOCAL_LAYOUT_ITERATIONS):
            forces = {genre_id: [0.0, 0.0] for genre_id in movable}
            for left, right, weight in local_edges:
                left_x, left_y = local[left]
                right_x, right_y = local[right]
                delta_x = right_x - left_x
                delta_y = right_y - left_y
                distance = math.hypot(delta_x, delta_y) + 1e-9
                attraction = weight * distance
                if left in forces:
                    forces[left][0] += delta_x / distance * attraction
                    forces[left][1] += delta_y / distance * attraction
                if right in forces:
                    forces[right][0] -= delta_x / distance * attraction
                    forces[right][1] -= delta_y / distance * attraction
            for offset, left in enumerate(ordered):
                left_x, left_y = local[left]
                for right in ordered[offset + 1 :]:
                    right_x, right_y = local[right]
                    delta_x = left_x - right_x
                    delta_y = left_y - right_y
                    distance_squared = delta_x * delta_x + delta_y * delta_y + 1e-6
                    scale = _LOCAL_LAYOUT_REPULSION / distance_squared
                    if left in forces:
                        forces[left][0] += delta_x * scale
                        forces[left][1] += delta_y * scale
                    if right in forces:
                        forces[right][0] -= delta_x * scale
                        forces[right][1] -= delta_y * scale
            for genre_id in movable:
                x, y = local[genre_id]
                force_x, force_y = forces[genre_id]
                local[genre_id] = (
                    min(
                        bounds.x1 - margin_x,
                        max(bounds.x0 + margin_x, x + force_x * _LOCAL_LAYOUT_STEP),
                    ),
                    min(
                        bounds.y1 - margin_y,
                        max(bounds.y0 + margin_y, y + force_y * _LOCAL_LAYOUT_STEP),
                    ),
                )
        positions.update(local)
    return positions


def _structural_lod(tree_node: _TreeNode, settings: ProductionMapSettings) -> tuple[int, str]:
    if tree_node.depth == 0 or tree_node.subtree_size >= settings.overview_subtree_minimum:
        return 0, "umbrella_or_large_subtree"
    if tree_node.subtree_size >= settings.middle_subtree_minimum:
        return 1, "genre_level_subtree"
    if tree_node.subtree_size >= settings.near_subtree_minimum:
        return 2, "subgenre_branch"
    return 3, "close_descendant"


def _lod_assignment(  # noqa: C901
    tree: Mapping[str, _TreeNode],
    regions: Mapping[str, ProductionRegion],
    settings: ProductionMapSettings,
) -> tuple[dict[str, int], dict[str, str]]:
    """Assign persistent LODs with a spatial quota at every doubled resolution.

    The four levels use 2, 4, 8, and 16 cells per axis. At a level, the
    already-visible tree is never removed; one candidate per occupied cell is
    admitted before any cell receives a second candidate. This keeps sparse
    branches legible when one umbrella has many descendants.
    """
    structural = {genre_id: _structural_lod(item, settings) for genre_id, item in tree.items()}
    budgets = (
        settings.overview_label_budget,
        settings.middle_label_budget,
        max(settings.middle_label_budget * 4, len(tree)),
        len(tree),
    )
    assigned: dict[str, int] = {}
    reasons: dict[str, str] = {}
    visible: set[str] = set()
    for level, budget in enumerate(budgets):
        grid = 2 ** (level + 1)
        candidates = [
            genre_id
            for genre_id, (natural_level, _reason) in structural.items()
            if genre_id not in visible and natural_level <= level
        ]
        by_cell: dict[tuple[int, int], list[str]] = defaultdict(list)
        for genre_id in candidates:
            region = regions[genre_id]
            cell = (
                min(grid - 1, int(((region.x0 + region.x1) / 2) * grid)),
                min(grid - 1, int(((region.y0 + region.y1) / 2) * grid)),
            )
            by_cell[cell].append(genre_id)
        ordered_cells = sorted(by_cell, key=lambda cell: (len(by_cell[cell]), cell))
        ordered: list[str] = []
        while any(by_cell.values()):
            for cell in ordered_cells:
                if by_cell[cell]:
                    selected_index = min(
                        range(len(by_cell[cell])),
                        key=lambda index: (
                            -tree[by_cell[cell][index]].subtree_size,
                            by_cell[cell][index],
                        ),
                    )
                    ordered.extend((by_cell[cell].pop(selected_index),))
        for genre_id in ordered:
            if len(visible) >= budget:
                break
            lineage: list[str] = []
            cursor: str | None = genre_id
            while cursor is not None and cursor not in visible:
                lineage.append(cursor)
                cursor = tree[cursor].parent_id
            if len(visible) + len(lineage) > budget:
                continue
            for item in reversed(lineage):
                assigned[item] = level
                reasons[item] = (
                    f"lod_{level}_persistent_spatial_quota_{grid}x{grid}_{structural[item][1]}"
                )
                visible.add(item)
    # The close level is complete even if a small test configuration constrained
    # an earlier level; ancestors are necessarily already present or added here.
    for genre_id in sorted(set(tree) - visible):
        assigned[genre_id] = 3
        reasons[genre_id] = "lod_3_complete_close_descendant"
    return assigned, reasons


def _quantile(values: list[float], quantile: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    index = (len(ordered) - 1) * quantile
    lower = math.floor(index)
    upper = math.ceil(index)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (index - lower)


def _coordinate_hash(nodes: Iterable[ProductionNode]) -> Sha256:
    return _canonical_sha256(
        [
            (item.genre_id, item.x, item.y, item.lod_min)
            for item in sorted(nodes, key=lambda node: node.genre_id)
        ]
    )


def _metrics(
    nodes: tuple[ProductionNode, ...],
    similarity: Mapping[EdgeKey, tuple[float, int]],
    settings: ProductionMapSettings,
    neighbor_reference_sha256: Sha256,
) -> ProductionGeometryMetrics:
    """Measure production-specific gates with no global spectral normalization."""
    by_id = {node.genre_id: node for node in nodes}
    xs = [float(node.x) for node in nodes]
    ys = [float(node.y) for node in nodes]
    grid = settings.geometry_grid_size
    occupied = {
        (
            min(grid - 1, int(float(node.x) * grid)),
            min(grid - 1, int(float(node.y) * grid)),
        )
        for node in nodes
    }
    qa_counts: dict[tuple[int, int], int] = defaultdict(int)
    for node in nodes:
        qa_counts[
            (
                min(_QA_GRID_COLUMNS - 1, int(float(node.x) * _QA_GRID_COLUMNS)),
                min(_QA_GRID_ROWS - 1, int(float(node.y) * _QA_GRID_ROWS)),
            )
        ] += 1
    source: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for (left, right), (weight, _shared) in similarity.items():
        source[left].append((right, weight))
        source[right].append((left, weight))

    def preservation(count: int) -> float:
        values: list[float] = []
        for node in nodes:
            desired = [
                item[0]
                for item in sorted(source[node.genre_id], key=lambda item: (-item[1], item[0]))[
                    :count
                ]
            ]
            if not desired:
                continue
            measured = sorted(
                (other.genre_id for other in nodes if other.genre_id != node.genre_id),
                key=lambda genre_id: (
                    (float(node.x) - float(by_id[genre_id].x)) ** 2
                    + (float(node.y) - float(by_id[genre_id].y)) ** 2,
                    genre_id,
                ),
            )[: len(desired)]
            values.append(len(set(desired) & set(measured)) / len(desired))
        return round(sum(values) / len(values), 12) if values else 0.0

    requested_preservation = preservation(settings.similarity_neighbors_per_genre)
    roots = [node.region for node in nodes if node.display_parent_id is None]
    root_overlaps = sum(
        left.x0 < right.x1 and left.x1 > right.x0 and left.y0 < right.y1 and left.y1 > right.y0
        for index, left in enumerate(roots)
        for right in roots[index + 1 :]
    )
    contained = [
        node.region.x0 >= by_id[node.display_parent_id].region.x0
        and node.region.x1 <= by_id[node.display_parent_id].region.x1
        and node.region.y0 >= by_id[node.display_parent_id].region.y0
        and node.region.y1 <= by_id[node.display_parent_id].region.y1
        for node in nodes
        if node.display_parent_id is not None
    ]
    coordinate_hash = _coordinate_hash(nodes)
    topology_hash = _canonical_sha256(
        [
            (node.genre_id, node.display_parent_id, node.community_id)
            for node in sorted(nodes, key=lambda node: node.genre_id)
        ]
    )
    return ProductionGeometryMetrics(
        central_90_span_x=round(_quantile(xs, 0.95) - _quantile(xs, 0.05), 12),
        central_90_span_y=round(_quantile(ys, 0.95) - _quantile(ys, 0.05), 12),
        occupied_cell_ratio=round(len(occupied) / (grid * grid), 12),
        desktop_16x9_occupied_cell_ratio=round(
            len(qa_counts) / (_QA_GRID_COLUMNS * _QA_GRID_ROWS), 12
        ),
        desktop_16x9_max_cell_fraction=round(max(qa_counts.values()) / len(nodes), 12),
        root_region_overlap_count=root_overlaps,
        overview_label_count=sum(node.lod_min == 0 for node in nodes),
        middle_label_count=sum(node.lod_min <= 1 for node in nodes),
        near_label_count=sum(node.lod_min <= settings.near_subtree_minimum for node in nodes),
        close_label_count=len(nodes),
        mean_knn_preservation=requested_preservation,
        top_10_mean_knn_preservation=preservation(10),
        top_25_mean_knn_preservation=preservation(25),
        neighbor_reference_sha256=neighbor_reference_sha256,
        hierarchy_containment_fraction=(
            round(sum(contained) / len(contained), 12) if contained else 1.0
        ),
        exact_rerun=True,
        coordinate_sha256=coordinate_hash,
        rerun_coordinate_sha256=coordinate_hash,
        topology_sha256=topology_hash,
        temporal_baseline_status="not_supplied",
        temporal_compared_nodes=0,
    )


def _assert_geometry(metrics: ProductionGeometryMetrics, settings: ProductionMapSettings) -> None:
    failures: list[str] = []
    if min(metrics.central_90_span_x, metrics.central_90_span_y) < settings.minimum_central_span:
        failures.append("central 90% span")
    if metrics.occupied_cell_ratio < settings.minimum_occupied_cell_ratio:
        failures.append("occupied grid cells")
    if metrics.desktop_16x9_occupied_cell_ratio < settings.minimum_desktop_16x9_occupied_cell_ratio:
        failures.append("desktop 16x9 occupied cells")
    if metrics.desktop_16x9_max_cell_fraction > settings.maximum_desktop_16x9_cell_fraction:
        failures.append("desktop 16x9 densest cell")
    if metrics.root_region_overlap_count:
        failures.append("root packing")
    if metrics.top_10_mean_knn_preservation < settings.minimum_neighbor_preservation:
        failures.append("similarity neighbor preservation")
    if metrics.hierarchy_containment_fraction != 1.0:
        failures.append("hierarchy containment")
    if failures:
        raise ProductionMapGeometryError("production geometry gates failed: " + ", ".join(failures))


def _screen_labels(
    nodes: tuple[ProductionNode, ...],
    width: int,
    height: int,
    budget: int,
) -> tuple[ProductionScreenLabel, ...]:
    """Predict deterministic, non-overlapping labels for a concrete viewport."""
    placed: list[ProductionScreenLabel] = []
    output: list[ProductionScreenLabel] = []
    for node in sorted(
        nodes,
        key=lambda item: (
            item.lod_min,
            -item.direct_artist_count,
            -item.subtree_size,
            item.genre_id,
        ),
    ):
        label_width = min(240.0, max(28.0, len(node.name) * 7.0 + 10.0))
        label_height = 16.0
        label_x = max(0.0, min(width - label_width, float(node.x) * width + 5.0))
        label_y = max(0.0, min(height - label_height, float(node.y) * height - label_height / 2))
        overlaps = any(
            label_x < item.x + item.width
            and label_x + label_width > item.x
            and label_y < item.y + item.height
            and label_y + label_height > item.y
            for item in placed
        )
        shown = len(placed) < budget and not overlaps
        decision = "shown" if shown else "collision" if overlaps else "budget"
        label = ProductionScreenLabel(
            genre_id=node.genre_id,
            shown=shown,
            decision=decision,
            x=round(label_x, 6),
            y=round(label_y, 6),
            width=label_width,
            height=label_height,
        )
        output.append(label)
        if shown:
            placed.append(label)
    return tuple(output)


def _lods(
    nodes: tuple[ProductionNode, ...], settings: ProductionMapSettings
) -> tuple[ProductionLOD, ...]:
    """Emit node-persistent LOD and explicit desktop/mobile collision decisions."""
    budgets = (
        settings.overview_label_budget,
        settings.middle_label_budget,
        settings.middle_label_budget * 4,
        len(nodes),
    )
    return tuple(
        ProductionLOD(
            level=level,
            visible_node_ids=tuple(
                item.genre_id
                for item in sorted(
                    (node for node in nodes if node.lod_min <= level),
                    key=lambda node: (node.lod_min, -node.subtree_size, node.genre_id),
                )
            ),
            desktop_labels=_screen_labels(
                tuple(node for node in nodes if node.lod_min <= level), 1440, 900, budgets[level]
            ),
            mobile_labels=_screen_labels(
                tuple(node for node in nodes if node.lod_min <= level),
                390,
                844,
                budgets[level] // 2,
            ),
        )
        for level in range(4)
    )


def _electronic_branch(
    names: Mapping[str, str],
    tree: Mapping[str, _TreeNode],
    children: Mapping[str, tuple[str, ...]],
    refs: Mapping[str, tuple[str, ...]],
    settings: ProductionMapSettings,
) -> ProductionBranchAudit:
    candidates = sorted(
        genre_id
        for genre_id, name in names.items()
        if name.casefold() in {"electronic", "electronic music"}
    )
    if not candidates:
        raise ValueError("production map requires a qualified Electronic music umbrella genre")
    root_id = candidates[0]
    descendants: list[str] = []
    queue = [root_id]
    while queue:
        current = queue.pop()
        descendants.append(current)
        queue.extend(reversed(children.get(current, ())))
    maximum_depth = max(tree[item].depth - tree[root_id].depth for item in descendants)
    if maximum_depth < settings.near_subtree_minimum:
        raise ValueError("Electronic music must remain an audited multi-level display branch")
    return ProductionBranchAudit(
        root_genre_id=root_id,
        descendant_genre_ids=tuple(sorted(descendants)),
        maximum_depth=maximum_depth,
        direct_child_count=len(children.get(root_id, ())),
        evidence_refs=refs[root_id],
    )


def build_production_map(
    inputs: PublicModelInput,
    source_model: PublicModelArtifact,
    settings: ProductionMapSettings | None = None,
) -> ProductionMapArtifact:
    """Build one versioned production artifact from qualified public model inputs."""
    started = time.monotonic()
    resolved_settings = settings or ProductionMapSettings()
    if source_model.input_sha256 != _canonical_sha256(inputs):
        raise ValueError("production input must exactly match the qualified source model")
    if not source_model.export_allowed or not all(item.export_allowed for item in inputs.artifacts):
        raise ValueError(
            "production export requires every qualified public artifact to allow export"
        )
    genre_ids = tuple(sorted(item.genre_id for item in inputs.genres))
    names = {item.genre_id: item.name for item in inputs.genres}
    identity_refs = {item.genre_id: item.evidence_refs for item in inputs.genres}
    direct_counts, direct_refs = _direct_counts(inputs)
    similarity = _similarity_lookup(
        source_model.neighbors, resolved_settings.similarity_neighbors_per_genre
    )
    selected, candidate_explanations = _display_parents(inputs, similarity, direct_counts)
    tree, children = _tree(genre_ids, selected)
    communities = _communities(genre_ids, similarity, resolved_settings)
    regions = _regions(tree, children, communities, similarity)
    positions = _force_positions(tree, regions, similarity)
    lod_minima, lod_reasons = _lod_assignment(tree, regions, resolved_settings)
    profiles = _profile_summary(source_model, genre_ids)
    nodes: list[ProductionNode] = []
    explanations: list[ProductionExplanation] = []
    for genre_id in genre_ids:
        item = tree[genre_id]
        region = regions[genre_id]
        position_region = regions[item.root_id]
        lod_min = lod_minima[genre_id]
        lod_reason = lod_reasons[genre_id]
        direct_count, _direct_max, propagated_count, _propagated_max, profile_refs = profiles[
            genre_id
        ]
        evidence_refs = tuple(
            sorted(
                set(identity_refs[genre_id])
                | set(direct_refs.get(genre_id, ()))
                | set(profile_refs)
            )
        )[:32]
        nodes.append(
            ProductionNode(
                genre_id=genre_id,
                name=names[genre_id],
                x=round(positions[genre_id][0], 12),
                y=round(positions[genre_id][1], 12),
                region=region,
                position_region=position_region,
                display_parent_id=item.parent_id,
                root_id=item.root_id,
                depth=item.depth,
                lod_min=lod_min,
                community_id=communities[genre_id],
                subtree_size=item.subtree_size,
                direct_artist_count=direct_counts.get(genre_id, direct_count),
                propagated_artist_count=propagated_count,
                evidence_refs=evidence_refs or identity_refs[genre_id],
            )
        )
        path: list[str] = [genre_id]
        cursor = item.parent_id
        while cursor is not None:
            path.append(cursor)
            cursor = tree[cursor].parent_id
        explanations.append(
            ProductionExplanation(
                genre_id=genre_id,
                parent_candidates=candidate_explanations.get(genre_id, ()),
                chosen_parent_id=item.parent_id,
                root_path=tuple(reversed(path)),
                community_id=communities[genre_id],
                community_evidence_refs=profile_refs[:32],
                lod_reason=lod_reason,
            )
        )
    production_nodes = tuple(nodes)
    taxonomy_edges: list[ProductionTaxonomyEdge] = [
        ProductionTaxonomyEdge(
            source_genre_id=item.child_genre_id,
            target_genre_id=item.parent_genre_id,
            selected_display_parent=(selected.get(item.child_genre_id) == item.parent_genre_id),
            evidence_refs=(item.evidence_ref,),
        )
        for item in sorted(
            inputs.hierarchy, key=lambda edge: (edge.child_genre_id, edge.parent_genre_id)
        )
    ]
    similarity_edges = [
        ProductionSimilarityEdge(
            source_genre_id=left,
            target_genre_id=right,
            weight=round(weight, 12),
            rank=1,
            shared_artist_count=shared,
            evidence_refs=("public-model:one-hop-weighted-jaccard",),
        )
        for (left, right), (weight, shared) in sorted(similarity.items())
    ]
    community_members: dict[str, list[ProductionNode]] = defaultdict(list)
    for node in production_nodes:
        community_members[node.community_id].append(node)
    production_communities = tuple(
        ProductionCommunity(
            community_id=community_id,
            center_x=round(sum(float(item.x) for item in members) / len(members), 12),
            center_y=round(sum(float(item.y) for item in members) / len(members), 12),
            member_count=len(members),
            root_count=sum(item.display_parent_id is None for item in members),
            evidence_refs=("public-model:one-hop-weighted-jaccard",),
        )
        for community_id, members in sorted(community_members.items())
    )
    production_profiles = tuple(
        ProductionGenreProfile(
            genre_id=genre_id,
            direct_artist_count=direct_counts.get(genre_id, values[0]),
            propagated_artist_count=values[2],
            maximum_direct_score=round(values[1], 12),
            maximum_propagated_score=round(values[3], 12),
            evidence_refs=values[4][:32],
        )
        for genre_id, values in sorted(profiles.items())
    )
    production_neighbors = tuple(
        ProductionNeighbor(
            genre_id=item.genre_id,
            neighbor_genre_id=item.neighbor_genre_id,
            rank=item.rank,
            weight=item.score,
            shared_artist_count=item.shared_artist_count,
            evidence_refs=("public-model:one-hop-weighted-jaccard",),
        )
        for item in source_model.neighbors
        if item.profile_kind == "one_hop"
        and item.metric == "weighted_jaccard"
        and item.rank <= resolved_settings.similarity_neighbors_per_genre
    )
    metrics = _metrics(
        production_nodes,
        similarity,
        resolved_settings,
        source_model.output_sha256,
    )
    _assert_geometry(metrics, resolved_settings)
    electronic = _electronic_branch(names, tree, children, identity_refs, resolved_settings)
    lods = _lods(production_nodes, resolved_settings)
    payload = {
        "settings": resolved_settings.model_dump(mode="json"),
        "source_model_output_sha256": source_model.output_sha256,
        "nodes": [item.model_dump(mode="json") for item in production_nodes],
        "communities": [item.model_dump(mode="json") for item in production_communities],
        "edges": [item.model_dump(mode="json") for item in (*taxonomy_edges, *similarity_edges)],
        "profiles": [item.model_dump(mode="json") for item in production_profiles],
        "neighbors": [item.model_dump(mode="json") for item in production_neighbors],
        "explanations": [item.model_dump(mode="json") for item in explanations],
        "lods": [item.model_dump(mode="json") for item in lods],
        "electronic_branch": electronic.model_dump(mode="json"),
        "metrics": metrics.model_dump(mode="json"),
    }
    return ProductionMapArtifact(
        input_sha256=_canonical_sha256(inputs),
        settings_sha256=_canonical_sha256(resolved_settings),
        output_sha256=_canonical_sha256(payload),
        source_model_output_sha256=source_model.output_sha256,
        export_allowed=True,
        nodes=production_nodes,
        communities=production_communities,
        edges=(*taxonomy_edges, *similarity_edges),
        profiles=production_profiles,
        neighbors=production_neighbors,
        explanations=tuple(explanations),
        lods=lods,
        electronic_branch=electronic,
        unplaced=(),
        metrics=metrics,
        resources=source_model.resources.model_copy(
            update={
                "elapsed_ms": round((time.monotonic() - started) * 1_000),
                "peak_rss_bytes": _peak_rss_bytes(),
            }
        ),
    )
