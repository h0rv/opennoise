"""Typed, reproducible contracts for the local Every Noise signal reconstruction."""

from typing import Literal

from pydantic import Field, FiniteFloat, model_validator

from musix.models import FrozenModel
from musix.types import Sha256


class HistoricalSignalSettings(FrozenModel):
    """Fixed public-signal configuration; no legacy coordinates are model inputs."""

    revision: Literal["historical-signal-v1"] = "historical-signal-v1"
    method: Literal["idf_membership_knn_diffusion_v1", "idf_membership_knn_spectral_v1"] = (
        "idf_membership_knn_diffusion_v1"
    )
    embedding_method: Literal["anchored_diffusion", "normalized_laplacian_spectral"] = (
        "anchored_diffusion"
    )
    neighbors_per_genre: int = Field(default=20, ge=2, le=50)
    maximum_artist_genre_degree: int = Field(default=32, ge=2, le=1_000)
    label_propagation_iterations: int = Field(default=30, ge=1, le=200)
    embedding_iterations: int = Field(default=90, ge=1, le=1_000)
    embedding_seed: int = Field(default=20260904, ge=0)
    evaluation_neighbor_count: int = Field(default=10, ge=1, le=50)
    evaluation_pair_sample: int = Field(default=50_000, ge=1_000, le=500_000)

    @model_validator(mode="after")
    def require_method_matches_embedding(self) -> "HistoricalSignalSettings":
        """Bind the hashable method identifier to the actual layout algorithm."""
        expected = (
            "idf_membership_knn_diffusion_v1"
            if self.embedding_method == "anchored_diffusion"
            else "idf_membership_knn_spectral_v1"
        )
        if self.method != expected:
            raise ValueError("historical signal method must match embedding method")
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
    artifact_sha256: Sha256
    exact_rerun: bool


class HistoricalSignalArtifact(FrozenModel):
    """Production-ready 6,291-node local historical reconstruction artifact."""

    revision: Literal["historical-signal-v1"] = "historical-signal-v1"
    settings: HistoricalSignalSettings
    inputs: HistoricalSignalInput
    nodes: tuple[HistoricalSignalNode, ...] = Field(min_length=1, max_length=20_000)
    neighbors: tuple[HistoricalSignalNeighbor, ...] = Field(max_length=1_000_000)
    communities: tuple[HistoricalSignalCommunity, ...] = Field(max_length=20_000)
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
        return self
