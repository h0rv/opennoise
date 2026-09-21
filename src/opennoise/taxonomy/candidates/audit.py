"""Deterministic, non-publishing triage for open-label genre review queues.

The audit only identifies review work that can be grouped from the sealed
artifact.  It deliberately cannot turn lexical similarity, a repeated proposed
label, or a competing label into a human review decision.
"""

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING, Final, Literal

from pydantic import Field, model_validator

from opennoise.common import sha256_json
from opennoise.models import FrozenModel
from opennoise.taxonomy.candidates.open_label_graph import (
    genre_candidate_review_from_open_label_graph,
    require_original_open_label_graph_queue,
)
from opennoise.taxonomy.open.label_graph_model import (
    OpenLabelGraphArtifact,
    OpenLabelGraphCandidate,
    verify_open_label_graph_model,
)
from opennoise.types import Sha256  # noqa: TC001  # Pydantic resolves aliases at runtime.

if TYPE_CHECKING:
    from opennoise.taxonomy.candidates.workflow import GenreCandidateReviewArtifact

_REVISION: Final = "genre-candidate-triage-audit-v2"

type TriageReason = Literal[
    "human_domain_interpretation_required",
    "lexical_only_evidence",
    "repeated_proposed_label",
    "competing_candidate_for_seed",
]


class GenreCandidateTriageRow(FrozenModel):
    """One review-only row with mechanically derived queueing reasons."""

    candidate_id: str = Field(pattern=r"^candidate:[A-Za-z0-9._:-]{1,240}$")
    source_item_id: str = Field(min_length=1, max_length=200)
    proposed_label: str = Field(min_length=1, max_length=500)
    reasons: tuple[TriageReason, ...] = Field(min_length=1, max_length=4)

    @model_validator(mode="after")
    def _unique_reasons(self) -> GenreCandidateTriageRow:
        if len(self.reasons) != len(set(self.reasons)):
            raise ValueError("triage reasons must be unique")
        return self


class GenreCandidateTriageCoverage(FrozenModel):
    """Complete accounting that expressly withholds automatic judgments."""

    source_claim_count: int = Field(ge=1)
    candidate_count: int = Field(ge=0)
    lexical_only_count: int = Field(ge=0)
    repeated_proposed_label_count: int = Field(ge=0)
    competing_candidate_for_seed_count: int = Field(ge=0)
    human_review_required_count: int = Field(ge=0)
    deterministic_rejection_count: Literal[0] = 0
    deterministic_approval_count: Literal[0] = 0

    @model_validator(mode="after")
    def _complete(self) -> GenreCandidateTriageCoverage:
        if self.lexical_only_count > self.candidate_count:
            raise ValueError("lexical-only count cannot exceed candidates")
        if self.human_review_required_count != self.candidate_count:
            raise ValueError("every candidate must remain queued for human review")
        return self


class GenreCandidateTriageAudit(FrozenModel):
    """A hash-bound audit that never records a review or publication decision."""

    revision: Literal["genre-candidate-triage-audit-v2"] = _REVISION
    source_candidate_artifact_sha256: Sha256
    review_queue_output_sha256: Sha256
    source_claims_sha256: Sha256
    triage_rows: tuple[GenreCandidateTriageRow, ...]
    coverage: GenreCandidateTriageCoverage
    source_claims_mutated: Literal[False] = False
    review_decisions_created: Literal[False] = False
    generated_genres_published: Literal[False] = False
    catalog_mutated: Literal[False] = False
    output_sha256: Sha256

    @model_validator(mode="after")
    def _complete(self) -> GenreCandidateTriageAudit:
        candidate_ids = tuple(row.candidate_id for row in self.triage_rows)
        if len(candidate_ids) != len(set(candidate_ids)):
            raise ValueError("triage rows must cover a candidate only once")
        if len(self.triage_rows) != self.coverage.candidate_count:
            raise ValueError("triage row count does not match coverage")
        return self


def genre_candidate_triage_output_sha256(audit: GenreCandidateTriageAudit) -> Sha256:
    """Recompute the audit's logical content hash."""
    return sha256_json(audit.model_dump(mode="json", exclude={"output_sha256"}))


def audit_open_label_graph_candidates(source: OpenLabelGraphArtifact) -> GenreCandidateTriageAudit:
    """Create deterministic queueing groups without judging music-domain meaning."""
    verify_open_label_graph_model(source)
    queue = genre_candidate_review_from_open_label_graph(source)
    require_original_open_label_graph_queue(queue, source)
    return _audit(source, queue)


def _audit(
    source: OpenLabelGraphArtifact, queue: GenreCandidateReviewArtifact
) -> GenreCandidateTriageAudit:
    """Audit the exact empty review queue generated from a verified source."""
    if len(source.candidates) != len(queue.candidates):
        raise ValueError("source candidates do not match review queue candidates")
    proposed_label_counts = Counter(candidate.proposed_label for candidate in queue.candidates)
    seed_counts = Counter(candidate.source_item_id for candidate in source.candidates)
    rows = tuple(
        GenreCandidateTriageRow(
            candidate_id=queue_candidate.candidate_id,
            source_item_id=source_candidate.source_item_id,
            proposed_label=queue_candidate.proposed_label,
            reasons=(
                "human_domain_interpretation_required",
                *(
                    ("lexical_only_evidence",)
                    if _has_no_nonlexical_support(source_candidate)
                    else ()
                ),
                *(
                    ("repeated_proposed_label",)
                    if proposed_label_counts[queue_candidate.proposed_label] > 1
                    else ()
                ),
                *(
                    ("competing_candidate_for_seed",)
                    if seed_counts[source_candidate.source_item_id] > 1
                    else ()
                ),
            ),
        )
        for source_candidate, queue_candidate in zip(
            source.candidates, queue.candidates, strict=True
        )
    )
    coverage = GenreCandidateTriageCoverage(
        source_claim_count=queue.coverage.source_claim_count,
        candidate_count=len(rows),
        lexical_only_count=sum("lexical_only_evidence" in row.reasons for row in rows),
        repeated_proposed_label_count=sum("repeated_proposed_label" in row.reasons for row in rows),
        competing_candidate_for_seed_count=sum(
            "competing_candidate_for_seed" in row.reasons for row in rows
        ),
        human_review_required_count=len(rows),
    )
    base = GenreCandidateTriageAudit(
        source_candidate_artifact_sha256=source.output_sha256,
        review_queue_output_sha256=queue.output_sha256,
        source_claims_sha256=queue.source_claims_sha256,
        triage_rows=rows,
        coverage=coverage,
        output_sha256="0" * 64,
    )
    return base.model_copy(update={"output_sha256": genre_candidate_triage_output_sha256(base)})


def _has_no_nonlexical_support(candidate: OpenLabelGraphCandidate) -> bool:
    """Return whether a source row lacks artist or contextual corroboration."""
    # The source model is validated at the public boundary.  This is a
    # structural check only, so it requires no music-label interpretation.
    return (
        candidate.direct_artist_overlap_count == 0
        and candidate.contextual_tag_overlap_count == 0
        and candidate.features.artist_graph_jaccard == 0.0
        and candidate.features.contextual_tag_match == 0.0
    )


def verify_genre_candidate_triage_audit(audit: GenreCandidateTriageAudit) -> None:
    """Fail closed on a modified audit or any claimed automatic decision."""
    if audit.output_sha256 != genre_candidate_triage_output_sha256(audit):
        raise ValueError("genre candidate triage audit output hash does not replay")
    if audit.coverage.deterministic_rejection_count or audit.coverage.deterministic_approval_count:
        raise ValueError("triage audit must not contain automatic review decisions")
