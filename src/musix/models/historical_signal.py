"""Typed, reproducible contracts for the local Every Noise signal reconstruction."""

from typing import Literal

from pydantic import Field, FiniteFloat, model_validator

from musix.models import FrozenModel
from musix.types import Sha256

_UMBRELLA_LEVEL = 0
_SUBCOMMUNITY_LEVEL = 1
_MICROGENRE_LEVEL = 2
_MIN_COMPONENTS_IN_BUNDLE = 2
_FULL_NODE_COUNT = 6_291
_MIN_FULL_UMBRELLAS = 2
_MAX_FULL_UMBRELLAS = 24
HISTORICAL_FULL_MAP_NODE_TARGET = _FULL_NODE_COUNT


class HistoricalSignalSettings(FrozenModel):
    """Fixed public-signal configuration; no legacy coordinates are model inputs."""

    revision: Literal["historical-signal-v1"] = "historical-signal-v1"
    method: Literal[
        "idf_membership_knn_diffusion_v1",
        "idf_membership_knn_spectral_v1",
        "idf_membership_knn_spectral_force_v1",
    ] = "idf_membership_knn_diffusion_v1"
    embedding_method: Literal[
        "anchored_diffusion", "normalized_laplacian_spectral", "spectral_force_refined"
    ] = "anchored_diffusion"
    neighbors_per_genre: int = Field(default=20, ge=2, le=50)
    maximum_artist_genre_degree: int = Field(default=32, ge=2, le=1_000)
    label_propagation_iterations: int = Field(default=30, ge=1, le=200)
    embedding_iterations: int = Field(default=90, ge=1, le=1_000)
    embedding_seed: int = Field(default=20260904, ge=0)
    evaluation_neighbor_count: int = Field(default=10, ge=1, le=50)
    evaluation_pair_sample: int = Field(default=50_000, ge=1_000, le=500_000)
    # Umbrellas are evidence-derived regions; browser response limits cap aggregate results, not leaves.
    hierarchy_umbrella_max_members: int = Field(default=3_000, ge=32, le=3_000)
    hierarchy_subcommunity_max_members: int = Field(default=512, ge=8, le=512)
    hierarchy_microgenre_max_members: int = Field(default=24, ge=2, le=128)

    @model_validator(mode="after")
    def require_method_matches_embedding(self) -> "HistoricalSignalSettings":
        """Bind the hashable method identifier to the actual layout algorithm."""
        expected = (
            "idf_membership_knn_diffusion_v1"
            if self.embedding_method == "anchored_diffusion"
            else (
                "idf_membership_knn_spectral_v1"
                if self.embedding_method == "normalized_laplacian_spectral"
                else "idf_membership_knn_spectral_force_v1"
            )
        )
        if self.method != expected:
            raise ValueError("historical signal method must match embedding method")
        if not (
            self.hierarchy_umbrella_max_members
            >= self.hierarchy_subcommunity_max_members
            >= self.hierarchy_microgenre_max_members
        ):
            raise ValueError("historical hierarchy member bounds must descend by zoom level")
        return self


class HistoricalSignalInput(FrozenModel):
    """Hash every local-only input while preserving the no-coordinate training boundary."""

    h2_artifact_sha256: Sha256
    h3_artifact_sha256: Sha256
    h3_database_sha256: Sha256
    genre_count: int = Field(gt=0, le=20_000)
    membership_count: int = Field(ge=0, le=2_000_000)
    mapped_membership_genre_count: int = Field(ge=0, le=20_000)
    distinct_artist_count: int = Field(ge=0, le=2_000_000)
    coordinate_training_status: Literal["excluded"] = "excluded"


class HistoricalSignalMembership(FrozenModel):
    """One source-scoped direct membership with no audio or preview values."""

    genre_id: str = Field(min_length=1, max_length=200)
    artist_id: str = Field(min_length=1, max_length=200)
    confidence: FiniteFloat = Field(default=1.0, gt=0.0, le=1.0)
    evidence_kind: Literal["h3_genre_to_artist"] = "h3_genre_to_artist"


