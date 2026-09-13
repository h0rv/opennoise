"""Contracts for the bounded, source-neutral co-listen genre neighborhood signal."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal

from pydantic import Field, model_validator

from opennoise.common import canonical_json, sha256_hex
from opennoise.models import FrozenModel

REVISION: Final = "genre-colisten-neighborhoods-v1"
SEED_COUNT: Final = 6_291
SHA256: Final = r"^[0-9a-f]{64}$"
Channel = Literal["artist_direct", "reviewed_alias_context"]


class GenreNeighborhoodError(ValueError):
    """Raised when a sealed input, bound cache, or query is invalid."""


class GenreNeighborhoodSettings(FrozenModel):
    """Predeclared, deliberately small construction controls."""

    revision: Literal["genre-colisten-neighborhood-settings-v1"] = (
        "genre-colisten-neighborhood-settings-v1"
    )
    split_seed: int = Field(default=20260913, ge=0)
    heldout_fraction: float = Field(default=0.2, gt=0, lt=0.5)
    top_k: int = Field(default=50, ge=1, le=200)
    minimum_window_support: int = Field(default=2, ge=1, le=1000)
    minimum_raw_mass: float = Field(default=0.05, gt=0)
    shrinkage_prior_mass: float = Field(default=3.0, gt=0)


class InputBinding(FrozenModel):
    """Exact byte and logical binding for a sealed model input."""

    role: str
    byte_sha256: str = Field(pattern=SHA256)
    byte_count: int = Field(gt=0)
    logical_sha256: str = Field(pattern=SHA256)


class GenreNeighborhoodInputs(FrozenModel):
    """Explicit paths to the two only construction sources and durable output."""

    graph_database: Path
    graph_receipt: Path
    colisten_database: Path
    colisten_receipt: Path
    cache_directory: Path


@dataclass(frozen=True, slots=True)
class CertifiedInputs:
    """Inputs issued only after receipts, bytes, logical IDs, and schemas bind."""

    bindings: tuple[InputBinding, InputBinding, InputBinding, InputBinding]
    graph_logical_sha256: str
    colisten_logical_sha256: str


class SplitCoverage(FrozenModel):
    """Canonical artist-pair split accounting; windows never cross partitions."""

    canonical_artist_pair_count: int = Field(ge=0)
    training_artist_pair_count: int = Field(ge=0)
    heldout_artist_pair_count: int = Field(ge=0)
    training_window_count: int = Field(ge=0)
    heldout_window_count: int = Field(ge=0)

    @model_validator(mode="after")
    def _complete(self) -> SplitCoverage:
        if (
            self.training_artist_pair_count + self.heldout_artist_pair_count
            != self.canonical_artist_pair_count
        ):
            raise ValueError("artist-pair split is incomplete")
        return self


class ChannelCoverage(FrozenModel):
    """Membership and positive-only evaluation accounting per evidence channel."""

    channel: Channel
    membership_count: int = Field(ge=0)
    membership_artist_count: int = Field(ge=0)
    observed_seed_count: int = Field(ge=0, le=SEED_COUNT)
    training_positive_count: int = Field(ge=0)
    retained_neighbor_count: int = Field(ge=0)
    heldout_positive_count: int = Field(ge=0)
    heldout_scoreable_positive_count: int = Field(ge=0)
    heldout_recovered_at_k_count: int = Field(ge=0)
    heldout_overlap_coverage: float | None = Field(default=None, ge=0, le=1)
    heldout_recovery_at_k: float | None = Field(default=None, ge=0, le=1)
    absence_is_negative: Literal[False] = False


class GenreNeighborhoodArtifact(FrozenModel):
    """Small logical artifact which binds a durable SQLite neighborhood cache."""

    revision: Literal["genre-colisten-neighborhoods-v1"] = REVISION
    inputs: tuple[InputBinding, ...] = Field(min_length=4, max_length=4)
    graph_receipt_output_sha256: str = Field(pattern=SHA256)
    colisten_receipt_output_sha256: str = Field(pattern=SHA256)
    settings: GenreNeighborhoodSettings
    settings_sha256: str = Field(pattern=SHA256)
    input_sha256: str = Field(pattern=SHA256)
    cache_database_sha256: str = Field(pattern=SHA256)
    cache_database_byte_count: int = Field(gt=0)
    stable_seed_count: Literal[6291] = SEED_COUNT
    colisten_artist_count: int = Field(ge=0)
    split: SplitCoverage
    channels: tuple[ChannelCoverage, ChannelCoverage]
    historical_inputs_read_for_construction: Literal[False] = False
    audio_read_for_construction: Literal[False] = False
    listener_identifiers_read_for_construction: Literal[False] = False
    output_sha256: str = Field(pattern=SHA256)

    @model_validator(mode="after")
    def _inputs_are_exact(self) -> GenreNeighborhoodArtifact:
        if tuple(item.role for item in self.inputs) != (
            "graph_database",
            "graph_receipt",
            "colisten_database",
            "colisten_receipt",
        ):
            raise ValueError(
                "artifact must bind graph and co-listen database/receipt inputs in stable order"
            )
        return self

    @model_validator(mode="after")
    def _channels_are_exact(self) -> GenreNeighborhoodArtifact:
        """Keep the two evidence channels present exactly once in stable order."""
        if tuple(item.channel for item in self.channels) != (
            "artist_direct",
            "reviewed_alias_context",
        ):
            raise ValueError("artifact must contain both evidence channels once in stable order")
        return self


class GenreNeighborhoodReceipt(FrozenModel):
    """Byte custody receipt for the logical output and durable cache."""

    artifact_sha256: str = Field(pattern=SHA256)
    artifact_byte_count: int = Field(gt=0)
    logical_output_sha256: str = Field(pattern=SHA256)
    cache_database_sha256: str = Field(pattern=SHA256)


def settings_sha256(settings: GenreNeighborhoodSettings) -> str:
    """Hash the complete validated settings payload."""
    return sha256_hex(canonical_json(settings.model_dump(mode="json")))


def artifact_sha256(artifact: GenreNeighborhoodArtifact) -> str:
    """Hash the logical artifact excluding its self-referential digest."""
    return sha256_hex(canonical_json(artifact.model_dump(mode="json", exclude={"output_sha256"})))


def verify_artifact(artifact: GenreNeighborhoodArtifact) -> None:
    """Fail closed unless settings and artifact logical digests replay."""
    if tuple(item.role for item in artifact.inputs) != (
        "graph_database",
        "graph_receipt",
        "colisten_database",
        "colisten_receipt",
    ):
        raise GenreNeighborhoodError("artifact input roles do not replay")
    if tuple(item.channel for item in artifact.channels) != (
        "artist_direct",
        "reviewed_alias_context",
    ):
        raise GenreNeighborhoodError("artifact channels do not replay")
    if artifact.settings_sha256 != settings_sha256(artifact.settings):
        raise GenreNeighborhoodError("settings hash does not replay")
    if artifact.output_sha256 != artifact_sha256(artifact):
        raise GenreNeighborhoodError("artifact hash does not replay")
