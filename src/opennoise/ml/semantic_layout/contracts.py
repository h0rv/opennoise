"""Small, strict contract for an open structural map coordinate artifact."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path  # noqa: TC003
from typing import Literal

from pydantic import Field, model_validator

from opennoise.models import FrozenModel

_REVISION = "semantic-map-layout-v1"
_SEED_COUNT = 6_291
_SHA256 = r"^[0-9a-f]{64}$"

type EvidenceKind = Literal["peer", "colisten", "hierarchy"]


def _canonical_sha256(value: object) -> str:
    """Return a stable digest for a JSON-compatible typed value."""
    payload = json.dumps(
        value, ensure_ascii=False, allow_nan=False, separators=(",", ":"), sort_keys=True
    ).encode()
    return hashlib.sha256(payload).hexdigest()


class SemanticLayoutError(ValueError):
    """Raise when an evidence layout cannot be built or replayed safely."""


class SemanticLayoutSettings(FrozenModel):
    """Small, explicit layout policy; all weights remain structural, not audio axes."""

    revision: Literal["semantic-map-layout-settings-v1"] = "semantic-map-layout-settings-v1"
    world_width: float = Field(default=1.777777777778, gt=1.0, le=3.0)
    world_height: float = Field(default=1.0, gt=0.0, le=1.0)
    margin: float = Field(default=0.035, gt=0.0, lt=0.15)
    peer_weight_scale: float = Field(default=1.0, gt=0.0, le=4.0)
    colisten_weight_scale: float = Field(default=0.35, gt=0.0, le=4.0)
    hierarchy_weight_floor: float = Field(default=0.05, gt=0.0, le=1.0)
    hierarchy_weight_scale: float = Field(default=0.16, gt=0.0, le=1.0)
    peers_per_genre: int = Field(default=10, ge=2, le=50)
    maximum_community_iterations: int = Field(default=60, ge=1, le=500)
    community_tie_seed: int = Field(default=20260913, ge=0)
    maximum_community_size: int = Field(default=240, ge=2, le=2_000)
    overview_label_budget: int = Field(default=24, ge=1, le=200)
    structural_refinement_iterations: int = Field(default=3, ge=0, le=32)
    structural_refinement_strength: float = Field(default=0.08, gt=0.0, le=0.25)


class InputBinding(FrozenModel):
    """Byte and logical identity for a directly consumed source artifact."""

    role: str = Field(min_length=1, max_length=100)
    byte_sha256: str = Field(pattern=_SHA256)
    byte_count: int = Field(gt=0)
    logical_sha256: str | None = Field(default=None, pattern=_SHA256)


class SemanticLayoutInputs(FrozenModel):
    """Explicit, source-neutral input locations; historical paths do not exist here."""

    peer_index: Path
    peer_manifold_artifact: Path
    hierarchy_artifact: Path
    colisten_artifact: Path
    colisten_cache: Path


class SemanticCoordinate(FrozenModel):
    """One evidence-supported stable seed in a landscape structural space."""

    seed_id: str = Field(min_length=1, max_length=200)
    name: str = Field(min_length=1, max_length=500)
    x: float = Field(ge=0.0, le=3.0)
    y: float = Field(ge=0.0, le=1.0)
    component_id: int = Field(ge=0)
    community_id: int = Field(ge=0)
    lod: Literal[0, 1, 2, 3]
    importance: float = Field(ge=0.0)
    label_priority: int = Field(ge=0)
    evidence_kinds: tuple[EvidenceKind, ...] = Field(min_length=1)
    display_parent_id: str | None = Field(default=None, min_length=1, max_length=200)
    hierarchy_root_id: str | None = Field(default=None, min_length=1, max_length=200)
    hierarchy_depth: int = Field(ge=0)
    placement_kind: Literal[
        "peer_manifold", "hierarchy_anchor", "colisten_anchor", "structural_component"
    ] = "structural_component"

    @model_validator(mode="after")
    def _finite_point(self) -> SemanticCoordinate:
        if not math.isfinite(self.x) or not math.isfinite(self.y):
            raise ValueError("structural coordinates must be finite")
        if self.display_parent_id == self.seed_id:
            raise ValueError("a display parent cannot be self")
        if self.display_parent_id is None and self.hierarchy_depth != 0:
            raise ValueError("a root or non-hierarchy seed cannot have a positive hierarchy depth")
        return self


class UnplacedSeed(FrozenModel):
    """One stable seed without an evidenced relation fit for a map coordinate."""

    seed_id: str = Field(min_length=1, max_length=200)
    name: str = Field(min_length=1, max_length=500)
    reason: Literal["no_supported_structural_relation"] = "no_supported_structural_relation"


class OverviewCommunity(FrozenModel):
    """A bounded renderer LOD region anchored by a real, high-importance genre node.

    This is deliberately not a claim of a taxonomic community. Taxonomy remains on
    each coordinate's parent/root chain and peer evidence remains on edge rows.
    """

    community_id: int = Field(ge=0)
    label: str = Field(min_length=1, max_length=500)
    anchor_seed_id: str = Field(default="legacy", min_length=1, max_length=200)
    member_count: int = Field(ge=1)
    component_id: int = Field(ge=0)
    x: float = Field(ge=0.0, le=3.0)
    y: float = Field(ge=0.0, le=1.0)
    overview_visible: bool = False


class CameraBounds(FrozenModel):
    """Explicit camera bounds prevent raw extrema from collapsing the initial map."""

    x0: float = Field(ge=0.0, le=3.0)
    y0: float = Field(ge=0.0, le=1.0)
    x1: float = Field(ge=0.0, le=3.0)
    y1: float = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _ordered(self) -> CameraBounds:
        if self.x1 <= self.x0 or self.y1 <= self.y0:
            raise ValueError("camera bounds must have positive area")
        return self


class StructuralEdge(FrozenModel):
    """A renderer-ready relation with source kind kept separate from display parenthood."""

    left_seed_id: str = Field(min_length=1, max_length=200)
    right_seed_id: str = Field(min_length=1, max_length=200)
    weight: float = Field(gt=0.0)
    evidence_kinds: tuple[EvidenceKind, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _canonical(self) -> StructuralEdge:
        if self.left_seed_id >= self.right_seed_id:
            raise ValueError("structural edges must be canonical and non-self")
        if len(self.evidence_kinds) != len(set(self.evidence_kinds)):
            raise ValueError("structural edge evidence kinds must be unique")
        return self


class GeometryMetrics(FrozenModel):
    """Renderer-independent geometry and evidence-preservation measurements."""

    placed_seed_count: int = Field(ge=0)
    unplaced_seed_count: int = Field(ge=0)
    component_count: int = Field(ge=0)
    community_count: int = Field(ge=0)
    source_peer_edge_count: int = Field(ge=0)
    source_colisten_edge_count: int = Field(ge=0)
    source_hierarchy_edge_count: int = Field(ge=0)
    mean_peer_knn_preservation: float | None = Field(default=None, ge=0.0, le=1.0)
    peer_manifold_seed_count: int = Field(default=0, ge=0)
    mean_colisten_knn_preservation: float | None = Field(default=None, ge=0.0, le=1.0)
    colisten_evaluable_seed_count: int = Field(default=0, ge=0)
    mean_hierarchy_endpoint_distance: float | None = Field(default=None, ge=0.0)
    confidence_weighted_structural_edge_distance: float | None = Field(default=None, ge=0.0)
    structural_edge_distance_p95: float | None = Field(default=None, ge=0.0)
    occupied_world_width_fraction: float = Field(ge=0.0, le=1.0)
    occupied_world_height_fraction: float = Field(ge=0.0, le=1.0)
    exact_coordinate_collision_count: int = Field(ge=0)
    overview_label_collision_count: int = Field(ge=0)
    largest_community_member_count: int = Field(ge=0)
    overview_visible_count: int = Field(default=0, ge=0)
    overview_root_count: int = Field(default=0, ge=0)
    overview_root_coverage_fraction: float = Field(default=0.0, ge=0.0, le=1.0)
    initial_camera_anchor_width_fraction: float = Field(default=0.0, ge=0.0, le=1.0)
    initial_camera_anchor_height_fraction: float = Field(default=0.0, ge=0.0, le=1.0)


class SemanticLayoutArtifact(FrozenModel):
    """One compact renderer-neutral open-evidence structural map layout."""

    revision: Literal["semantic-map-layout-v1"] = _REVISION
    coordinate_semantics: Literal["public_structural_proximity_not_audio_axes"] = (
        "public_structural_proximity_not_audio_axes"
    )
    publication_scope: Literal["local_research_only"] = "local_research_only"
    inputs: tuple[InputBinding, ...] = Field(min_length=5, max_length=5)
    settings: SemanticLayoutSettings
    settings_sha256: str = Field(pattern=_SHA256)
    stable_seed_count: Literal[6291] = _SEED_COUNT
    coordinates: tuple[SemanticCoordinate, ...]
    unplaced: tuple[UnplacedSeed, ...]
    communities: tuple[OverviewCommunity, ...]
    structural_edges: tuple[StructuralEdge, ...]
    world_bounds: CameraBounds
    content_bounds: CameraBounds
    initial_camera: CameraBounds
    metrics: GeometryMetrics
    historical_inputs_read_for_construction: Literal[False] = False
    audio_read_for_construction: Literal[False] = False
    output_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def _complete_partition(self) -> SemanticLayoutArtifact:  # noqa: C901, PLR0912, PLR0915
        coordinate_ids = {item.seed_id for item in self.coordinates}
        unplaced_ids = {item.seed_id for item in self.unplaced}
        if len(coordinate_ids) != len(self.coordinates) or len(unplaced_ids) != len(self.unplaced):
            raise ValueError("seed identities must be unique within each placement state")
        if coordinate_ids & unplaced_ids:
            raise ValueError("a stable seed cannot be both placed and unplaced")
        if len(coordinate_ids) + len(unplaced_ids) != self.stable_seed_count:
            raise ValueError("coordinates and unplaced seeds must partition the stable universe")
        if self.metrics.placed_seed_count != len(self.coordinates):
            raise ValueError("placed metric disagrees with coordinates")
        if self.metrics.unplaced_seed_count != len(self.unplaced):
            raise ValueError("unplaced metric disagrees with unplaced seeds")
        if len({item.community_id for item in self.communities}) != len(self.communities):
            raise ValueError("overview communities must have unique IDs")
        if {item.role for item in self.inputs} != {
            "peer_index",
            "peer_manifold_artifact",
            "hierarchy_artifact",
            "colisten_artifact",
            "colisten_cache",
        }:
            raise ValueError(
                "layout must bind exactly peer manifold, hierarchy, and co-listen inputs"
            )
        if tuple(item.seed_id for item in self.coordinates) != tuple(sorted(coordinate_ids)):
            raise ValueError("coordinates must be sorted by stable seed ID")
        if tuple(item.seed_id for item in self.unplaced) != tuple(sorted(unplaced_ids)):
            raise ValueError("unplaced seeds must be sorted by stable seed ID")
        if tuple(item.community_id for item in self.communities) != tuple(
            sorted(item.community_id for item in self.communities)
        ):
            raise ValueError("communities must be sorted by ID")
        referenced_communities = {item.community_id for item in self.coordinates}
        community_ids = {item.community_id for item in self.communities}
        if referenced_communities != community_ids:
            raise ValueError("communities must be referenced by at least one coordinate")
        member_counts = {
            community_id: sum(item.community_id == community_id for item in self.coordinates)
            for community_id in community_ids
        }
        if any(
            community.member_count != member_counts[community.community_id]
            for community in self.communities
        ):
            raise ValueError("community member ledger does not replay")
        placed_ids = set(coordinate_ids)
        edge_ids = {(edge.left_seed_id, edge.right_seed_id) for edge in self.structural_edges}
        if len(edge_ids) != len(self.structural_edges):
            raise ValueError("structural edges must be unique")
        if tuple(
            (item.left_seed_id, item.right_seed_id) for item in self.structural_edges
        ) != tuple(sorted(edge_ids)):
            raise ValueError("structural edges must be sorted canonically")
        incident_kinds: dict[str, set[EvidenceKind]] = {}
        for edge in self.structural_edges:
            if edge.left_seed_id not in placed_ids or edge.right_seed_id not in placed_ids:
                raise ValueError("structural edge endpoints must be placed")
            incident_kinds.setdefault(edge.left_seed_id, set()).update(edge.evidence_kinds)
            incident_kinds.setdefault(edge.right_seed_id, set()).update(edge.evidence_kinds)
        if any(
            set(item.evidence_kinds) != incident_kinds.get(item.seed_id, set())
            for item in self.coordinates
        ):
            raise ValueError("coordinate evidence kinds must replay from structural edge ledger")
        channel_counts = {
            kind: sum(kind in edge.evidence_kinds for edge in self.structural_edges)
            for kind in ("peer", "colisten", "hierarchy")
        }
        if (
            self.metrics.source_peer_edge_count != channel_counts["peer"]
            or self.metrics.source_colisten_edge_count != channel_counts["colisten"]
            or self.metrics.source_hierarchy_edge_count != channel_counts["hierarchy"]
        ):
            raise ValueError("source channel counts must replay from structural edges")
        coordinate_by_id = {item.seed_id: item for item in self.coordinates}
        edge_distances = tuple(
            math.dist(
                (coordinate_by_id[edge.left_seed_id].x, coordinate_by_id[edge.left_seed_id].y),
                (coordinate_by_id[edge.right_seed_id].x, coordinate_by_id[edge.right_seed_id].y),
            )
            for edge in self.structural_edges
        )
        if self.metrics.confidence_weighted_structural_edge_distance is not None:
            total_weight = sum(edge.weight for edge in self.structural_edges)
            expected_weighted_distance = (
                sum(
                    edge.weight * distance
                    for edge, distance in zip(self.structural_edges, edge_distances, strict=True)
                )
                / total_weight
                if total_weight > 0.0
                else 0.0
            )
            if not math.isclose(
                self.metrics.confidence_weighted_structural_edge_distance,
                expected_weighted_distance,
                rel_tol=0.0,
                abs_tol=1e-10,
            ):
                raise ValueError("confidence-weighted structural distance does not replay")
        if self.metrics.structural_edge_distance_p95 is not None:
            if not edge_distances:
                raise ValueError("structural distance p95 requires structural edges")
            ordered_distances = sorted(edge_distances)
            expected_p95 = ordered_distances[
                min(len(ordered_distances) - 1, math.ceil(0.95 * len(ordered_distances)) - 1)
            ]
            if not math.isclose(
                self.metrics.structural_edge_distance_p95,
                expected_p95,
                rel_tol=0.0,
                abs_tol=1e-10,
            ):
                raise ValueError("structural distance p95 does not replay")
        for community in self.communities:
            anchor = coordinate_by_id.get(community.anchor_seed_id)
            if anchor is None or anchor.community_id != community.community_id:
                raise ValueError("LOD region anchor must be a member coordinate")
            if anchor.name != community.label or anchor.x != community.x or anchor.y != community.y:
                raise ValueError("LOD region label must be anchored to its real genre point")
        overview_communities = tuple(
            community for community in self.communities if community.overview_visible
        )
        if self.metrics.overview_visible_count != len(overview_communities):
            raise ValueError("overview visible metric does not replay")
        overview_anchors = tuple(
            coordinate_by_id[community.anchor_seed_id] for community in overview_communities
        )
        overview_roots = {
            coordinate.hierarchy_root_id or coordinate.seed_id for coordinate in overview_anchors
        }
        if self.metrics.overview_root_count != len(overview_roots):
            raise ValueError("overview root metric does not replay")
        expected_root_fraction = (
            len(overview_roots) / len(overview_anchors) if overview_anchors else 0.0
        )
        if not math.isclose(
            self.metrics.overview_root_coverage_fraction,
            expected_root_fraction,
            rel_tol=0.0,
            abs_tol=1e-12,
        ):
            raise ValueError("overview root coverage metric does not replay")
        if any(anchor.lod != 0 for anchor in overview_anchors):
            raise ValueError("overview anchors must be visible at LOD zero")
        if any(
            not (
                self.initial_camera.x0 <= anchor.x <= self.initial_camera.x1
                and self.initial_camera.y0 <= anchor.y <= self.initial_camera.y1
            )
            for anchor in overview_anchors
        ):
            raise ValueError("initial camera must contain every overview anchor")
        anchor_width = max((anchor.x for anchor in overview_anchors), default=0.0) - min(
            (anchor.x for anchor in overview_anchors), default=0.0
        )
        anchor_height = max((anchor.y for anchor in overview_anchors), default=0.0) - min(
            (anchor.y for anchor in overview_anchors), default=0.0
        )
        expected_width_fraction = anchor_width / (self.initial_camera.x1 - self.initial_camera.x0)
        expected_height_fraction = anchor_height / (self.initial_camera.y1 - self.initial_camera.y0)
        if not math.isclose(
            self.metrics.initial_camera_anchor_width_fraction,
            expected_width_fraction,
            rel_tol=0.0,
            abs_tol=1e-12,
        ) or not math.isclose(
            self.metrics.initial_camera_anchor_height_fraction,
            expected_height_fraction,
            rel_tol=0.0,
            abs_tol=1e-12,
        ):
            raise ValueError("initial camera anchor occupancy metrics do not replay")
        for item in self.coordinates:
            if (item.display_parent_id is None) != (item.hierarchy_depth == 0):
                raise ValueError("display parent must match positive hierarchy depth")
            if (
                item.display_parent_id is not None
                and item.display_parent_id not in coordinate_by_id
            ):
                raise ValueError("display parent must be placed")
            if (
                item.display_parent_id is not None
                and coordinate_by_id[item.display_parent_id].lod > item.lod
            ):
                raise ValueError("hierarchy parent cannot require a deeper zoom than its child")
            if (
                item.hierarchy_root_id is not None
                and item.hierarchy_root_id not in coordinate_by_id
            ):
                raise ValueError("hierarchy root must be placed")
            cursor, seen, steps = item, {item.seed_id}, 0
            while cursor.display_parent_id is not None:
                parent = coordinate_by_id[cursor.display_parent_id]
                if parent.seed_id in seen:
                    raise ValueError("display hierarchy must be acyclic")
                seen.add(parent.seed_id)
                cursor, steps = parent, steps + 1
            if steps != item.hierarchy_depth:
                raise ValueError("hierarchy depth does not replay")
            if item.hierarchy_root_id != (None if steps == 0 else cursor.seed_id):
                raise ValueError("hierarchy root does not replay")
        if not (
            self.world_bounds.x0
            <= self.content_bounds.x0
            < self.content_bounds.x1
            <= self.world_bounds.x1
            and self.world_bounds.y0
            <= self.content_bounds.y0
            < self.content_bounds.y1
            <= self.world_bounds.y1
            and self.world_bounds.x0
            <= self.initial_camera.x0
            < self.initial_camera.x1
            <= self.world_bounds.x1
            and self.world_bounds.y0
            <= self.initial_camera.y0
            < self.initial_camera.y1
            <= self.world_bounds.y1
        ):
            raise ValueError("content and initial camera must fit inside the world")
        if any(
            not (
                self.content_bounds.x0 <= item.x <= self.content_bounds.x1
                and self.content_bounds.y0 <= item.y <= self.content_bounds.y1
            )
            for item in self.coordinates
        ):
            raise ValueError("content bounds must contain every coordinate")
        if self.metrics.component_count != len({item.component_id for item in self.coordinates}):
            raise ValueError("component metric does not replay")
        if self.metrics.community_count != len(self.communities):
            raise ValueError("community metric does not replay")
        if self.metrics.largest_community_member_count != max(member_counts.values(), default=0):
            raise ValueError("largest community metric does not replay")
        if self.metrics.peer_manifold_seed_count > len(self.coordinates):
            raise ValueError("peer manifold coverage exceeds coordinates")
        if self.metrics.colisten_evaluable_seed_count > len(self.coordinates):
            raise ValueError("co-listen coverage exceeds coordinates")
        collisions = len(self.coordinates) - len(
            {(round(item.x, 12), round(item.y, 12)) for item in self.coordinates}
        )
        if self.metrics.exact_coordinate_collision_count != collisions:
            raise ValueError("coordinate collision metric does not replay")
        return self


def semantic_layout_settings_sha256(settings: SemanticLayoutSettings) -> str:
    """Hash validated settings without accepting arbitrary mapping input."""
    return _canonical_sha256(settings.model_dump(mode="json"))


def semantic_layout_sha256(artifact: SemanticLayoutArtifact) -> str:
    """Hash all logical output fields except the self-referential digest."""
    return _canonical_sha256(artifact.model_dump(mode="json", exclude={"output_sha256"}))


def verify_semantic_map_layout(artifact: SemanticLayoutArtifact) -> None:
    """Fail closed if settings or logical output have drifted."""
    if artifact.settings_sha256 != semantic_layout_settings_sha256(artifact.settings):
        raise SemanticLayoutError("semantic layout settings hash does not replay")
    if artifact.output_sha256 != semantic_layout_sha256(artifact):
        raise SemanticLayoutError("semantic layout output hash does not replay")