class HistoricalSignalNeighbor(FrozenModel):
    """One explainable weighted similarity candidate retained in the kNN graph."""

    genre_id: str = Field(min_length=1, max_length=200)
    neighbor_genre_id: str = Field(min_length=1, max_length=200)
    rank: int = Field(gt=0, le=50)
    weighted_jaccard: FiniteFloat = Field(gt=0.0, le=1.0)
    cosine: FiniteFloat = Field(gt=0.0, le=1.0)
    idf_overlap: FiniteFloat = Field(gt=0.0)
    shared_artist_count: int = Field(gt=0)
    evidence_kind: Literal["h3_genre_to_artist"] = "h3_genre_to_artist"

    @model_validator(mode="after")
    def require_distinct_genres(self) -> "HistoricalSignalNeighbor":
        """Reject self-neighbors before a graph can be published."""
        if self.genre_id == self.neighbor_genre_id:
            raise ValueError("historical signal neighbors must be distinct")
        return self


class HistoricalSignalNode(FrozenModel):
    """One all-scale coordinate learned only from H3 topology."""

    genre_id: str = Field(min_length=1, max_length=200)
    name: str = Field(min_length=1, max_length=500)
    x: FiniteFloat = Field(ge=0.0, le=2.0)
    y: FiniteFloat = Field(ge=0.0, le=1.0)
    community_id: str = Field(min_length=1, max_length=200)
    umbrella_id: str = Field(min_length=1, max_length=200)
    subcommunity_id: str = Field(min_length=1, max_length=200)
    microgenre_id: str = Field(min_length=1, max_length=200)
    component_id: int = Field(ge=0)
    membership_count: int = Field(ge=0)
    lod_min: int = Field(ge=0, le=3)
    evidence_kind: Literal["h3_genre_to_artist", "no_h3_membership"]


class HistoricalSignalCommunity(FrozenModel):
    """A deterministic weighted-label-propagation community."""

    community_id: str = Field(min_length=1, max_length=200)
    member_count: int = Field(gt=0)
    component_count: int = Field(gt=0)
    representative_genre_id: str = Field(min_length=1, max_length=200)


class HistoricalSignalHierarchyNode(FrozenModel):
    """One graph-derived zoom grouping, not a semantic genre taxonomy."""

    hierarchy_id: str = Field(min_length=1, max_length=200)
    parent_id: str | None = Field(default=None, min_length=1, max_length=200)
    children_ids: tuple[str, ...] = Field(default=(), max_length=2_000)
    level: Literal[0, 1, 2]
    member_count: int = Field(gt=0, le=20_000)
    component_count: int = Field(default=1, gt=0, le=20_000)
    representative_genre_id: str = Field(min_length=1, max_length=200)
    representative_label: str = Field(min_length=1, max_length=500)
    x: FiniteFloat = Field(ge=0.0, le=2.0)
    y: FiniteFloat = Field(ge=0.0, le=1.0)
    provenance: Literal[
        "graph_derived_h3_similarity", "graph_and_genre_name_derived"
    ] = "graph_derived_h3_similarity"
    connectivity: Literal["connected", "disconnected_bundle"] = "connected"

    @model_validator(mode="after")
    def require_level_shape(self) -> "HistoricalSignalHierarchyNode":
        """Keep the UI hierarchy explicitly limited to its three zoom levels."""
        if self.level == _UMBRELLA_LEVEL and self.parent_id is not None:
            raise ValueError("umbrella hierarchy nodes cannot have a parent")
        if self.level > _UMBRELLA_LEVEL and self.parent_id is None:
            raise ValueError("non-umbrella hierarchy nodes must have a parent")
        if self.level == _MICROGENRE_LEVEL and self.children_ids:
            raise ValueError("microgenre hierarchy nodes cannot have children")
        if self.level < _MICROGENRE_LEVEL and not self.children_ids:
            raise ValueError("non-leaf hierarchy nodes must expose children")
        if self.connectivity == "connected" and self.component_count != 1:
            raise ValueError("connected hierarchy nodes must contain one graph component")
        if (
            self.connectivity == "disconnected_bundle"
            and self.component_count < _MIN_COMPONENTS_IN_BUNDLE
        ):
            raise ValueError("disconnected hierarchy bundles must contain multiple components")
        return self


