"""Strict records for public graph validation experiments."""

from typing import Literal

from pydantic import Field, FiniteFloat, model_validator

from musix.models import FrozenModel
from musix.models.catalog import ArtistCoListenRunProjection
from musix.models.modeling import ArtistPairEvidence, PublicArtifact, PublicModelInput
from musix.types import Sha256

_MINIMUM_TEMPORAL_PRIVACY_FLOOR = 5


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


class TemporalPairWindow(FrozenModel):
    """Hold one disjoint event-time window from a joint raw aggregation."""

    window_start: int = Field(ge=0)
    window_end: int = Field(gt=0)
    pairs: tuple[ArtistPairEvidence, ...] = Field(max_length=1_000_000)

    @model_validator(mode="after")
    def require_single_window_evidence(self) -> "TemporalPairWindow":
        """Reject additive or duplicated pair rows inside one event window."""
        if self.window_end <= self.window_start:
            raise ValueError("event-time window must have positive duration")
        identities = {(pair.left_artist_id, pair.right_artist_id) for pair in self.pairs}
        if len(identities) != len(self.pairs):
            raise ValueError("event-time window pairs must be unique")
        if any(pair.supporting_windows != 1 for pair in self.pairs):
            raise ValueError("each event-time pair must describe exactly one window")
        return self


class GraphValidationSettings(FrozenModel):
    """Declare deterministic experiment parameters."""

    revision: Literal["public-graph-validation-v1"] = "public-graph-validation-v1"
    neighbors_per_genre: int = Field(default=10, ge=2, le=50)
    community_seeds: tuple[int, ...] = Field(
        default=(20260830, 20260831, 20260832), min_length=1, max_length=8
    )
    maximum_community_iterations: int = Field(default=100, gt=0, le=1_000)
    maximum_validation_genres: int = Field(default=2_000, gt=0, le=2_000)

    @model_validator(mode="after")
    def require_unique_seeds(self) -> "GraphValidationSettings":
        """Reject duplicate experiments."""
        if len(self.community_seeds) != len(set(self.community_seeds)):
            raise ValueError("community seeds must be unique")
        return self


class GraphValidationInput(FrozenModel):
    """Bundle the bounded evidence accepted by graph validation."""

    base_inputs: PublicModelInput
    source_artifacts: tuple[PublicArtifact, ...] = Field(min_length=7, max_length=14)
    event_windows: tuple[TemporalPairWindow, ...] = Field(min_length=7, max_length=14)
    corpus_run: ArtistCoListenRunProjection
    hierarchy: tuple[GenreHierarchyEdge, ...] = Field(max_length=100_000)
    input_database_bytes: int = Field(ge=0)
    input_artifact_bytes: int = Field(ge=0)

    @model_validator(mode="after")
    def require_joint_disjoint_corpus(self) -> "GraphValidationInput":
        """Reject publication-batch counts and ambiguous temporal windows."""
        if any(artifact.source != "listenbrainz" for artifact in self.source_artifacts):
            raise ValueError("joint corpus artifacts must all be ListenBrainz sources")
        snapshots = tuple(artifact.snapshot for artifact in self.source_artifacts)
        hashes = tuple(artifact.content_sha256 for artifact in self.source_artifacts)
        if len(snapshots) != len(set(snapshots)) or len(hashes) != len(set(hashes)):
            raise ValueError("joint corpus snapshots and hashes must be unique")
        for left, right in zip(self.event_windows, self.event_windows[1:], strict=False):
            if left.window_end != right.window_start:
                raise ValueError("event-time windows must be ordered, disjoint, and contiguous")
        if self.corpus_run.minimum_distinct_users < _MINIMUM_TEMPORAL_PRIVACY_FLOOR:
            raise ValueError("temporal corpus requires a privacy floor of at least five users")
        if any(
            pair.listener_day_support < self.corpus_run.minimum_distinct_users
            for window in self.event_windows
            for pair in window.pairs
        ):
            raise ValueError("event-time pair falls below the corpus privacy floor")
        if any(
            window.window_end - window.window_start != self.corpus_run.window_seconds
            for window in self.event_windows
        ):
            raise ValueError("event-time windows must match the corpus window size")
        return self


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
    mutual_neighbor_fraction: FiniteFloat = Field(ge=0.0, le=1.0)
    hierarchy_edges_evaluated: int = Field(ge=0)
    hierarchy_recall_at_k: FiniteFloat = Field(ge=0.0, le=1.0)


class TemporalValidation(FrozenModel):
    """Compare cumulative train, validation, and test graph artifacts."""

    left_window_end: int = Field(gt=0)
    right_window_end: int = Field(gt=0)
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
    input_artifact_bytes: int = Field(ge=0)


class GraphValidationArtifact(FrozenModel):
    """Publish a deterministic, content-addressed graph validation report."""

    revision: Literal["public-graph-validation-v1"] = "public-graph-validation-v1"
    input_sha256: Sha256
    settings_sha256: Sha256
    output_sha256: Sha256
    export_allowed: bool
    source_artifacts: tuple[PublicArtifact, ...] = Field(min_length=7, max_length=14)
    event_windows: int = Field(ge=7, le=14)
    corpus_run: ArtistCoListenRunProjection
    hierarchy_edges: int = Field(ge=0)
    communities: tuple[CommunityExperiment, ...] = Field(min_length=1, max_length=8)
    community_stability: CommunityStability
    neighborhood: NeighborhoodValidation
    temporal: tuple[TemporalValidation, ...] = Field(min_length=2, max_length=3)
    source_holdout: SourceHoldoutValidation
    deterministic_rerun: bool
    model_output_sha256: Sha256
    resources: ValidationResources
