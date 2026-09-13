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
type OpenIdentityNamespace = Literal[
    "musicbrainz_genre_id",
    "musicbrainz_tag_name",
    "wikidata_genre_qid",
    "musicbrainz_release_group_genre_name",
    "musicbrainz_release_group_tag_name",
]
type DecisionKind = Literal[
    "existing_open_identity",
    "unique_normalized_label",
    "compositional",
    "acronym_initialism",
    "semantic_alias",
    "ambiguous_existing_identity",
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
    maximum_head_candidates: int = Field(default=250, ge=1, le=1_000)
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

    namespace: OpenIdentityNamespace
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
        return (
            self.reconciled
            + self.public_only
            + self.musicbrainz_only
            + self.review_only
            + self.ambiguous
            + self.unresolved
        )


class ColdLabelAlignmentCoverage(FrozenModel):
    """Complete seed-level accounting with known and proposed links kept separate."""

    seed_count: int = Field(ge=1)
    reconciliation: DispositionCoverage
    open_identity_count: int = Field(ge=0)
    projected_open_identity_count: int = Field(ge=0)
    supplemental_open_identity_count: int = Field(default=0, ge=0)
    open_label_cluster_count: int = Field(ge=0)
    existing_open_identity_accepted_seed_count: int = Field(ge=0)
    inferred_unique_normalized_accepted_seed_count: int = Field(ge=0)
    compositional_review_seed_count: int = Field(ge=0)
    acronym_initialism_review_seed_count: int = Field(ge=0)
    semantic_alias_review_seed_count: int = Field(ge=0)
    ambiguous_existing_identity_review_seed_count: int = Field(ge=0)
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
            + self.acronym_initialism_review_seed_count
            + self.semantic_alias_review_seed_count
            + self.ambiguous_existing_identity_review_seed_count
            + self.abstained_seed_count
            != self.seed_count
        ):
            raise ValueError("accepted, review, and abstention states must cover every seed")
        return self


class ColdLabelAlignmentArtifact(FrozenModel):
    """Sealed construction-only label alignment checkpoint."""

    revision: Literal["cold-label-alignment-v1"] = "cold-label-alignment-v1"
    inputs: tuple[InputBinding, ...] = Field(min_length=3, max_length=5)
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
    def _complete(  # noqa: C901, PLR0912 - receipt invariants are atomic.
        self,
    ) -> ColdLabelAlignmentArtifact:
        roles = {binding.role for binding in self.inputs}
        required_roles = {
            "source_neutral_evidence_graph_database",
            "source_neutral_evidence_graph_receipt",
            "seed_reconciliation",
        }
        supplemental_roles = {
            "musicbrainz_release_group_vocabulary_artifact",
            "musicbrainz_release_group_vocabulary_receipt",
        }
        if not required_roles <= roles:
            raise ValueError("base construction input roles are incomplete")
        if roles & supplemental_roles and not supplemental_roles <= roles:
            raise ValueError("supplemental vocabulary requires both archive and receipt bindings")
        if len(roles) != len(self.inputs):
            raise ValueError("construction input roles must be unique")
        if roles != required_roles and roles != required_roles | supplemental_roles:
            raise ValueError("construction input roles must be an exact supported role set")
        accepted_ids = {candidate.source_item_id for candidate in self.accepted}
        review_ids = {candidate.source_item_id for candidate in self.review}
        abstained_ids = {abstention.source_item_id for abstention in self.abstentions}
        if accepted_ids & review_ids or accepted_ids & abstained_ids or review_ids & abstained_ids:
            raise ValueError("a seed cannot appear in more than one alignment partition")
        if len(accepted_ids) != len(self.accepted):
            raise ValueError("accepted output must contain at most one candidate per seed")
        review_pairs = {
            (candidate.source_item_id, candidate.candidate_normalized_label)
            for candidate in self.review
        }
        if len(review_pairs) != len(self.review):
            raise ValueError("review output must not repeat a seed and candidate label cluster")
        if any(
            candidate.decision_kind not in {"existing_open_identity", "unique_normalized_label"}
            for candidate in self.accepted
        ):
            raise ValueError("accepted decisions must be existing or uniquely normalized")
        if sum(
            candidate.decision_kind == "existing_open_identity" for candidate in self.accepted
        ) != (self.coverage.existing_open_identity_accepted_seed_count):
            raise ValueError("existing accepted count does not match coverage")
        if sum(
            candidate.decision_kind == "unique_normalized_label" for candidate in self.accepted
        ) != (self.coverage.inferred_unique_normalized_accepted_seed_count):
            raise ValueError("inferred accepted count does not match coverage")
        review_kinds = {
            source_item_id: {
                candidate.decision_kind
                for candidate in self.review
                if candidate.source_item_id == source_item_id
            }
            for source_item_id in review_ids
        }
        if any(len(kinds) != 1 for kinds in review_kinds.values()):
            raise ValueError("each review seed must have one decision kind")
        if sum(kinds == {"compositional"} for kinds in review_kinds.values()) != (
            self.coverage.compositional_review_seed_count
        ):
            raise ValueError("compositional review count does not match coverage")
        if sum(kinds == {"acronym_initialism"} for kinds in review_kinds.values()) != (
            self.coverage.acronym_initialism_review_seed_count
        ):
            raise ValueError("acronym review count does not match coverage")
        if sum(kinds == {"semantic_alias"} for kinds in review_kinds.values()) != (
            self.coverage.semantic_alias_review_seed_count
        ):
            raise ValueError("semantic alias review count does not match coverage")
        if sum(kinds == {"ambiguous_existing_identity"} for kinds in review_kinds.values()) != (
            self.coverage.ambiguous_existing_identity_review_seed_count
        ):
            raise ValueError("ambiguous existing-identity review count does not match coverage")
        if len(abstained_ids) != self.coverage.abstained_seed_count:
            raise ValueError("abstention count does not match coverage")
        if (
            sum(abstention.reason == "generic_root_prohibited" for abstention in self.abstentions)
            != self.coverage.generic_root_abstention_count
        ):
            raise ValueError("generic-root abstention count does not match coverage")
        identity_rows = [*self.accepted, *self.review, *self.abstentions]
        if any(
            len(
                {
                    (row.seed_name, row.reconciliation_disposition)
                    for row in identity_rows
                    if row.source_item_id == source_item_id
                }
            )
            != 1
            for source_item_id in accepted_ids | review_ids | abstained_ids
        ):
            raise ValueError("a seed must not carry contradictory name or disposition rows")
        if len(accepted_ids | review_ids | abstained_ids) != self.coverage.seed_count:
            raise ValueError("alignment partitions must contain every seed exactly once")
        return self


class ColdLabelAlignmentReceipt(FrozenModel):
    """Content-addressed receipt for the construction-only artifact."""

    revision: Literal["cold-label-alignment-receipt-v1"] = "cold-label-alignment-receipt-v1"
    artifact_sha256: str = Field(pattern=_SHA)
    artifact_byte_count: int = Field(gt=0)
    logical_output_sha256: str = Field(pattern=_SHA)
    object_key: str = Field(min_length=1)
    historical_inputs_used_for_construction: Literal[False] = False
