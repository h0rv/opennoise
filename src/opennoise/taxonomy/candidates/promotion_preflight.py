"""Fail-closed local preflight for source-bound generated genre candidates.

This module deliberately evaluates *readiness for a later publication
assessment*.  It never creates a genre identity, changes a source claim, or
authorizes a public export.  In particular, a review approval does not carry
source redistribution or display permission with it.
"""

from __future__ import annotations

from collections import Counter
from typing import Final, Literal

from pydantic import Field, model_validator

from opennoise.common import sha256_json
from opennoise.models import FrozenModel
from opennoise.taxonomy.candidates.audit import (
    GenreCandidateTriageAudit,
    TriageReason,
    verify_genre_candidate_triage_audit,
)
from opennoise.taxonomy.candidates.workflow import (
    GenreCandidateReviewArtifact,
    verify_genre_candidate_review_artifact,
)
from opennoise.types import Sha256  # noqa: TC001  # Pydantic resolves aliases at runtime.

_REVISION: Final = "genre-candidate-promotion-preflight-v1"
_POLICY_REVISION: Final = "genre-candidate-promotion-preflight-policy-v1"

type PromotionPreflightState = Literal[
    "awaiting_independent_review",
    "blocked_by_triage",
    "awaiting_source_publication_authorization",
]

_BLOCKING_TRIAGE_REASONS: Final = frozenset(
    {"lexical_only_evidence", "repeated_proposed_label", "competing_candidate_for_seed"}
)


class GenreCandidatePromotionPreflightPolicy(FrozenModel):
    """Versioned limits for an intentionally local, non-authorizing screen."""

    revision: Literal["genre-candidate-promotion-preflight-policy-v1"] = _POLICY_REVISION
    maximum_candidates: int = Field(default=10_000, ge=1, le=50_000)


class GenreCandidatePromotionPreflightRow(FrozenModel):
    """One candidate's conservative state before a separate publication decision."""

    candidate_id: str = Field(pattern=r"^candidate:[A-Za-z0-9._:-]{1,240}$")
    state: PromotionPreflightState
    blocking_triage_reasons: tuple[TriageReason, ...] = ()

    @model_validator(mode="after")
    def _state_matches_reasons(self) -> GenreCandidatePromotionPreflightRow:
        blocked = bool(set(self.blocking_triage_reasons) & _BLOCKING_TRIAGE_REASONS)
        if self.state == "blocked_by_triage" and not blocked:
            raise ValueError("triage-blocked candidate must name a blocking triage reason")
        if self.state == "awaiting_source_publication_authorization" and (
            self.blocking_triage_reasons
        ):
            raise ValueError("authorization-ready candidates may not name blocking reasons")
        if len(self.blocking_triage_reasons) != len(set(self.blocking_triage_reasons)):
            raise ValueError("blocking triage reasons must be unique")
        return self


class GenreCandidatePromotionPreflightCoverage(FrozenModel):
    """A complete accounting that cannot be mistaken for publication coverage."""

    candidate_count: int = Field(ge=0)
    awaiting_independent_review_count: int = Field(ge=0)
    blocked_by_triage_count: int = Field(ge=0)
    awaiting_source_publication_authorization_count: int = Field(ge=0)
    triage_blocked_count: int = Field(ge=0)
    public_genres_authorized_count: Literal[0] = 0

    @model_validator(mode="after")
    def _partition(self) -> GenreCandidatePromotionPreflightCoverage:
        if self.candidate_count != (
            self.awaiting_independent_review_count
            + self.blocked_by_triage_count
            + self.awaiting_source_publication_authorization_count
        ):
            raise ValueError("preflight states must partition candidates")
        return self


class GenreCandidatePromotionPreflight(FrozenModel):
    """A hash-bound local assessment, expressly without public authorization."""

    revision: Literal["genre-candidate-promotion-preflight-v1"] = _REVISION
    policy: GenreCandidatePromotionPreflightPolicy
    policy_sha256: Sha256
    review_artifact_output_sha256: Sha256
    triage_audit_output_sha256: Sha256
    source_candidate_artifact_sha256: Sha256
    source_claims_sha256: Sha256
    rows: tuple[GenreCandidatePromotionPreflightRow, ...]
    coverage: GenreCandidatePromotionPreflightCoverage
    source_claims_mutated: Literal[False] = False
    generated_genres_published: Literal[False] = False
    catalog_mutated: Literal[False] = False
    public_export_authorized: Literal[False] = False
    output_sha256: Sha256

    @model_validator(mode="after")
    def _complete(self) -> GenreCandidatePromotionPreflight:
        row_ids = tuple(row.candidate_id for row in self.rows)
        if len(row_ids) != len(set(row_ids)):
            raise ValueError("preflight rows must cover a candidate only once")
        if len(self.rows) != self.coverage.candidate_count:
            raise ValueError("preflight row count does not match coverage")
        if self.policy_sha256 != sha256_json(self.policy.model_dump(mode="json")):
            raise ValueError("promotion preflight policy hash does not replay")
        return self


