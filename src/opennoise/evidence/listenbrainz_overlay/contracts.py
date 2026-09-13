"""Typed contracts for receipt-bound, strictly separated ListenBrainz sidecars."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final, Literal

from pydantic import Field, model_validator

from opennoise.common import canonical_json, sha256_hex
from opennoise.models import FrozenModel

if TYPE_CHECKING:
    from pathlib import Path

_SHA256: Final = r"^[0-9a-f]{64}$"
_REVIEW_INPUT_ROLES: Final = frozenset(
    {
        "evidence_graph_database",
        "evidence_graph_receipt",
        "listenbrainz_propagation_artifact",
        "listenbrainz_propagation_receipt",
    }
)
_COLISTEN_INPUT_ROLES: Final = frozenset(
    {
        "evidence_graph_database",
        "evidence_graph_receipt",
        "qualified_listenbrainz_database",
    }
)
_CERTIFICATE: Final = object()


class ListenBrainzOverlayError(ValueError):
    """A source, sidecar, or bounded query violates the overlay contract."""


class SidecarInput(FrozenModel):
    """One exact byte-bound source with a portable, non-machine-specific locator."""

    role: str = Field(min_length=1)
    locator: str = Field(min_length=1)
    byte_sha256: str = Field(pattern=_SHA256)
    byte_count: int = Field(gt=0)
    logical_sha256: str = Field(pattern=_SHA256)


class PrivacyPolicy(FrozenModel):
    """The a-priori aggregate threshold applied before a co-listen row is retained."""

    revision: Literal["listenbrainz-overlay-privacy-v1"] = "listenbrainz-overlay-privacy-v1"
    minimum_distinct_user_count: int = Field(default=5, ge=1, le=10_000)
    raw_listens_read: Literal[False] = False
    listener_identifiers_read: Literal[False] = False
    audio_read: Literal[False] = False


class ReviewCandidateCoverage(FrozenModel):
    """Mutually exclusive dispositions for every sealed propagation candidate."""

    source_candidate_count: int = Field(ge=0)
    retained_candidate_count: int = Field(ge=0)
    abstained_artist_not_in_graph_count: int = Field(ge=0)
    rejected_stable_seed_not_in_graph_count: int = Field(ge=0)
    rejected_invalid_identifier_count: int = Field(ge=0)
    candidate_artist_count: int = Field(ge=0)
    candidate_seed_count: int = Field(ge=0, le=6_291)
    historical_input_used_for_construction: Literal[False] = False
    factual_memberships_written: Literal[False] = False

    @model_validator(mode="after")
    def fully_accounted(self) -> ReviewCandidateCoverage:
        """Require exactly one outcome for every sealed propagation candidate."""
        if self.source_candidate_count != (
            self.retained_candidate_count
            + self.abstained_artist_not_in_graph_count
            + self.rejected_stable_seed_not_in_graph_count
            + self.rejected_invalid_identifier_count
        ):
            raise ValueError("review candidate dispositions do not account for every input")
        return self


class CoListenCoverage(FrozenModel):
    """Mutually exclusive dispositions for every raw aggregate co-listen row."""

    source_row_count: int = Field(ge=0)
    retained_relation_count: int = Field(ge=0)
    abstained_endpoint_not_in_graph_count: int = Field(ge=0)
    rejected_below_privacy_threshold_count: int = Field(ge=0)
    rejected_noncanonical_endpoint_count: int = Field(ge=0)
    retained_artist_count: int = Field(ge=0)
    historical_input_used_for_construction: Literal[False] = False
    inferred_artist_similarity_written: Literal[False] = False

    @model_validator(mode="after")
    def fully_accounted(self) -> CoListenCoverage:
        """Require exactly one outcome for every qualified aggregate row."""
        if self.source_row_count != (
            self.retained_relation_count
            + self.abstained_endpoint_not_in_graph_count
            + self.rejected_below_privacy_threshold_count
            + self.rejected_noncanonical_endpoint_count
        ):
            raise ValueError("co-listen dispositions do not account for every input")
        return self


class DerivedReviewOverlayArtifact(FrozenModel):
    """Receipt for review-only artist-to-seed candidates; never a factual graph claim."""

    revision: Literal["listenbrainz-derived-review-overlay-v1"] = (
        "listenbrainz-derived-review-overlay-v1"
    )
    membership_semantics: Literal["derived_review_evidence_not_factual_membership"] = (
        "derived_review_evidence_not_factual_membership"
    )
    graph_receipt_output_sha256: str = Field(pattern=_SHA256)
    propagation_output_sha256: str = Field(pattern=_SHA256)
    inputs: tuple[SidecarInput, ...] = Field(min_length=4, max_length=4)
    database_sha256: str = Field(pattern=_SHA256)
    database_bytes: int = Field(gt=0)
    coverage: ReviewCandidateCoverage
    output_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def source_complete(self) -> DerivedReviewOverlayArtifact:
        """Require every source needed to replay review-only candidates."""
        if {item.role for item in self.inputs} != _REVIEW_INPUT_ROLES:
            raise ValueError("derived-review receipt must bind every required input")
        return self


class CoListenOverlayArtifact(FrozenModel):
    """Receipt for aggregate artist co-listens; it is not an artist-similarity model."""

    revision: Literal["listenbrainz-colisten-overlay-v1"] = "listenbrainz-colisten-overlay-v1"
    relation_semantics: Literal["privacy_thresholded_aggregate_colisten_not_similarity"] = (
        "privacy_thresholded_aggregate_colisten_not_similarity"
    )
    graph_receipt_output_sha256: str = Field(pattern=_SHA256)
    inputs: tuple[SidecarInput, ...] = Field(min_length=3, max_length=3)
    privacy: PrivacyPolicy
    database_sha256: str = Field(pattern=_SHA256)
    database_bytes: int = Field(gt=0)
    coverage: CoListenCoverage
    output_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def source_complete(self) -> CoListenOverlayArtifact:
        """Require every source needed to replay aggregate co-listen rows."""
        if {item.role for item in self.inputs} != _COLISTEN_INPUT_ROLES:
            raise ValueError("co-listen receipt must bind every required input")
        return self


@dataclass(frozen=True, slots=True)
class DerivedReviewOverlayInputs:
    """Sealed sources and an empty destination for a derived-review sidecar."""

    graph_database: Path
    graph_receipt: Path
    propagation_artifact: Path
    propagation_receipt: Path
    output_database: Path


@dataclass(frozen=True, slots=True)
class CoListenOverlayInputs:
    """Sealed graph and qualified aggregate source for a co-listen sidecar."""

    graph_database: Path
    graph_receipt: Path
    qualified_listenbrainz_database: Path
    expected_qualified_database_sha256: str
    output_database: Path
    privacy: PrivacyPolicy = field(default_factory=PrivacyPolicy)


@dataclass(frozen=True, slots=True)
class DerivedReviewOverlaySources:
    """Persisted derived-review sidecar and its independently verified receipt."""

    database: Path
    artifact: DerivedReviewOverlayArtifact


@dataclass(frozen=True, slots=True)
class CoListenOverlaySources:
    """Persisted aggregate co-listen sidecar and its independently verified receipt."""

    database: Path
    artifact: CoListenOverlayArtifact


@dataclass(frozen=True, slots=True)
class CertifiedDerivedReviewOverlaySources:
    """A source wrapper issued only after full startup verification."""

    sources: DerivedReviewOverlaySources
    _certificate: object = field(repr=False, compare=False)

    def is_valid(self) -> bool:
        """Return whether this wrapper was issued by the certification factory."""
        return self._certificate is _CERTIFICATE


@dataclass(frozen=True, slots=True)
class CertifiedCoListenOverlaySources:
    """A source wrapper issued only after full startup verification."""

    sources: CoListenOverlaySources
    _certificate: object = field(repr=False, compare=False)

    def is_valid(self) -> bool:
        """Return whether this wrapper was issued by the certification factory."""
        return self._certificate is _CERTIFICATE


def derived_review_overlay_sha256(artifact: DerivedReviewOverlayArtifact) -> str:
    """Return the canonical logical digest for a derived-review receipt."""
    return sha256_hex(canonical_json(artifact.model_dump(mode="json", exclude={"output_sha256"})))


def colisten_overlay_sha256(artifact: CoListenOverlayArtifact) -> str:
    """Return the canonical logical digest for a co-listen receipt."""
    return sha256_hex(canonical_json(artifact.model_dump(mode="json", exclude={"output_sha256"})))


def verify_derived_review_overlay(artifact: DerivedReviewOverlayArtifact) -> None:
    """Reject a derived-review receipt whose self-replay digest differs."""
    if derived_review_overlay_sha256(artifact) != artifact.output_sha256:
        raise ListenBrainzOverlayError("derived-review receipt hash does not replay")


def verify_colisten_overlay(artifact: CoListenOverlayArtifact) -> None:
    """Reject a co-listen receipt whose self-replay digest differs."""
    if colisten_overlay_sha256(artifact) != artifact.output_sha256:
        raise ListenBrainzOverlayError("co-listen receipt hash does not replay")
