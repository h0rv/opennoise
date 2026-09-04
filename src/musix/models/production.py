"""Strict contracts for the single public production genre map."""

from typing import Literal

from pydantic import Field, FiniteFloat, model_validator

from musix.models import FrozenModel
from musix.models.modeling import ModelResources
from musix.types import Sha256

type ProductionEdgeKind = Literal["taxonomy", "similarity"]
type TemporalBaselineStatus = Literal["not_supplied", "compared"]
type ProductionLabelDecision = Literal["shown", "collision", "budget"]


class ProductionMapSettings(FrozenModel):
    """Declare the complete deterministic production layout policy."""

    revision: Literal["production-map-v1"] = "production-map-v1"
    method: Literal["similarity_first_spectral_with_hierarchy_lod"] = (
        "similarity_first_spectral_with_hierarchy_lod"
    )
    method_version: Literal["2"] = "2"
    community_seed: int = Field(default=20260831, ge=0)
    maximum_community_iterations: int = Field(default=100, gt=0, le=1_000)
    similarity_neighbors_per_genre: int = Field(default=10, ge=2, le=25)
    overview_subtree_minimum: int = Field(default=16, ge=2, le=1_000)
    middle_subtree_minimum: int = Field(default=5, ge=2, le=1_000)
    near_subtree_minimum: int = Field(default=2, ge=2, le=1_000)
    overview_label_budget: int = Field(default=160, ge=1, le=500)
    middle_label_budget: int = Field(default=400, ge=1, le=2_000)
    geometry_grid_size: int = Field(default=20, ge=5, le=100)
    minimum_central_span: FiniteFloat = Field(default=0.65, gt=0.0, le=1.0)
    minimum_occupied_cell_ratio: FiniteFloat = Field(default=0.2, gt=0.0, le=1.0)
    minimum_desktop_16x9_occupied_cell_ratio: FiniteFloat = Field(default=0.20, gt=0.0, le=1.0)
    maximum_desktop_16x9_cell_fraction: FiniteFloat = Field(default=0.15, gt=0.0, le=1.0)
    # Certification compares this layout to its declared null and legacy
    # baseline.  A raw recall floor would reject valid similarity-first maps
    # with sparse public source neighborhoods before that calibrated check.
    minimum_neighbor_preservation: FiniteFloat = Field(default=0.0, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def require_ordered_lod_policy(self) -> "ProductionMapSettings":
        """Keep larger subtrees visible no later than smaller subtrees."""
        if not (
            self.overview_subtree_minimum > self.middle_subtree_minimum > self.near_subtree_minimum
        ):
            raise ValueError("LOD subtree thresholds must be strictly descending")
        if self.overview_label_budget > self.middle_label_budget:
            raise ValueError("overview label budget cannot exceed the middle budget")
        return self


class ProductionRegion(FrozenModel):
    """Reserve one nested normalized rectangle for a real genre node."""

    x0: FiniteFloat = Field(ge=0.0, le=1.0)
    y0: FiniteFloat = Field(ge=0.0, le=1.0)
    x1: FiniteFloat = Field(ge=0.0, le=1.0)
    y1: FiniteFloat = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def require_positive_area(self) -> "ProductionRegion":
        """Reject collapsed compound regions."""
        if self.x0 >= self.x1 or self.y0 >= self.y1:
            raise ValueError("production regions require positive width and height")
        return self


class ProductionNode(FrozenModel):
    """Expose one Cytoscape-ready real genre node and semantic LOD tier."""

    genre_id: str = Field(min_length=1, max_length=200)
    name: str = Field(min_length=1, max_length=500)
    x: FiniteFloat = Field(ge=0.0, le=1.0)
    y: FiniteFloat = Field(ge=0.0, le=1.0)
    region: ProductionRegion
    position_region: ProductionRegion
    display_parent_id: str | None = Field(default=None, max_length=200)
    root_id: str = Field(min_length=1, max_length=200)
    depth: int = Field(ge=0, le=100)
    lod_min: int = Field(ge=0, le=3)
    community_id: str = Field(min_length=1, max_length=200)
    subtree_size: int = Field(gt=0)
    direct_artist_count: int = Field(ge=0)
    propagated_artist_count: int = Field(ge=0)
    evidence_refs: tuple[str, ...] = Field(min_length=1, max_length=32)

    @model_validator(mode="after")
    def require_root_shape(self) -> "ProductionNode":
        """Make root and child states impossible to confuse."""
        is_root = self.display_parent_id is None
        if is_root != (self.depth == 0 and self.root_id == self.genre_id):
            raise ValueError("production root identity and depth are inconsistent")
        if self.display_parent_id == self.genre_id:
            raise ValueError("a genre cannot be its own display parent")
        if not (self.position_region.x0 <= self.x <= self.position_region.x1):
            raise ValueError("node x coordinate must be inside its position region")
        if not (self.position_region.y0 <= self.y <= self.position_region.y1):
            raise ValueError("node y coordinate must be inside its position region")
        return self


class ProductionCommunity(FrozenModel):
    """Record one stable detected community and its packed center."""

    community_id: str = Field(min_length=1, max_length=200)
    center_x: FiniteFloat = Field(ge=0.0, le=1.0)
    center_y: FiniteFloat = Field(ge=0.0, le=1.0)
    member_count: int = Field(gt=0)
    root_count: int = Field(ge=0)
    evidence_refs: tuple[str, ...] = Field(max_length=32)


class ProductionTaxonomyEdge(FrozenModel):
    """Keep every exact Wikidata taxonomy edge and mark the display-tree subset."""

    kind: Literal["taxonomy"] = "taxonomy"
    source_genre_id: str = Field(min_length=1, max_length=200)
    target_genre_id: str = Field(min_length=1, max_length=200)
    weight: FiniteFloat = Field(default=1.0, gt=0.0, le=1.0)
    rank: None = None
    selected_display_parent: bool
    evidence_refs: tuple[str, ...] = Field(min_length=1, max_length=32)

    @model_validator(mode="after")
    def require_distinct_nodes(self) -> "ProductionTaxonomyEdge":
        """Reject taxonomy self loops."""
        if self.source_genre_id == self.target_genre_id:
            raise ValueError("taxonomy edges cannot be self loops")
        return self


class ProductionSimilarityEdge(FrozenModel):
    """Publish one canonical validated co-listen-informed similarity edge."""

    kind: Literal["similarity"] = "similarity"
    source_genre_id: str = Field(min_length=1, max_length=200)
    target_genre_id: str = Field(min_length=1, max_length=200)
    weight: FiniteFloat = Field(gt=0.0, le=1.0)
    rank: int = Field(gt=0, le=25)
    selected_display_parent: Literal[False] = False
    shared_artist_count: int = Field(gt=0)
    evidence_refs: tuple[str, ...] = Field(min_length=1, max_length=32)

    @model_validator(mode="after")
    def require_canonical_pair(self) -> "ProductionSimilarityEdge":
        """Prevent duplicated undirected edges."""
        if self.source_genre_id >= self.target_genre_id:
            raise ValueError("similarity edges require ascending distinct genre IDs")
        return self


type ProductionEdge = ProductionTaxonomyEdge | ProductionSimilarityEdge


class ProductionGenreProfile(FrozenModel):
    """Expose bounded membership coverage for one genre."""

    genre_id: str = Field(min_length=1, max_length=200)
    direct_artist_count: int = Field(ge=0)
    propagated_artist_count: int = Field(ge=0)
    maximum_direct_score: FiniteFloat = Field(ge=0.0, le=1.0)
    maximum_propagated_score: FiniteFloat = Field(ge=0.0, le=1.0)
    evidence_refs: tuple[str, ...] = Field(max_length=32)


class ProductionNeighbor(FrozenModel):
    """Keep one directed explainable production neighbor."""

    genre_id: str = Field(min_length=1, max_length=200)
    neighbor_genre_id: str = Field(min_length=1, max_length=200)
    rank: int = Field(gt=0, le=25)
    weight: FiniteFloat = Field(gt=0.0, le=1.0)
    shared_artist_count: int = Field(gt=0)
    evidence_refs: tuple[str, ...] = Field(min_length=1, max_length=32)


class ParentCandidateExplanation(FrozenModel):
    """Show every exact parent candidate considered by the deterministic tie rule."""

    parent_genre_id: str = Field(min_length=1, max_length=200)
    similarity_weight: FiniteFloat = Field(ge=0.0, le=1.0)
    shared_artist_count: int = Field(ge=0)
    parent_direct_artist_count: int = Field(ge=0)
    taxonomy_evidence_refs: tuple[str, ...] = Field(min_length=1, max_length=32)


class ProductionExplanation(FrozenModel):
    """Explain parent, root, community, LOD, and placement for one genre."""

    genre_id: str = Field(min_length=1, max_length=200)
    parent_rule: Literal[
        "one_hop_weighted_jaccard_then_shared_artists_then_parent_direct_count_then_id_v1"
    ] = "one_hop_weighted_jaccard_then_shared_artists_then_parent_direct_count_then_id_v1"
    parent_candidates: tuple[ParentCandidateExplanation, ...] = Field(max_length=64)
    chosen_parent_id: str | None = Field(default=None, max_length=200)
    root_path: tuple[str, ...] = Field(min_length=1, max_length=101)
    community_id: str = Field(min_length=1, max_length=200)
    community_evidence_refs: tuple[str, ...] = Field(max_length=32)
    lod_reason: str = Field(min_length=1, max_length=200)
    placement_reason: Literal["qualified_taxonomy_forest"] = "qualified_taxonomy_forest"


class ProductionUnplaced(FrozenModel):
    """Explain a qualified genre that could not be placed."""

    genre_id: str = Field(min_length=1, max_length=200)
    reason: Literal["invalid_taxonomy", "geometry_limit"]


class ProductionGeometryMetrics(FrozenModel):
    """Make product geometry gates and temporal behavior auditable."""

    central_90_span_x: FiniteFloat = Field(ge=0.0, le=1.0)
    central_90_span_y: FiniteFloat = Field(ge=0.0, le=1.0)
    occupied_cell_ratio: FiniteFloat = Field(ge=0.0, le=1.0)
    desktop_16x9_occupied_cell_ratio: FiniteFloat = Field(ge=0.0, le=1.0)
    desktop_16x9_max_cell_fraction: FiniteFloat = Field(ge=0.0, le=1.0)
    root_region_overlap_count: int = Field(ge=0)
    overview_label_count: int = Field(ge=0)
    middle_label_count: int = Field(ge=0)
    near_label_count: int = Field(ge=0)
    close_label_count: int = Field(ge=0)
    mean_knn_preservation: FiniteFloat = Field(ge=0.0, le=1.0)
    top_10_mean_knn_preservation: FiniteFloat = Field(ge=0.0, le=1.0)
    top_25_mean_knn_preservation: FiniteFloat = Field(ge=0.0, le=1.0)
    neighbor_reference_sha256: Sha256
    hierarchy_containment_fraction: FiniteFloat = Field(ge=0.0, le=1.0)
    exact_rerun: bool
    coordinate_sha256: Sha256
    rerun_coordinate_sha256: Sha256
    topology_sha256: Sha256
    temporal_baseline_status: TemporalBaselineStatus
    temporal_compared_nodes: int = Field(ge=0)
    temporal_aligned_rms: FiniteFloat | None = Field(default=None, ge=0.0)

    @model_validator(mode="after")
    def require_exact_hash_match(self) -> "ProductionGeometryMetrics":
        """Make the asserted deterministic rerun independently inspectable."""
        if self.exact_rerun != (self.coordinate_sha256 == self.rerun_coordinate_sha256):
            raise ValueError("exact rerun flag and coordinate hashes are inconsistent")
        return self


class ProductionScreenLabel(FrozenModel):
    """One deterministic renderer-independent label decision at a screen size."""

    genre_id: str = Field(min_length=1, max_length=200)
    shown: bool
    decision: ProductionLabelDecision
    x: FiniteFloat = Field(ge=0.0)
    y: FiniteFloat = Field(ge=0.0)
    width: FiniteFloat = Field(gt=0.0)
    height: FiniteFloat = Field(gt=0.0)


class ProductionLOD(FrozenModel):
    """A persistent node level and collision-checked screen label instructions."""

    level: int = Field(ge=0, le=3)
    visible_node_ids: tuple[str, ...] = Field(min_length=1, max_length=20_000)
    desktop_labels: tuple[ProductionScreenLabel, ...]
    mobile_labels: tuple[ProductionScreenLabel, ...]


class ProductionBranchAudit(FrozenModel):
    """Audit an explicitly named umbrella branch in the display tree."""

    root_genre_id: str = Field(min_length=1, max_length=200)
    descendant_genre_ids: tuple[str, ...] = Field(min_length=1, max_length=20_000)
    maximum_depth: int = Field(ge=2, le=100)
    direct_child_count: int = Field(ge=1)
    evidence_refs: tuple[str, ...] = Field(min_length=1, max_length=32)


class ProductionMapArtifact(FrozenModel):
    """Publish one complete production map independent of benchmark layouts."""

    revision: Literal["production-map-v1"] = "production-map-v1"
    method: Literal["similarity_first_spectral_with_hierarchy_lod"] = (
        "similarity_first_spectral_with_hierarchy_lod"
    )
    method_version: Literal["2"] = "2"
    input_sha256: Sha256
    settings_sha256: Sha256
    output_sha256: Sha256
    source_model_output_sha256: Sha256
    export_allowed: bool
    nodes: tuple[ProductionNode, ...]
    communities: tuple[ProductionCommunity, ...]
    edges: tuple[ProductionEdge, ...]
    profiles: tuple[ProductionGenreProfile, ...]
    neighbors: tuple[ProductionNeighbor, ...]
    explanations: tuple[ProductionExplanation, ...]
    lods: tuple[ProductionLOD, ...] = Field(min_length=4, max_length=4)
    electronic_branch: ProductionBranchAudit
    unplaced: tuple[ProductionUnplaced, ...]
    metrics: ProductionGeometryMetrics
    resources: ModelResources

    @model_validator(mode="after")
    def require_complete_graph(self) -> "ProductionMapArtifact":  # noqa: C901, PLR0912, PLR0915
        """Validate the complete node, tree, LOD, and explanation boundary."""
        node_by_id = {node.genre_id: node for node in self.nodes}
        if len(node_by_id) != len(self.nodes):
            raise ValueError("production node IDs must be unique")
        unplaced_ids = {item.genre_id for item in self.unplaced}
        if len(unplaced_ids) != len(self.unplaced) or node_by_id.keys() & unplaced_ids:
            raise ValueError("placed and unplaced production genres must be disjoint")
        if {item.genre_id for item in self.profiles} != node_by_id.keys():
            raise ValueError("every placed genre requires one profile summary")
        if {item.genre_id for item in self.explanations} != node_by_id.keys():
            raise ValueError("every placed genre requires one explanation")
        expected_levels = tuple(range(4))
        if tuple(item.level for item in self.lods) != expected_levels:
            raise ValueError("production LOD levels must be exactly ordered 0 through 3")
        previous_visible: set[str] = set()
        for lod in self.lods:
            visible = set(lod.visible_node_ids)
            if len(visible) != len(lod.visible_node_ids) or not visible <= node_by_id.keys():
                raise ValueError("LOD visible genre IDs must be unique placed nodes")
            if not previous_visible <= visible:
                raise ValueError("production LOD nodes cannot disappear at a closer level")
            if visible != {node.genre_id for node in self.nodes if node.lod_min <= lod.level}:
                raise ValueError("LOD visibility must exactly honor node lod_min")
            previous_visible = visible
        taxonomy = {
            (edge.source_genre_id, edge.target_genre_id)
            for edge in self.edges
            if edge.kind == "taxonomy"
        }
        selected = {
            (edge.source_genre_id, edge.target_genre_id)
            for edge in self.edges
            if edge.kind == "taxonomy" and edge.selected_display_parent
        }
        for node in self.nodes:
            parent = node.display_parent_id
            if parent is None:
                continue
            if parent not in node_by_id or (node.genre_id, parent) not in selected:
                raise ValueError("display parent must be a placed selected taxonomy edge")
            parent_node = node_by_id[parent]
            if node.root_id != parent_node.root_id or node.depth != parent_node.depth + 1:
                raise ValueError("display tree root or depth is inconsistent")
            if node.lod_min < parent_node.lod_min:
                raise ValueError("a child cannot become visible before its parent")
        if not selected <= taxonomy:
            raise ValueError("selected display parents must belong to the taxonomy DAG")
        similarity = [edge for edge in self.edges if edge.kind == "similarity"]
        similarity_keys = {(edge.source_genre_id, edge.target_genre_id) for edge in similarity}
        if len(similarity_keys) != len(similarity):
            raise ValueError("production similarity edges must be unique")
        community_ids = {item.community_id for item in self.communities}
        if any(node.community_id not in community_ids for node in self.nodes):
            raise ValueError("every node requires a declared community")
        electronic = self.electronic_branch
        if electronic.root_genre_id not in node_by_id:
            raise ValueError("electronic branch root must be placed")
        descendants = set(electronic.descendant_genre_ids)
        if not descendants <= node_by_id.keys() or electronic.root_genre_id not in descendants:
            raise ValueError("electronic branch descendants must be placed and include its root")
        if max(node_by_id[item].depth for item in descendants) < electronic.maximum_depth:
            raise ValueError("electronic branch maximum depth exceeds its display tree")
        return self
