import unittest

from opennoise.common import sha256_json
from opennoise.taxonomy.candidates.open_label_graph import (
    genre_candidate_review_from_open_label_graph,
    require_original_open_label_graph_queue,
)
from opennoise.taxonomy.candidates.workflow import GenreCandidateReviewDecision
from opennoise.taxonomy.open.label_graph_model import (
    LabelGraphFeatures,
    OpenLabelGraphArtifact,
    OpenLabelGraphCandidate,
    OpenLabelGraphSettings,
)


def _source_fixture() -> OpenLabelGraphArtifact:
    settings = OpenLabelGraphSettings()
    candidate = OpenLabelGraphCandidate(
        source_item_id="item:unanchored",
        seed_name="Example Sound",
        candidate_label_id="tag:example-sound",
        candidate_label_name="Example Sound",
        score=0.9,
        lexical_baseline_score=0.8,
        features=LabelGraphFeatures(
            token_jaccard=1.0,
            character_ngram_cosine=1.0,
            normalized_subword_overlap=1.0,
            head_modifier_relation=1.0,
            tag_support=1.0,
            artist_graph_jaccard=0.0,
            contextual_tag_match=0.0,
        ),
        direct_artist_overlap_count=0,
        contextual_tag_overlap_count=0,
        evidence_refs=("musicbrainz:seed-target:fixture:tag:example-sound",),
    )
    base = OpenLabelGraphArtifact.model_construct(
        seed_target_file_sha256="a" * 64,
        settings=settings,
        settings_sha256=sha256_json(settings.model_dump(mode="json")),
        candidates=(candidate,),
        output_sha256="0" * 64,
    )
    return base.model_copy(
        update={
            "output_sha256": sha256_json(base.model_dump(mode="json", exclude={"output_sha256"}))
        }
    )


class OpenLabelGraphReviewQueueTests(unittest.TestCase):
    def test_source_bound_fixture_flows_from_queue_to_human_review(self) -> None:
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
                    rationale="The source claim is adequate for separate publication review.",
                ),
                GenreCandidateReviewDecision(
                    decision_id="decision:two",
                    candidate_id=candidate_id,
                    reviewer_ref="reviewer:two",
                    review_revision="guide-v1",
                    disposition="approve",
                    rationale="Independent review agrees with the retained source claim.",
                ),
            ),
        )

        self.assertEqual(queue.coverage.pending_review_count, 1)
        self.assertEqual(queue.source_claims[0].source_object_sha256, "a" * 64)
        self.assertEqual(queue.source_candidate_artifact_sha256, source.output_sha256)
        self.assertEqual(reviewed.review_rows[0].state, "ready_for_separate_publication")
        self.assertFalse(reviewed.generated_genres_published)
        self.assertFalse(reviewed.catalog_mutated)

    def test_rejects_a_self_consistent_but_substituted_queue(self) -> None:
        source = _source_fixture()
        queue = genre_candidate_review_from_open_label_graph(source)
        altered_claim = queue.source_claims[0].model_copy(
            update={"observed_label": "Different Label"}
        )
        altered = queue.model_copy(
            update={
                "source_claims": (altered_claim,),
                "source_claims_sha256": sha256_json([altered_claim.model_dump(mode="json")]),
                "output_sha256": "0" * 64,
            }
        )
        altered = altered.model_copy(
            update={
                "output_sha256": sha256_json(
                    altered.model_dump(mode="json", exclude={"output_sha256"})
                )
            }
        )

        with self.assertRaisesRegex(ValueError, "does not exactly match"):
            require_original_open_label_graph_queue(altered, source)
