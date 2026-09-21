"""A bounded, source-preserving review ledger for generated genre candidates.

This module deliberately stops before catalog or public-map publication.  A
candidate is an opaque ``candidate:`` identifier, never a genre identifier;
even a candidate with sufficient review approval needs a separate, versioned
publication decision in a downstream workflow.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Final, Literal

from pydantic import Field, model_validator

from opennoise.common import sha256_json
from opennoise.models import FrozenModel
from opennoise.types import Sha256  # noqa: TC001  # Pydantic resolves the alias at runtime.

_REVISION: Final = "genre-candidate-review-workflow-v1"
_POLICY_REVISION: Final = "genre-candidate-review-policy-v1"
_GATE_REVISION: Final = "genre-candidate-review-gate-v1"

type ReviewDisposition = Literal["approve", "reject", "needs_evidence"]
type CandidateReviewState = Literal[
    "pending_review",
    "needs_evidence",
    "rejected",
    "ready_for_separate_publication",
]


class SourceGenreClaim(FrozenModel):
    """An immutable source observation retained exactly as supplied by its adapter."""

    claim_id: str = Field(min_length=1, max_length=300)
    source_id: str = Field(min_length=1, max_length=120)
    source_record_id: str = Field(min_length=1, max_length=500)
    observed_label: str = Field(min_length=1, max_length=500)
    source_object_sha256: Sha256


class GenreCandidate(FrozenModel):
    """One generated label proposal supported by immutable source-claim IDs."""

    candidate_id: str = Field(pattern=r"^candidate:[A-Za-z0-9._:-]{1,240}$")
    proposed_label: str = Field(min_length=1, max_length=500)
    generator_revision: str = Field(min_length=1, max_length=120)
    source_claim_ids: tuple[str, ...] = Field(min_length=1, max_length=64)
    rationale: str = Field(min_length=1, max_length=2_000)

    @model_validator(mode="after")
    def _unique_claim_ids(self) -> GenreCandidate:
        if len(self.source_claim_ids) != len(set(self.source_claim_ids)):
            raise ValueError("candidate source claim IDs must be unique")
        return self


class GenreCandidateReviewDecision(FrozenModel):
    """One immutable human review event; it cannot alter a source claim."""

    decision_id: str = Field(min_length=1, max_length=300)
    candidate_id: str = Field(pattern=r"^candidate:[A-Za-z0-9._:-]{1,240}$")
    reviewer_ref: str = Field(min_length=1, max_length=300)
    review_revision: str = Field(min_length=1, max_length=120)
    disposition: ReviewDisposition
    rationale: str = Field(min_length=1, max_length=2_000)


class GenreCandidateWorkflowPolicy(FrozenModel):
    """Versioned bounds and independent-review threshold for one candidate batch."""

    revision: Literal["genre-candidate-review-policy-v1"] = _POLICY_REVISION
    maximum_source_claims: int = Field(default=50_000, ge=1, le=500_000)
    maximum_candidates: int = Field(default=10_000, ge=1, le=50_000)
    maximum_review_decisions: int = Field(default=30_000, ge=0, le=150_000)
    required_independent_approvals: int = Field(default=2, ge=1, le=10)
    required_rejections: int = Field(default=1, ge=1, le=10)


class GenreCandidateReviewRow(FrozenModel):
    """The derived state of one candidate, without assigning a public genre ID."""

    candidate_id: str = Field(pattern=r"^candidate:[A-Za-z0-9._:-]{1,240}$")
    state: CandidateReviewState
    approval_count: int = Field(default=0, ge=0)
    rejection_count: int = Field(default=0, ge=0)
    needs_evidence_count: int = Field(default=0, ge=0)


class GenreCandidateReviewCoverage(FrozenModel):
    """Complete bounded accounting for all candidates in a batch."""

    source_claim_count: int = Field(ge=1)
    candidate_count: int = Field(ge=0)
    review_decision_count: int = Field(ge=0)
    pending_review_count: int = Field(ge=0)
    needs_evidence_count: int = Field(ge=0)
    rejected_count: int = Field(ge=0)
    ready_for_separate_publication_count: int = Field(ge=0)

    @model_validator(mode="after")
    def _candidate_partition(self) -> GenreCandidateReviewCoverage:
        if self.candidate_count != (
            self.pending_review_count
            + self.needs_evidence_count
            + self.rejected_count
            + self.ready_for_separate_publication_count
        ):
            raise ValueError("candidate review states must partition candidates")
        return self


class GenreCandidateReviewArtifact(FrozenModel):
    """A sealed review ledger that expressly has no catalog/publication effect."""

    revision: Literal["genre-candidate-review-workflow-v1"] = _REVISION
    policy: GenreCandidateWorkflowPolicy
    policy_sha256: Sha256
    source_candidate_artifact_sha256: Sha256
    source_claims_sha256: Sha256
    candidates_sha256: Sha256
    review_decisions_sha256: Sha256
    source_claims: tuple[SourceGenreClaim, ...] = Field(min_length=1)
    candidates: tuple[GenreCandidate, ...]
    review_decisions: tuple[GenreCandidateReviewDecision, ...]
    review_rows: tuple[GenreCandidateReviewRow, ...]
    coverage: GenreCandidateReviewCoverage
    source_claims_mutated: Literal[False] = False
    generated_genres_published: Literal[False] = False
    catalog_mutated: Literal[False] = False
    output_sha256: Sha256

    @model_validator(mode="after")
    def _hashes_and_complete_coverage(self) -> GenreCandidateReviewArtifact:
        if self.policy_sha256 != sha256_json(self.policy.model_dump(mode="json")):
            raise ValueError("candidate workflow policy hash does not replay")
        if self.source_claims_sha256 != sha256_json(
            [item.model_dump(mode="json") for item in self.source_claims]
        ):
            raise ValueError("source claim hash does not replay")
        if self.candidates_sha256 != sha256_json(
            [item.model_dump(mode="json") for item in self.candidates]
        ):
            raise ValueError("candidate hash does not replay")
        if self.review_decisions_sha256 != sha256_json(
            [item.model_dump(mode="json") for item in self.review_decisions]
        ):
            raise ValueError("review decision hash does not replay")
        candidate_ids = tuple(item.candidate_id for item in self.candidates)
        row_ids = tuple(item.candidate_id for item in self.review_rows)
        if len(candidate_ids) != len(set(candidate_ids)):
            raise ValueError("candidate IDs must be unique")
        if set(row_ids) != set(candidate_ids) or len(row_ids) != len(set(row_ids)):
            raise ValueError("review rows must cover every candidate exactly once")
        if len(self.source_claims) != self.coverage.source_claim_count:
            raise ValueError("source claim count does not match coverage")
        if len(self.candidates) != self.coverage.candidate_count:
            raise ValueError("candidate count does not match coverage")
        if len(self.review_decisions) != self.coverage.review_decision_count:
            raise ValueError("review decision count does not match coverage")
        return self


class GenreCandidateReviewGate(FrozenModel):
    """Verification result for a review artifact, never a publication authorization."""

    revision: Literal["genre-candidate-review-gate-v1"] = _GATE_REVISION
    artifact_output_sha256: Sha256
    candidate_count: int = Field(ge=0)
    deterministic_replay: Literal[True] = True
    source_claims_immutable: Literal[True] = True
    generated_genres_not_published: Literal[True] = True
    catalog_not_mutated: Literal[True] = True
    approved_candidates_require_separate_publication: Literal[True] = True


def _review_state(
    decisions: tuple[GenreCandidateReviewDecision, ...], policy: GenreCandidateWorkflowPolicy
) -> GenreCandidateReviewRow:
    """Resolve a fail-closed state from the immutable decisions for one candidate."""
    counts = Counter(item.disposition for item in decisions)
    if counts["reject"] >= policy.required_rejections:
        state: CandidateReviewState = "rejected"
    elif counts["approve"] >= policy.required_independent_approvals:
        state = "ready_for_separate_publication"
    elif counts["needs_evidence"]:
        state = "needs_evidence"
    else:
        state = "pending_review"
    return GenreCandidateReviewRow(
        candidate_id=decisions[0].candidate_id,
        state=state,
        approval_count=counts["approve"],
        rejection_count=counts["reject"],
        needs_evidence_count=counts["needs_evidence"],
    )


def genre_candidate_review_output_sha256(artifact: GenreCandidateReviewArtifact) -> Sha256:
    """Recompute a sealed artifact's logical content hash."""
    return sha256_json(artifact.model_dump(mode="json", exclude={"output_sha256"}))