class HistoricalSignalLOD(FrozenModel):
    """Bound initial browser work at each progressive map level."""

    level: int = Field(ge=0, le=3)
    node_count: int = Field(ge=0, le=20_000)
    initial_edge_count: Literal[0] = 0
    focus_edge_budget: int = Field(ge=0, le=200)


class HistoricalSignalTile(FrozenModel):
    """A viewport-tile membership list, separate from full node records."""

    level: int = Field(ge=0, le=3)
    column: int = Field(ge=0, le=15)
    row: int = Field(ge=0, le=15)
    node_ids: tuple[str, ...] = Field(min_length=1, max_length=2_000)


class HistoricalSignalGeometry(FrozenModel):
    """Landscape viewport expectations validated without legacy-coordinate fitting."""

    viewport_aspect_ratio: FiniteFloat = Field(default=16 / 9, gt=1.0, le=3.0)
    tile_columns: int = Field(default=16, ge=1, le=16)
    tile_rows: int = Field(default=16, ge=1, le=16)
    central_q05_q95_span_x: FiniteFloat = Field(gt=0.0, le=2.0)
    central_q05_q95_span_y: FiniteFloat = Field(gt=0.0, le=1.0)
    central_span_aspect_ratio: FiniteFloat = Field(gt=0.0, le=3.0)


class CoordinateComparison(FrozenModel):
    """Coordinate-oracle evaluation, explicitly separate from fitting."""

    oracle: Literal["h2_legacy_coordinates"] = "h2_legacy_coordinates"
    used_for_training: Literal[False] = False
    compared_node_count: int = Field(ge=0)
    procrustes_aligned_rms: FiniteFloat | None = Field(default=None, ge=0.0)
    normalized_stress: FiniteFloat | None = Field(default=None, ge=0.0)
    sampled_distance_rank_correlation: FiniteFloat | None = Field(default=None, ge=-1.0, le=1.0)
    legacy_neighborhood_recall_at_k: FiniteFloat | None = Field(default=None, ge=0.0, le=1.0)
    embedding_graph_neighbor_recall_at_k: FiniteFloat | None = Field(default=None, ge=0.0, le=1.0)
    direct_weighted_jaccard_recall_at_k: FiniteFloat | None = Field(default=None, ge=0.0, le=1.0)
    direct_cosine_recall_at_k: FiniteFloat | None = Field(default=None, ge=0.0, le=1.0)
    direct_idf_overlap_recall_at_k: FiniteFloat | None = Field(default=None, ge=0.0, le=1.0)
    direct_shared_artist_recall_at_k: FiniteFloat | None = Field(default=None, ge=0.0, le=1.0)


class HistoricalSignalAblation(FrozenModel):
    """Make active, disabled, and oracle-only signals unambiguous."""

    name: str = Field(min_length=1, max_length=100)
    role: Literal["active", "disabled_auxiliary", "evaluation_oracle"]
    detail: str = Field(min_length=1, max_length=500)


class HistoricalSignalQuality(FrozenModel):
    """Coverage, graph, and determinism facts for a full model run."""

    node_count: int = Field(gt=0)
    member_genre_count: int = Field(ge=0)
    zero_membership_genre_count: int = Field(ge=0)
    similarity_edge_count: int = Field(ge=0)
    community_count: int = Field(ge=0)
    connected_component_count: int = Field(ge=0)
    mean_neighbor_weight: FiniteFloat = Field(ge=0.0, le=1.0)
    hierarchy_umbrella_count: int = Field(ge=0, le=20_000)
    hierarchy_subcommunity_count: int = Field(ge=0, le=20_000)
    hierarchy_microgenre_count: int = Field(ge=0, le=20_000)
    hierarchy_node_coverage: FiniteFloat = Field(ge=0.0, le=1.0)
    hierarchy_microgenre_internal_edge_fraction: FiniteFloat = Field(ge=0.0, le=1.0)
    hierarchy_max_microgenre_member_count: int = Field(ge=0, le=20_000)
    artifact_sha256: Sha256
    exact_rerun: bool


