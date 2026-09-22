import unittest

from opennoise.common import sha256_json
from opennoise.taxonomy.candidates.audit import (
    audit_open_label_graph_candidates,
    genre_candidate_triage_output_sha256,
)
from opennoise.taxonomy.candidates.open_label_graph import (
    genre_candidate_review_from_open_label_graph,
)
from opennoise.taxonomy.candidates.promotion_preflight import (
    build_genre_candidate_promotion_preflight,
    verify_genre_candidate_promotion_preflight,
)
from opennoise.taxonomy.candidates.workflow import GenreCandidateReviewDecision
from tests.taxonomy.candidates.test_open_label_graph import _source_fixture


class GenreCandidatePromotionPreflightTests(unittest.TestCase):
    def test_incomplete_review_retains_triage_blocker_in_coverage(self) -> None:
        source = _source_fixture()
        preflight = build_genre_candidate_promotion_preflight(
            genre_candidate_review_from_open_label_graph(source),
            audit_open_label_graph_candidates(source),
        )

        self.assertEqual(preflight.rows[0].state, "awaiting_independent_review")
        self.assertEqual(preflight.coverage.awaiting_independent_review_count, 1)
        self.assertEqual(preflight.coverage.triage_blocked_count, 1)

    def test_lexical_only_candidate_is_blocked_even_after_independent_review(self) -> None:
        source = _source_fixture()
        queue = genre_candidate_review_from_open_label_graph(source)
        candidate_id = queue.candidates[0].candidate_id
        reviewed = genre_candidate_review_from_open_label_graph(
            source,
            (
                GenreCandidateReviewDecision(
                    decision_id="decision:one",
                    candidate_id=candidate_id,
                    reviewer_ref="reviewer:one",
                    review_revision="guide-v1",
                    disposition="approve",
                    rationale="First independent review.",
                ),
                GenreCandidateReviewDecision(
                    decision_id="decision:two",
                    candidate_id=candidate_id,
                    reviewer_ref="reviewer:two",
                    review_revision="guide-v1",
                    disposition="approve",
                    rationale="Second independent review.",
                ),
            ),
        )

        preflight = build_genre_candidate_promotion_preflight(
            reviewed, audit_open_label_graph_candidates(source)
        )

        self.assertEqual(preflight.rows[0].state, "blocked_by_triage")
        self.assertEqual(preflight.coverage.blocked_by_triage_count, 1)
        self.assertEqual(preflight.coverage.public_genres_authorized_count, 0)
        self.assertFalse(preflight.public_export_authorized)
        verify_genre_candidate_promotion_preflight(preflight)

    def test_nonlexical_reviewed_candidate_still_needs_source_authorization(self) -> None:
        source = _source_fixture()
        candidate = source.candidates[0].model_copy(update={"direct_artist_overlap_count": 1})
        base = source.model_copy(update={"candidates": (candidate,), "output_sha256": "0" * 64})
        source = base.model_copy(
            update={
                "output_sha256": sha256_json(
                    base.model_dump(mode="json", exclude={"output_sha256"})
                )
            }
        )
        queue = genre_candidate_review_from_open_label_graph(source)
        candidate_id = queue.candidates[0].candidate_id
        decisions = tuple(
            GenreCandidateReviewDecision(
                decision_id=f"decision:{index}",
                candidate_id=candidate_id,
                reviewer_ref=f"reviewer:{index}",
                review_revision="guide-v1",
                disposition="approve",
                rationale="Independent review.",
            )
            for index in (1, 2)
        )
        reviewed = genre_candidate_review_from_open_label_graph(source, decisions)

        preflight = build_genre_candidate_promotion_preflight(
            reviewed, audit_open_label_graph_candidates(source)
        )

        self.assertEqual(preflight.rows[0].state, "awaiting_source_publication_authorization")
        self.assertEqual(preflight.coverage.awaiting_source_publication_authorization_count, 1)

    def test_rejects_triage_from_another_source_artifact(self) -> None:
        source = _source_fixture()
        reviewed = genre_candidate_review_from_open_label_graph(source)
        original = audit_open_label_graph_candidates(source)
        altered = original.model_copy(
            update={"source_candidate_artifact_sha256": "b" * 64, "output_sha256": "0" * 64}
        )
        triage = altered.model_copy(
            update={"output_sha256": genre_candidate_triage_output_sha256(altered)}
        )

        with self.assertRaisesRegex(ValueError, "different source candidate artifact"):
            build_genre_candidate_promotion_preflight(reviewed, triage)