def _validate_batch_bounds(
    source_claims: tuple[SourceGenreClaim, ...],
    candidates: tuple[GenreCandidate, ...],
    review_decisions: tuple[GenreCandidateReviewDecision, ...],
    policy: GenreCandidateWorkflowPolicy,
) -> None:
    """Reject input collections that exceed the explicitly declared batch bounds."""
    if len(source_claims) > policy.maximum_source_claims:
        raise ValueError("source claim count exceeds workflow policy bound")
    if len(candidates) > policy.maximum_candidates:
        raise ValueError("candidate count exceeds workflow policy bound")
    if len(review_decisions) > policy.maximum_review_decisions:
        raise ValueError("review decision count exceeds workflow policy bound")


def _validate_claims_and_candidates(
    source_claims: tuple[SourceGenreClaim, ...], candidates: tuple[GenreCandidate, ...]
) -> set[str]:
    """Require unique immutable claims and candidate evidence that names only those claims."""
    claim_ids = tuple(item.claim_id for item in source_claims)
    if len(claim_ids) != len(set(claim_ids)):
        raise ValueError("source claim IDs must be unique")
    candidate_ids = tuple(item.candidate_id for item in candidates)
    if len(candidate_ids) != len(set(candidate_ids)):
        raise ValueError("candidate IDs must be unique")
    known_claim_ids = set(claim_ids)
    for candidate in candidates:
        if set(candidate.source_claim_ids) - known_claim_ids:
            raise ValueError("candidate references an unknown source claim")
    return set(candidate_ids)


