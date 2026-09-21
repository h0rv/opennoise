"""Adapt sealed open-label-graph candidates into review queues only."""

from __future__ import annotations

from collections import defaultdict

from opennoise.common import sha256_json
from opennoise.taxonomy.candidates.workflow import (
    GenreCandidate,
    GenreCandidateReviewArtifact,
    GenreCandidateReviewDecision,
    GenreCandidateWorkflowPolicy,
    SourceGenreClaim,
    build_genre_candidate_review_artifact,
    verify_genre_candidate_review_artifact,
)
from opennoise.taxonomy.open.label_graph_model import (
    OpenLabelGraphArtifact,
    verify_open_label_graph_model,
)


def _claim_id(source_object_sha256: str, evidence_ref: str) -> str:
    claim = {"source_object_sha256": source_object_sha256, "evidence_ref": evidence_ref}
    return f"claim:{sha256_json(claim)}"


def genre_candidate_review_from_open_label_graph(
    source: OpenLabelGraphArtifact,
    review_decisions: tuple[GenreCandidateReviewDecision, ...] = (),
    policy: GenreCandidateWorkflowPolicy | None = None,
) -> GenreCandidateReviewArtifact:
    """Make a queue from review candidates without asserting genre identity or publication."""
    verify_open_label_graph_model(source)
    labels_by_ref: dict[str, set[str]] = defaultdict(set)
    for candidate in source.candidates:
        for evidence_ref in candidate.evidence_refs:
            labels_by_ref[evidence_ref].add(candidate.candidate_label_name)
    if any(len(labels) != 1 for labels in labels_by_ref.values()):
        raise ValueError("open label graph evidence reference maps to multiple observed labels")
    source_claims = tuple(
        SourceGenreClaim(
            claim_id=_claim_id(source.seed_target_file_sha256, evidence_ref),
            source_id="musicbrainz_seed_target",
            source_record_id=evidence_ref,
            observed_label=next(iter(labels_by_ref[evidence_ref])),
            source_object_sha256=source.seed_target_file_sha256,
        )
        for evidence_ref in sorted(labels_by_ref)
    )
    candidates = tuple(
        GenreCandidate(
            candidate_id=f"candidate:open-label-graph:{source.output_sha256}:{index}",
            proposed_label=row.candidate_label_name,
            generator_revision=source.revision,
            source_claim_ids=tuple(
                _claim_id(source.seed_target_file_sha256, evidence_ref)
                for evidence_ref in sorted(row.evidence_refs)
            ),
            rationale=(
                f"Open-label graph candidate {row.candidate_label_id} for retained seed "
                f"{row.source_item_id}; score={row.score:.12g}, "
                f"lexical_baseline_score={row.lexical_baseline_score:.12g}."
            ),
        )
        for index, row in enumerate(source.candidates, start=1)
    )
    return build_genre_candidate_review_artifact(
        source_claims, candidates, review_decisions, source.output_sha256, policy
    )


def require_original_open_label_graph_queue(
    queue: GenreCandidateReviewArtifact, source: OpenLabelGraphArtifact
) -> None:
    """Require the exact empty queue derived from this verified source and its policy."""
    verify_genre_candidate_review_artifact(queue)
    if queue.review_decisions:
        raise ValueError("apply requires the original queue without review decisions")
    expected = genre_candidate_review_from_open_label_graph(source, policy=queue.policy)
    if queue.output_sha256 != expected.output_sha256:
        raise ValueError("review queue does not exactly match its source artifact and policy")
