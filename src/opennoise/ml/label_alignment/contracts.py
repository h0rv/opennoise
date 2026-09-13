"""Stable contracts for the conservative cold-label alignment checkpoint."""

from __future__ import annotations

from typing import Final, Literal

from pydantic import Field, model_validator

from opennoise.models import FrozenModel

_SHA: Final = r"^[0-9a-f]{64}$"

type SeedDisposition = Literal[
    "reconciled",
    "public_only",
    "musicbrainz_only",
    "review_only",
    "ambiguous",
    "unresolved",
]
type CandidateStatus = Literal["accepted", "review"]
type DecisionKind = Literal[
    "existing_open_identity",
    "unique_normalized_label",
    "compositional",
    "acronym_initialism",
]
type AbstentionReason = Literal[
    "generic_root_prohibited",
    "no_open_label_candidate",
    "ambiguous_or_weak_composition",
]


class ColdLabelAlignmentSettings(FrozenModel):
    """Fixed, explainable thresholds for a laptop-safe alignment run."""

    revision: Literal["cold-label-alignment-settings-v1"] = "cold-label-alignment-settings-v1"
    split_seed: int = Field(default=20260913, ge=0)
    masked_evaluation_fraction: float = Field(default=0.2, gt=0.0, lt=0.5)
    candidates_per_seed: int = Field(default=5, ge=1, le=20)
    minimum_review_score: float = Field(default=0.68, ge=0.0, le=1.0)
    minimum_review_token_jaccard: float = Field(default=0.34, ge=0.0, le=1.0)
    minimum_review_character_cosine: float = Field(default=0.42, ge=0.0, le=1.0)


class InputBinding(FrozenModel):
    """One byte-bound input consumed by a construction-only run."""

    role: str = Field(min_length=1)
    byte_sha256: str = Field(pattern=_SHA)
    byte_count: int = Field(gt=0)
    logical_sha256: str | None = Field(default=None, pattern=_SHA)


class OpenIdentityReference(FrozenModel):
    """One source identity represented by a normalized open-label cluster."""

    namespace: Literal["musicbrainz_genre_id", "musicbrainz_tag_name", "wikidata_genre_qid"]
    identifier: str = Field(min_length=1, max_length=500)
    label: str = Field(min_length=1, max_length=500)
    open_artist_count: int = Field(ge=0)
    open_claim_count: int = Field(ge=0)


class LabelAlignmentCandidate(FrozenModel):
    """A transparent proposed mapping, never a promoted graph identity."""

    source_item_id: str = Field(min_length=1, max_length=200)
    seed_name: str = Field(min_length=1, max_length=500)
    reconciliation_disposition: SeedDisposition
    candidate_normalized_label: str = Field(min_length=1, max_length=500)
    candidate_label: str = Field(min_length=1, max_length=500)
    identities: tuple[OpenIdentityReference, ...] = Field(min_length=1, max_length=16)
    decision_kind: DecisionKind
    score: float = Field(ge=0.0, le=1.0)
    token_jaccard: float = Field(ge=0.0, le=1.0)
    character_ngram_cosine: float = Field(ge=0.0, le=1.0)
    head_modifier_score: float = Field(ge=0.0, le=1.0)
    open_graph_context_score: float = Field(ge=0.0, le=1.0)
    evidence_signals: tuple[str, ...] = Field(min_length=1, max_length=8)
    status: CandidateStatus


class LabelAlignmentAbstention(FrozenModel):
    """One seed deliberately left unlinked rather than fuzzily forced."""

    source_item_id: str = Field(min_length=1, max_length=200)
    seed_name: str = Field(min_length=1, max_length=500)
    reconciliation_disposition: SeedDisposition
    reason: AbstentionReason
    best_score: float | None = Field(default=None, ge=0.0, le=1.0)


class MaskedEvaluation(FrozenModel):
    """Deterministic identity recovery after hiding trusted reconciliation edges."""

    eligible_high_confidence_seed_count: int = Field(ge=0)
    masked_seed_count: int = Field(ge=0)
    retrievable_seed_count: int = Field(ge=0)
    top_1_recall: float | None = Field(default=None, ge=0.0, le=1.0)
    top_k_recall: float | None = Field(default=None, ge=0.0, le=1.0)
    accepted_prediction_count: int = Field(ge=0)
    accepted_precision: float | None = Field(default=None, ge=0.0, le=1.0)
    review_prediction_count: int = Field(ge=0)
    review_precision: float | None = Field(default=None, ge=0.0, le=1.0)
    acronym_review_prediction_count: int = Field(ge=0)
    acronym_review_precision: float | None = Field(default=None, ge=0.0, le=1.0)
    heldout_identity_edges_excluded_from_decision: Literal[True] = True