def _require_hierarchy_parent_edges(
    hierarchy: tuple[HistoricalSignalHierarchyNode, ...],
    hierarchy_by_id: dict[str, HistoricalSignalHierarchyNode],
) -> None:
    for item in hierarchy:
        if len(set(item.children_ids)) != len(item.children_ids):
            raise ValueError("historical signal hierarchy children must be unique")
        if any(child_id not in hierarchy_by_id for child_id in item.children_ids):
            raise ValueError("historical signal hierarchy children must exist")
        if item.parent_id is not None:
            parent = hierarchy_by_id.get(item.parent_id)
            if parent is None or parent.level + 1 != item.level:
                raise ValueError("historical signal hierarchy parents must be adjacent levels")
            if item.hierarchy_id not in parent.children_ids:
                raise ValueError("historical signal hierarchy parent must list each child")


def _require_hierarchy_child_edges(
    hierarchy: tuple[HistoricalSignalHierarchyNode, ...],
    hierarchy_by_id: dict[str, HistoricalSignalHierarchyNode],
) -> None:
    for parent in hierarchy:
        if not parent.children_ids:
            continue
        children = tuple(hierarchy_by_id[child_id] for child_id in parent.children_ids)
        if any(child.level != parent.level + 1 for child in children):
            raise ValueError("historical signal hierarchy children must be adjacent levels")
        if any(child.parent_id != parent.hierarchy_id for child in children):
            raise ValueError("historical signal hierarchy children must point to their parent")
        if sum(child.member_count for child in children) != parent.member_count:
            raise ValueError("historical signal hierarchy child counts must sum to parent count")


def _require_hierarchy_structure(hierarchy: tuple[HistoricalSignalHierarchyNode, ...]) -> None:
    """Validate unique, parent-closed hierarchy edges before node memberships are checked."""
    hierarchy_by_id = {item.hierarchy_id: item for item in hierarchy}
    if len(hierarchy_by_id) != len(hierarchy):
        raise ValueError("historical signal hierarchy IDs must be unique")
    _require_hierarchy_parent_edges(hierarchy, hierarchy_by_id)
    _require_hierarchy_child_edges(hierarchy, hierarchy_by_id)


def _require_hierarchy_node_paths(
    hierarchy: tuple[HistoricalSignalHierarchyNode, ...], nodes: tuple[HistoricalSignalNode, ...]
) -> tuple[int, int, int]:
    """Verify every node has one closed umbrella-to-microgenre graph hierarchy path."""
    hierarchy_by_id = {item.hierarchy_id: item for item in hierarchy}
    microgenres = {item.hierarchy_id: item for item in hierarchy if item.level == _MICROGENRE_LEVEL}
    subcommunities = {
        item.hierarchy_id: item for item in hierarchy if item.level == _SUBCOMMUNITY_LEVEL
    }
    umbrellas = {item.hierarchy_id: item for item in hierarchy if item.level == _UMBRELLA_LEVEL}
    if any(
        node.umbrella_id not in umbrellas
        or node.subcommunity_id not in subcommunities
        or node.microgenre_id not in microgenres
        for node in nodes
    ):
        raise ValueError("every historical signal node must have a complete hierarchy path")
    if any(
        node.community_id != node.umbrella_id
        or subcommunities[node.subcommunity_id].parent_id != node.umbrella_id
        or microgenres[node.microgenre_id].parent_id != node.subcommunity_id
        for node in nodes
    ):
        raise ValueError("historical signal node hierarchy paths must be parent-closed")
    membership_counts = {
        hierarchy_id: sum(
            (node.umbrella_id, node.subcommunity_id, node.microgenre_id).count(hierarchy_id)
            for node in nodes
        )
        for hierarchy_id in hierarchy_by_id
    }
    if any(
        membership_counts[hierarchy_id] != item.member_count
        for hierarchy_id, item in hierarchy_by_id.items()
    ):
        raise ValueError("historical signal hierarchy member counts must match node paths")
    return len(umbrellas), len(subcommunities), len(microgenres)


