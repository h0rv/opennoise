import unittest

from opennoise.common import sha256_json
from opennoise.taxonomy.candidates.audit import (
    audit_open_label_graph_candidates,
    verify_genre_candidate_triage_audit,
)
from tests.taxonomy.candidates.test_open_label_graph import _source_fixture


class GenreCandidateTriageAuditTests(unittest.TestCase):
    def test_triage_preserves_human_review_for_lexical_only_candidate(self) -> None:
        audit = audit_open_label_graph_candidates(_source_fixture())

        self.assertEqual(audit.coverage.candidate_count, 1)
        self.assertEqual(audit.coverage.lexical_only_count, 1)
        self.assertEqual(audit.coverage.human_review_required_count, 1)
        self.assertEqual(audit.coverage.deterministic_rejection_count, 0)
        self.assertEqual(audit.coverage.deterministic_approval_count, 0)
        self.assertEqual(
            audit.triage_rows[0].reasons,
            ("human_domain_interpretation_required", "lexical_only_evidence"),
        )
        self.assertFalse(audit.review_decisions_created)
        self.assertFalse(audit.generated_genres_published)
        verify_genre_candidate_triage_audit(audit)

    def test_triage_groups_repeated_proposed_labels_and_competing_seed_candidates(self) -> None:
        source = _source_fixture()
        first = source.candidates[0]
        second = first.model_copy(update={"candidate_label_id": "tag:other"})
        source = source.model_copy(
            update={"candidates": (first, second), "output_sha256": "0" * 64}
        )
        source = source.model_copy(
            update={
                "output_sha256": sha256_json(
                    source.model_dump(mode="json", exclude={"output_sha256"})
                )
            }
        )

        audit = audit_open_label_graph_candidates(source)

        self.assertEqual(audit.coverage.repeated_proposed_label_count, 2)
        self.assertEqual(audit.coverage.competing_candidate_for_seed_count, 2)
        self.assertEqual(
            audit.triage_rows[0].reasons,
            (
                "human_domain_interpretation_required",
                "lexical_only_evidence",
                "repeated_proposed_label",
                "competing_candidate_for_seed",
            ),
        )

    def test_triage_marks_same_label_from_distinct_source_claims(self) -> None:
        first = _source_fixture().candidates[0]
        second = first.model_copy(
            update={
                "source_item_id": "item:another-unanchored",
                "candidate_label_id": "tag:other-example-sound",
                "evidence_refs": ("musicbrainz:seed-target:fixture:tag:other-example-sound",),
            }
        )
        source = _source_fixture().model_copy(
            update={"candidates": (first, second), "output_sha256": "0" * 64}
        )
        source = source.model_copy(
            update={
                "output_sha256": sha256_json(
                    source.model_dump(mode="json", exclude={"output_sha256"})
                )
            }
        )

        audit = audit_open_label_graph_candidates(source)

        self.assertEqual(audit.coverage.source_claim_count, 2)
        self.assertEqual(audit.coverage.repeated_proposed_label_count, 2)
        self.assertEqual(audit.coverage.competing_candidate_for_seed_count, 0)
        self.assertEqual(
            audit.triage_rows[0].reasons,
            (
                "human_domain_interpretation_required",
                "lexical_only_evidence",
                "repeated_proposed_label",
            ),
        )
