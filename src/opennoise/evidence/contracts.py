"""Transparent evidence and ranking contracts for albums within genres."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field, FiniteFloat

from opennoise.models import FrozenModel


class DirectGenreEvidence(FrozenModel):
    """A source directly associated a release group with a genre."""

    evidence_kind: Literal["direct"] = "direct"
    supports_membership: Literal[True] = True
    evidence_ref: str = Field(min_length=1)
    provenance_id: int
    source_key: str
    observed_at: datetime
    source_genre_name: str
    source_count: int | None = Field(default=None, ge=0)
    source_total: int | None = Field(default=None, ge=0)


class InferredGenreEvidence(FrozenModel):
    """A versioned method inferred release group membership from other facts."""

    evidence_kind: Literal["inferred"] = "inferred"
    supports_membership: Literal[False] = False
    evidence_ref: str = Field(min_length=1)
    provenance_ids: tuple[int, ...]
    method_key: str = Field(min_length=1)
    method_version: str = Field(min_length=1)
    source_family: str = Field(min_length=1)
    observed_at: datetime
    listener_support: int | None = Field(default=None, ge=0)
    eligible_listener_count: int | None = Field(default=None, ge=0)
    territory: str | None = None
    window_start: datetime | None = None
    window_end: datetime | None = None


type AlbumGenreEvidence = Annotated[
    DirectGenreEvidence | InferredGenreEvidence,
    Field(discriminator="evidence_kind"),
]


class EditionSelection(FrozenModel):
    """A separately derived concrete edition selected for an album result."""

    release_id: int
    method_key: str = Field(min_length=1)
    method_version: str = Field(min_length=1)
    explanation: str = Field(min_length=1)
    evidence_refs: tuple[str, ...]


class RankingComponent(FrozenModel):
    """One named and reproducible contribution to a ranking score."""

    component_key: str = Field(min_length=1)
    raw_value: FiniteFloat | None
    transformed_value: FiniteFloat
    transform_key: str = Field(min_length=1)
    transform_version: str = Field(min_length=1)
    evidence_refs: tuple[str, ...]


class AlbumGenreRankingItem(FrozenModel):
    """One eligible release group in a versioned genre ranking output."""

    genre_id: int
    release_group_id: int
    rank: int = Field(gt=0)
    score: FiniteFloat
    membership_confidence: FiniteFloat = Field(ge=0.0, le=1.0)
    evidence_coverage: FiniteFloat = Field(ge=0.0, le=1.0)
    components: tuple[RankingComponent, ...]
    evidence: tuple[AlbumGenreEvidence, ...]
    explanation: str = Field(min_length=1)
    missing_features: tuple[str, ...]
    edition: EditionSelection | None = None


class AlbumGenreRankingArtifact(FrozenModel):
    """A complete derived ranking with explicit method and eligibility rules."""

    run_ref: str = Field(min_length=1)
    method_key: str = Field(min_length=1)
    method_version: str = Field(min_length=1)
    config_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    input_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    policy_id: int
    generated_at: datetime
    membership_threshold: FiniteFloat
    eligibility_rule: str = Field(min_length=1)
    items: tuple[AlbumGenreRankingItem, ...]
