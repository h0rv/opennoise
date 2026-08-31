"""Strict records for public graph validation experiments."""

from typing import Literal

from pydantic import Field, FiniteFloat, model_validator

from musix.models import FrozenModel
from musix.models.modeling import ArtistPairEvidence, PublicArtifact, PublicModelInput
from musix.types import Sha256


class GenreHierarchyEdge(FrozenModel):
    """Keep public genre hierarchy evidence separate from learned similarity."""

    child_genre_id: str = Field(min_length=1, max_length=200)
    parent_genre_id: str = Field(min_length=1, max_length=200)
    evidence_ref: str = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def require_distinct_genres(self) -> "GenreHierarchyEdge":
        """Reject hierarchy self loops."""
        if self.child_genre_id == self.parent_genre_id:
            raise ValueError("genre hierarchy edges cannot be self loops")
        return self


class TemporalPairSnapshot(FrozenModel):
    """Hold one privacy-safe daily graph snapshot."""

    artifact: PublicArtifact
    minimum_listened_at: int = Field(ge=0)
    maximum_listened_at: int = Field(ge=0)
    listens_seen: int = Field(ge=0)
    listens_with_artist_mbid: int = Field(ge=0)
    distinct_artists: int = Field(ge=0)
    user_windows: int = Field(ge=0)
    pairs: tuple[ArtistPairEvidence, ...] = Field(max_length=1_000_000)

    @model_validator(mode="after")
    def require_ordered_coverage(self) -> "TemporalPairSnapshot":
        """Keep temporal coverage and snapshot identity unambiguous."""
        if self.artifact.source != "listenbrainz":
            raise ValueError("temporal pair snapshots require ListenBrainz artifacts")
        if self.minimum_listened_at > self.maximum_listened_at:
            raise ValueError("snapshot time coverage must be ordered")
        return self


class GraphValidationSettings(FrozenModel):
    """Declare deterministic experiment parameters."""

    revision: Literal["public-graph-validation-v1"] = "public-graph-validation-v1"
    neighbors_per_genre: int = Field(default=10, ge=2, le=50)
    community_seeds: tuple[int, ...] = Field(
        default=(20260830, 20260831, 20260832), min_length=1, max_length=8
    )
    maximum_community_iterations: int = Field(default=100, gt=0, le=1_000)

    @model_validator(mode="after")
    def require_unique_seeds(self) -> "GraphValidationSettings":
        """Reject duplicate experiments."""
        if len(self.community_seeds) != len(set(self.community_seeds)):
            raise ValueError("community seeds must be unique")
        return self


class GraphValidationInput(FrozenModel):
    """Bundle the bounded evidence accepted by graph validation."""

    base_inputs: PublicModelInput
    snapshots: tuple[TemporalPairSnapshot, ...] = Field(min_length=3, max_length=14)
    hierarchy: tuple[GenreHierarchyEdge, ...] = Field(max_length=100_000)
    input_database_bytes: int = Field(ge=0)


class CommunityAssignment(FrozenModel):
    """Assign one genre to one experimental graph community."""

    genre_id: str = Field(min_length=1, max_length=200)
    community_id: str = Field(min_length=1, max_length=200)


class CommunityExperiment(FrozenModel):
    """Report one seeded weighted label-propagation experiment."""

    algorithm: Literal["seeded_weighted_label_propagation_v1"]
    seed: int = Field(ge=0)
    iterations: int = Field(ge=0)
    converged: bool
    community_count: int = Field(ge=0)
    modularity: FiniteFloat = Field(ge=-1.0, le=1.0)
    assignments: tuple[CommunityAssignment, ...]


class CommunityStability(FrozenModel):
    """Measure whether seed changes alter discovered co-memberships."""

    experiment_count: int = Field(ge=1)
    mean_pairwise_coassignment_jaccard: FiniteFloat = Field(ge=0.0, le=1.0)


class NeighborhoodValidation(FrozenModel):
    """Measure local graph quality without claiming semantic axes."""

    profile_kind: Literal["one_hop"] = "one_hop"
    metric: Literal["weighted_jaccard"] = "weighted_jaccard"
    neighbors_per_genre: int = Field(gt=0)
    genres_evaluated: int = Field(ge=0)
    mean_knn_preservation: FiniteFloat = Field(ge=0.0, le=1.0)
    truncated_graph_trustworthiness: FiniteFloat = Field(ge=0.0, le=1.0)
    mutual_neighbor_fraction: FiniteFloat = Field(ge=0.0, le=1.0)
    hierarchy_edges_evaluated: int = Field(ge=0)
    hierarchy_recall_at_k: FiniteFloat = Field(ge=0.0, le=1.0)


class TemporalValidation(FrozenModel):
    """Compare cumulative train, validation, and test graph artifacts."""

    left_snapshot: str = Field(min_length=1)
    right_snapshot: str = Field(min_length=1)
    common_genres: int = Field(ge=0)
    directed_neighbor_jaccard: FiniteFloat = Field(ge=0.0, le=1.0)
    aligned_coordinate_rms: FiniteFloat = Field(ge=0.0)


class SourceHoldoutValidation(FrozenModel):
    """Make independent-source holdout availability explicit."""

    status: Literal["available", "unavailable"]
    reason: str = Field(min_length=1)
    training_observations: int = Field(ge=0)
    held_out_observations: int = Field(ge=0)


class ValidationResources(FrozenModel):
    """Record measured experiment costs."""

    elapsed_ms: int = Field(ge=0)
    peak_rss_bytes: int = Field(ge=0)
    input_database_bytes: int = Field(ge=0)


class GraphValidationArtifact(FrozenModel):
    """Publish a deterministic, content-addressed graph validation report."""

    revision: Literal["public-graph-validation-v1"] = "public-graph-validation-v1"
    input_sha256: Sha256
    settings_sha256: Sha256
    output_sha256: Sha256
    export_allowed: bool
    snapshots: tuple[PublicArtifact, ...] = Field(min_length=3, max_length=14)
    hierarchy_edges: int = Field(ge=0)
    communities: tuple[CommunityExperiment, ...] = Field(min_length=1, max_length=8)
    community_stability: CommunityStability
    neighborhood: NeighborhoodValidation
    temporal: tuple[TemporalValidation, ...] = Field(min_length=2, max_length=3)
    source_holdout: SourceHoldoutValidation
    deterministic_rerun: bool
    model_output_sha256: Sha256
    resources: ValidationResources