def _validated_grouped_decisions(
    source_claims: tuple[SourceGenreClaim, ...],
    candidates: tuple[GenreCandidate, ...],
    review_decisions: tuple[GenreCandidateReviewDecision, ...],
    policy: GenreCandidateWorkflowPolicy,
) -> dict[str, list[GenreCandidateReviewDecision]]:
    """Check bounded immutable inputs and group their one-per-reviewer decisions."""
    _validate_batch_bounds(source_claims, candidates, review_decisions, policy)
    known_candidate_ids = _validate_claims_and_candidates(source_claims, candidates)
    grouped: dict[str, list[GenreCandidateReviewDecision]] = defaultdict(list)
    reviewer_candidate_pairs: set[tuple[str, str]] = set()
    decision_ids: set[str] = set()
    for decision in review_decisions:
        if decision.candidate_id not in known_candidate_ids:
            raise ValueError("review decision references an unknown candidate")
        if decision.decision_id in decision_ids:
            raise ValueError("review decision IDs must be unique")
        decision_ids.add(decision.decision_id)
        reviewer_pair = (decision.candidate_id, decision.reviewer_ref)
        if reviewer_pair in reviewer_candidate_pairs:
            raise ValueError("a reviewer may record only one decision per candidate batch")
        reviewer_candidate_pairs.add(reviewer_pair)
        grouped[decision.candidate_id].append(decision)
    return grouped


def build_genre_candidate_review_artifact(
    source_claims: tuple[SourceGenreClaim, ...],
    candidates: tuple[GenreCandidate, ...],
    review_decisions: tuple[GenreCandidateReviewDecision, ...],
    source_candidate_artifact_sha256: Sha256,
    policy: GenreCandidateWorkflowPolicy | None = None,
) -> GenreCandidateReviewArtifact:
    """Build a deterministic review artifact without creating or publishing genres."""
    resolved = policy or GenreCandidateWorkflowPolicy()
    grouped = _validated_grouped_decisions(source_claims, candidates, review_decisions, resolved)
    rows = tuple(
        _review_state(tuple(grouped[candidate.candidate_id]), resolved)
        if grouped[candidate.candidate_id]
        else GenreCandidateReviewRow(candidate_id=candidate.candidate_id, state="pending_review")
        for candidate in candidates
    )
    coverage = GenreCandidateReviewCoverage(
        source_claim_count=len(source_claims),
        candidate_count=len(candidates),
        review_decision_count=len(review_decisions),
        pending_review_count=sum(row.state == "pending_review" for row in rows),
        needs_evidence_count=sum(row.state == "needs_evidence" for row in rows),
        rejected_count=sum(row.state == "rejected" for row in rows),
        ready_for_separate_publication_count=sum(
            row.state == "ready_for_separate_publication" for row in rows
        ),
    )
    base = GenreCandidateReviewArtifact(
        policy=resolved,
        policy_sha256=sha256_json(resolved.model_dump(mode="json")),
        source_candidate_artifact_sha256=source_candidate_artifact_sha256,
        source_claims_sha256=sha256_json([item.model_dump(mode="json") for item in source_claims]),
        candidates_sha256=sha256_json([item.model_dump(mode="json") for item in candidates]),
        review_decisions_sha256=sha256_json(
            [item.model_dump(mode="json") for item in review_decisions]
        ),
        source_claims=source_claims,
        candidates=candidates,
        review_decisions=review_decisions,
        review_rows=rows,
        coverage=coverage,
        output_sha256="0" * 64,
    )
    return base.model_copy(update={"output_sha256": genre_candidate_review_output_sha256(base)})


def verify_genre_candidate_review_artifact(
    artifact: GenreCandidateReviewArtifact,
) -> GenreCandidateReviewGate:
    """Fail closed if the sealed review ledger has changed or exceeds its policy."""
    if artifact.output_sha256 != genre_candidate_review_output_sha256(artifact):
        raise ValueError("candidate review artifact output hash does not replay")
    if artifact.coverage.source_claim_count > artifact.policy.maximum_source_claims:
        raise ValueError("source claim count exceeds workflow policy bound")
    if artifact.coverage.candidate_count > artifact.policy.maximum_candidates:
        raise ValueError("candidate count exceeds workflow policy bound")
    if artifact.coverage.review_decision_count > artifact.policy.maximum_review_decisions:
        raise ValueError("review decision count exceeds workflow policy bound")
    return GenreCandidateReviewGate(
        artifact_output_sha256=artifact.output_sha256,
        candidate_count=artifact.coverage.candidate_count,
    )