class HistoricalSignalArtifact(FrozenModel):
    """Production-ready 6,291-node local historical reconstruction artifact."""

    revision: Literal["historical-signal-v1"] = "historical-signal-v1"
    settings: HistoricalSignalSettings
    inputs: HistoricalSignalInput
    nodes: tuple[HistoricalSignalNode, ...] = Field(min_length=1, max_length=20_000)
    neighbors: tuple[HistoricalSignalNeighbor, ...] = Field(max_length=1_000_000)
    communities: tuple[HistoricalSignalCommunity, ...] = Field(max_length=20_000)
    hierarchy: tuple[HistoricalSignalHierarchyNode, ...] = Field(min_length=3, max_length=20_000)
    geometry: HistoricalSignalGeometry
    progressive_lods: tuple[HistoricalSignalLOD, ...] = Field(min_length=4, max_length=4)
    tiles: tuple[HistoricalSignalTile, ...] = Field(max_length=1_024)
    ablations: tuple[HistoricalSignalAblation, ...] = Field(min_length=3, max_length=20)
    coordinate_evaluation: CoordinateComparison
    quality: HistoricalSignalQuality

    @model_validator(mode="after")
    def require_one_node_per_genre(self) -> "HistoricalSignalArtifact":
        """Make the full retained vocabulary contract enforceable."""
        if len({node.genre_id for node in self.nodes}) != len(self.nodes):
            raise ValueError("historical signal nodes must have unique genre IDs")
        if self.inputs.genre_count != len(self.nodes):
            raise ValueError("historical signal input genre count must equal node count")
        _require_hierarchy_structure(self.hierarchy)
        umbrellas, subcommunities, microgenres = _require_hierarchy_node_paths(
            self.hierarchy, self.nodes
        )
        if self.quality.hierarchy_node_coverage != 1.0:
            raise ValueError("historical signal hierarchy must cover every retained node")
        if (
            self.quality.hierarchy_umbrella_count != umbrellas
            or self.quality.hierarchy_subcommunity_count != subcommunities
            or self.quality.hierarchy_microgenre_count != microgenres
        ):
            raise ValueError("historical signal hierarchy quality counts must match the artifact")
        if (
            self.inputs.genre_count == _FULL_NODE_COUNT
            and not _MIN_FULL_UMBRELLAS <= umbrellas <= _MAX_FULL_UMBRELLAS
        ):
            raise ValueError("6,291-node historical hierarchy must contain 2 to 24 umbrellas")
        return self


class HistoricalSignalPublicationQuality(FrozenModel):
    """Record publication gates for an explicit local historical-map opt-in."""

    required_node_count: Literal[6291] = HISTORICAL_FULL_MAP_NODE_TARGET
    node_count: int = Field(gt=0, le=20_000)
    final_lod_node_count: int = Field(gt=0, le=20_000)
    final_lod_tile_node_count: int = Field(gt=0, le=20_000)
    h3_membership_count: int = Field(ge=0, le=2_000_000)
    h3_member_genre_count: int = Field(ge=0, le=20_000)
    h2_oracle_evaluation_node_count: int = Field(ge=0, le=20_000)
    deterministic_source_build: Literal[True] = True
    deterministic_publication: Literal[True] = True
    h2_coordinates_excluded_from_training: Literal[True] = True
    default_production_promotion: Literal[False] = False


class HistoricalSignalPublicationArtifact(FrozenModel):
    """A sealed local-only map envelope around an H3-built signal artifact.

    This deliberately remains separate from ``ProductionMapArtifact``: the latter
    makes qualified public-taxonomy claims that historical H3 evidence cannot make.
    """

    revision: Literal["historical-signal-publication-v1"] = "historical-signal-publication-v1"
    source_signal_artifact_sha256: Sha256
    h2_artifact_sha256: Sha256
    h3_artifact_sha256: Sha256
    h3_database_sha256: Sha256
    h3_policy_key: str = Field(min_length=1, max_length=300)
    h3_membership_query_view: Literal["displayable_historical_genre_artists"] = (
        "displayable_historical_genre_artists"
    )
    map: HistoricalSignalArtifact
    quality: HistoricalSignalPublicationQuality

    @model_validator(mode="after")
    def require_safe_complete_local_map(self) -> "HistoricalSignalPublicationArtifact":
        """Bind every published coordinate to the sealed H3-only source build."""
        _require_publication_provenance(self)
        _require_publication_delivery(self)
        _require_publication_coordinate_boundary(self)
        return self


