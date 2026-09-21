import unittest

from opennoise.taxonomy.candidates.workflow import (
    GenreCandidate,
    GenreCandidateReviewDecision,
    GenreCandidateWorkflowPolicy,
    SourceGenreClaim,
    build_genre_candidate_review_artifact,
    verify_genre_candidate_review_artifact,
)


def _claims() -> tuple[SourceGenreClaim, ...]:
    return (
        SourceGenreClaim(
            claim_id="claim:one",
            source_id="wikidata",
            source_record_id="Q1",
            observed_label="Example Sound",
            source_object_sha256="a" * 64,
        ),
    )


def _candidate() -> GenreCandidate:
    return GenreCandidate(
        candidate_id="candidate:example-sound",
        proposed_label="Example Sound",
        generator_revision="label-cluster-v1",
        source_claim_ids=("claim:one",),
        rationale="The generator clustered the retained source label.",
    )


class GenreCandidateWorkflowTests(unittest.TestCase):
    def test_seals_reviewed_candidates_without_publishing_a_genre(self) -> None:
        decisions = (
            GenreCandidateReviewDecision(
                decision_id="decision:one",
                candidate_id="candidate:example-sound",
                reviewer_ref="reviewer:alice",
                review_revision="genre-review-guide-v1",
                disposition="approve",
                rationale="The retained source observation supports this proposal.",
            ),
            GenreCandidateReviewDecision(
                decision_id="decision:two",
                candidate_id="candidate:example-sound",
                reviewer_ref="reviewer:bob",
                review_revision="genre-review-guide-v1",
                disposition="approve",
                rationale="Independent review agrees with the source evidence.",
            ),
        )
        first = build_genre_candidate_review_artifact(
            _claims(), (_candidate(),), decisions, "b" * 64
        )
        second = build_genre_candidate_review_artifact(
            _claims(), (_candidate(),), decisions, "b" * 64
        )

        self.assertEqual(first.output_sha256, second.output_sha256)
        self.assertEqual(first.review_rows[0].state, "ready_for_separate_publication")
        self.assertFalse(first.source_claims_mutated)
        self.assertFalse(first.generated_genres_published)
        self.assertFalse(first.catalog_mutated)
        self.assertTrue(
            verify_genre_candidate_review_artifact(
                first
            ).approved_candidates_require_separate_publication
        )

    def test_rejection_wins_over_approval_and_pending_is_accounted_for(self) -> None:
        candidate = _candidate()
        rejected = build_genre_candidate_review_artifact(
            _claims(),
            (candidate,),
            (
                GenreCandidateReviewDecision(
                    decision_id="decision:reject",
                    candidate_id=candidate.candidate_id,
                    reviewer_ref="reviewer:alice",
                    review_revision="genre-review-guide-v1",
                    disposition="reject",
                    rationale="The source observation is too ambiguous.",
                ),
                GenreCandidateReviewDecision(
                    decision_id="decision:approve",
                    candidate_id=candidate.candidate_id,
                    reviewer_ref="reviewer:bob",
                    review_revision="genre-review-guide-v1",
                    disposition="approve",
                    rationale="The proposed label looks plausible.",
                ),
            ),
            "b" * 64,
        )
        pending = build_genre_candidate_review_artifact(_claims(), (candidate,), (), "b" * 64)

        self.assertEqual(rejected.review_rows[0].state, "rejected")
        self.assertEqual(pending.coverage.pending_review_count, 1)

    def test_rejects_unknown_evidence_duplicate_review_and_bounds(self) -> None:
        unknown_claim = _candidate().model_copy(update={"source_claim_ids": ("claim:missing",)})
        with self.assertRaisesRegex(ValueError, "unknown source claim"):
            build_genre_candidate_review_artifact(_claims(), (unknown_claim,), (), "b" * 64)
        duplicate_reviewer = (
            GenreCandidateReviewDecision(
                decision_id="decision:one",
                candidate_id="candidate:example-sound",
                reviewer_ref="reviewer:alice",
                review_revision="genre-review-guide-v1",
                disposition="approve",
                rationale="First decision.",
            ),
            GenreCandidateReviewDecision(
                decision_id="decision:two",
                candidate_id="candidate:example-sound",
                reviewer_ref="reviewer:alice",
                review_revision="genre-review-guide-v1",
                disposition="reject",
                rationale="Second decision is intentionally invalid.",
            ),
        )
        with self.assertRaisesRegex(ValueError, "only one decision"):
            build_genre_candidate_review_artifact(
                _claims(), (_candidate(),), duplicate_reviewer, "b" * 64
            )
        with self.assertRaisesRegex(ValueError, "candidate count exceeds"):
            build_genre_candidate_review_artifact(
                _claims(),
                (_candidate(), _candidate()),
                (),
                "b" * 64,
                GenreCandidateWorkflowPolicy(maximum_candidates=1),
            )