def genre_candidate_promotion_preflight_sha256(
    preflight: GenreCandidatePromotionPreflight,
) -> Sha256:
    """Return the canonical logical checksum excluding the self hash."""
    return sha256_json(preflight.model_dump(mode="json", exclude={"output_sha256"}))


def build_genre_candidate_promotion_preflight(
    review: GenreCandidateReviewArtifact,
    triage: GenreCandidateTriageAudit,
    policy: GenreCandidatePromotionPreflightPolicy | None = None,
) -> GenreCandidatePromotionPreflight:
    """Bind reviewed candidates to triage without granting publication rights."""
    verify_genre_candidate_review_artifact(review)
    verify_genre_candidate_triage_audit(triage)
    resolved = policy or GenreCandidatePromotionPreflightPolicy()
    if review.coverage.candidate_count > resolved.maximum_candidates:
        raise ValueError("candidate count exceeds promotion preflight policy bound")
    if triage.source_candidate_artifact_sha256 != review.source_candidate_artifact_sha256:
        raise ValueError("triage audit is bound to a different source candidate artifact")
    if triage.source_claims_sha256 != review.source_claims_sha256:
        raise ValueError("triage audit is bound to different immutable source claims")
    triage_by_id = {row.candidate_id: row for row in triage.triage_rows}
    review_by_id = {row.candidate_id: row for row in review.review_rows}
    if set(triage_by_id) != set(review_by_id):
        raise ValueError("triage and review artifacts must cover the same candidate IDs")

    rows = tuple(
        _preflight_row(
            candidate_id, review_by_id[candidate_id].state, triage_by_id[candidate_id].reasons
        )
        for candidate_id in sorted(review_by_id)
    )
    counts = Counter(row.state for row in rows)
    coverage = GenreCandidatePromotionPreflightCoverage(
        candidate_count=len(rows),
        awaiting_independent_review_count=counts["awaiting_independent_review"],
        blocked_by_triage_count=counts["blocked_by_triage"],
        awaiting_source_publication_authorization_count=counts[
            "awaiting_source_publication_authorization"
        ],
        triage_blocked_count=sum(bool(row.blocking_triage_reasons) for row in rows),
    )
    base = GenreCandidatePromotionPreflight(
        policy=resolved,
        policy_sha256=sha256_json(resolved.model_dump(mode="json")),
        review_artifact_output_sha256=review.output_sha256,
        triage_audit_output_sha256=triage.output_sha256,
        source_candidate_artifact_sha256=review.source_candidate_artifact_sha256,
        source_claims_sha256=review.source_claims_sha256,
        rows=rows,
        coverage=coverage,
        output_sha256="0" * 64,
    )
    return base.model_copy(
        update={"output_sha256": genre_candidate_promotion_preflight_sha256(base)}
    )


def _preflight_row(
    candidate_id: str,
    review_state: str,
    reasons: tuple[TriageReason, ...],
) -> GenreCandidatePromotionPreflightRow:
    """Resolve one conservative state; approval alone never authorizes export."""
    blocking_reasons = tuple(reason for reason in reasons if reason in _BLOCKING_TRIAGE_REASONS)
    if review_state != "ready_for_separate_publication":
        return GenreCandidatePromotionPreflightRow(
            candidate_id=candidate_id,
            state="awaiting_independent_review",
            blocking_triage_reasons=blocking_reasons,
        )
    if blocking_reasons:
        return GenreCandidatePromotionPreflightRow(
            candidate_id=candidate_id,
            state="blocked_by_triage",
            blocking_triage_reasons=blocking_reasons,
        )
    return GenreCandidatePromotionPreflightRow(
        candidate_id=candidate_id,
        state="awaiting_source_publication_authorization",
    )


def verify_genre_candidate_promotion_preflight(
    preflight: GenreCandidatePromotionPreflight,
) -> None:
    """Reject edits and any artifact that purports to authorize public output."""
    if preflight.output_sha256 != genre_candidate_promotion_preflight_sha256(preflight):
        raise ValueError("genre candidate promotion preflight output hash does not replay")
    if preflight.coverage.candidate_count > preflight.policy.maximum_candidates:
        raise ValueError("candidate count exceeds promotion preflight policy bound")
    if preflight.public_export_authorized or preflight.coverage.public_genres_authorized_count:
        raise ValueError("promotion preflight cannot authorize public genres")