class DispositionCoverage(FrozenModel):
    """Retain the six reconciliation states rather than silently collapsing them."""

    reconciled: int = Field(ge=0)
    public_only: int = Field(ge=0)
    musicbrainz_only: int = Field(ge=0)
    review_only: int = Field(ge=0)
    ambiguous: int = Field(ge=0)
    unresolved: int = Field(ge=0)

    @property
    def seed_count(self) -> int:
        """Return the complete reconciliation universe size."""
        return sum(self.model_dump().values())


class ColdLabelAlignmentCoverage(FrozenModel):
    """Complete seed-level accounting with known and proposed links kept separate."""

    seed_count: int = Field(ge=1)
    reconciliation: DispositionCoverage
    open_identity_count: int = Field(ge=0)
    projected_open_identity_count: int = Field(ge=0)
    supplemental_open_identity_count: Literal[0] = 0
    open_label_cluster_count: int = Field(ge=0)
    existing_open_identity_accepted_seed_count: int = Field(ge=0)
    inferred_unique_normalized_accepted_seed_count: int = Field(ge=0)
    compositional_review_seed_count: int = Field(ge=0)
    abstained_seed_count: int = Field(ge=0)
    generic_root_abstention_count: int = Field(ge=0)
    historical_inputs_read: Literal[False] = False
    identities_promoted: Literal[False] = False
    memberships_created: Literal[False] = False

    @model_validator(mode="after")
    def _all_seeds_accounted(self) -> ColdLabelAlignmentCoverage:
        if self.reconciliation.seed_count != self.seed_count:
            raise ValueError("reconciliation disposition totals must equal seed count")
        if (
            self.existing_open_identity_accepted_seed_count
            + self.inferred_unique_normalized_accepted_seed_count
            + self.compositional_review_seed_count
            + self.abstained_seed_count
            != self.seed_count
        ):
            raise ValueError("accepted, review, and abstention states must cover every seed")
        return self


class ColdLabelAlignmentArtifact(FrozenModel):
    """Sealed construction-only label alignment checkpoint."""

    revision: Literal["cold-label-alignment-v1"] = "cold-label-alignment-v1"
    inputs: tuple[InputBinding, ...] = Field(min_length=3, max_length=3)
    seed_identity_sha256: str = Field(pattern=_SHA)
    settings: ColdLabelAlignmentSettings
    settings_sha256: str = Field(pattern=_SHA)
    input_sha256: str = Field(pattern=_SHA)
    vocabulary_sha256: str = Field(pattern=_SHA)
    accepted: tuple[LabelAlignmentCandidate, ...]
    review: tuple[LabelAlignmentCandidate, ...]
    abstentions: tuple[LabelAlignmentAbstention, ...]
    masked_evaluation: MaskedEvaluation
    coverage: ColdLabelAlignmentCoverage
    historical_inputs_read: Literal[False] = False
    output_sha256: str = Field(pattern=_SHA)

    @model_validator(mode="after")
    def _complete(self) -> ColdLabelAlignmentArtifact:
        accepted_ids = {candidate.source_item_id for candidate in self.accepted}
        review_ids = {candidate.source_item_id for candidate in self.review}
        abstained_ids = {abstention.source_item_id for abstention in self.abstentions}
        if accepted_ids & review_ids or accepted_ids & abstained_ids or review_ids & abstained_ids:
            raise ValueError("a seed cannot appear in more than one alignment partition")
        if len(accepted_ids) != len(self.accepted):
            raise ValueError("accepted output must contain at most one candidate per seed")
        if len(accepted_ids) != (
            self.coverage.existing_open_identity_accepted_seed_count
            + self.coverage.inferred_unique_normalized_accepted_seed_count
        ):
            raise ValueError("accepted count does not match coverage")
        if len(review_ids) != self.coverage.compositional_review_seed_count:
            raise ValueError("review seed count does not match coverage")
        if len(abstained_ids) != self.coverage.abstained_seed_count:
            raise ValueError("abstention count does not match coverage")
        return self


class ColdLabelAlignmentReceipt(FrozenModel):
    """Content-addressed receipt for the construction-only artifact."""

    revision: Literal["cold-label-alignment-receipt-v1"] = "cold-label-alignment-receipt-v1"
    artifact_sha256: str = Field(pattern=_SHA)
    artifact_byte_count: int = Field(gt=0)
    logical_output_sha256: str = Field(pattern=_SHA)
    object_key: str = Field(min_length=1)
    historical_inputs_used_for_construction: Literal[False] = False