class HistoricalSignalPublicationReceipt(FrozenModel):
    """Portable object-store receipt for a local historical signal map."""

    revision: Literal["historical-signal-publication-receipt-v1"] = (
        "historical-signal-publication-receipt-v1"
    )
    artifact_sha256: Sha256
    artifact_byte_size: int = Field(gt=0)
    object_key: str = Field(min_length=1, max_length=1_000)
    source_signal_artifact_sha256: Sha256
    h2_artifact_sha256: Sha256
    h3_artifact_sha256: Sha256
    h3_database_sha256: Sha256
    h3_policy_key: str = Field(min_length=1, max_length=300)
    h3_membership_query_view: Literal["displayable_historical_genre_artists"] = (
        "displayable_historical_genre_artists"
    )
    default_production_promotion: Literal[False] = False


def _require_publication_provenance(artifact: HistoricalSignalPublicationArtifact) -> None:
    if artifact.source_signal_artifact_sha256 != artifact.map.quality.artifact_sha256:
        raise ValueError("publication signal hash must match the embedded map")
    if artifact.h2_artifact_sha256 != artifact.map.inputs.h2_artifact_sha256:
        raise ValueError("publication H2 provenance must match the embedded map")
    if artifact.h3_artifact_sha256 != artifact.map.inputs.h3_artifact_sha256:
        raise ValueError("publication H3 provenance must match the embedded map")
    if artifact.h3_database_sha256 != artifact.map.inputs.h3_database_sha256:
        raise ValueError("publication H3 database hash must match the embedded map")
    if not artifact.h3_policy_key.startswith("historical-membership:local-display:"):
        raise ValueError("publication H3 policy must be an explicit local-display policy")
    if artifact.quality.h3_membership_count != artifact.map.inputs.membership_count:
        raise ValueError("publication membership count must match the embedded map")
    if artifact.quality.h3_member_genre_count != artifact.map.inputs.mapped_membership_genre_count:
        raise ValueError("publication member genre count must match the embedded map")


def _require_publication_delivery(artifact: HistoricalSignalPublicationArtifact) -> None:
    if artifact.quality.node_count != len(artifact.map.nodes):
        raise ValueError("publication node count must match the embedded map")
    if artifact.quality.node_count != HISTORICAL_FULL_MAP_NODE_TARGET:
        raise ValueError("historical full-map publication must contain all 6,291 nodes")
    final_lod = artifact.map.progressive_lods[-1]
    if artifact.quality.final_lod_node_count != final_lod.node_count:
        raise ValueError("publication final LOD count must match the embedded map")
    if final_lod.node_count != len(artifact.map.nodes):
        raise ValueError("historical final LOD must expose every node")
    final_tiles = [tile for tile in artifact.map.tiles if tile.level == final_lod.level]
    final_tile_ids = [genre_id for tile in final_tiles for genre_id in tile.node_ids]
    if len(set(final_tile_ids)) != len(final_tile_ids) or set(final_tile_ids) != {
        node.genre_id for node in artifact.map.nodes
    }:
        raise ValueError("historical final LOD tiles must partition every node exactly once")
    if artifact.quality.final_lod_tile_node_count != len(final_tile_ids):
        raise ValueError("publication tile count must match the embedded map")


def _require_publication_coordinate_boundary(artifact: HistoricalSignalPublicationArtifact) -> None:
    if (
        artifact.quality.h2_oracle_evaluation_node_count
        != artifact.map.coordinate_evaluation.compared_node_count
    ):
        raise ValueError("publication H2 evaluation count must match the embedded map")
    if artifact.map.inputs.coordinate_training_status != "excluded":
        raise ValueError("H2 coordinates must be excluded from historical map training")
    if artifact.map.coordinate_evaluation.used_for_training:
        raise ValueError("H2 coordinates must remain an evaluation-only oracle")
