"""Strict report types for the H2-calibrated reverse-engineering experiment."""

from pydantic import Field, FiniteFloat

from musix.models import FrozenModel
from musix.types import Sha256


class ReplicaGridResult(FrozenModel):
    """One interpretable train-only blend candidate."""

    artist_weight: FiniteFloat = Field(ge=0.0, le=1.0)
    maximum_artist_genre_degree: int = Field(ge=2, le=1_000)
    neighbors_per_genre: int = Field(ge=1, le=50)
    train_recall_at_k: FiniteFloat = Field(ge=0.0, le=1.0)


class CalibratedReplicaReport(FrozenModel):
    """A no-leak train/holdout report; never a production-model input."""

    revision: str = "calibrated-replica-v1"
    h2_artifact_sha256: Sha256
    h3_artifact_sha256: Sha256
    train_genre_count: int = Field(gt=0)
    holdout_genre_count: int = Field(gt=0)
    random_holdout_recall_at_k: FiniteFloat = Field(ge=0.0, le=1.0)
    grid: tuple[ReplicaGridResult, ...] = Field(min_length=1, max_length=100)
    selected: ReplicaGridResult
    holdout_recall_at_k: FiniteFloat = Field(ge=0.0, le=1.0)
    holdout_lift_over_artist_only: FiniteFloat
    embedding_options_not_selected: tuple[str, ...] = (
        "normalized_laplacian_spectral",
        "spectral_force_refined",
    )
    production_artifact_modified: bool = False
