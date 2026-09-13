"""Focused safety checks for conservative open-label alignment."""

from __future__ import annotations

import json
import unittest

from pydantic import ValidationError

from opennoise.ml.label_alignment.contracts import (
    ColdLabelAlignmentArtifact,
    ColdLabelAlignmentCoverage,
    ColdLabelAlignmentSettings,
    DispositionCoverage,
    LabelAlignmentAbstention,
    MaskedEvaluation,
)
from opennoise.ml.label_alignment.normalize import (
    initialism_forms,
    is_generic_root,
    normalized_label,
    semantic_alias_target,
)
from opennoise.ml.label_alignment.pipeline import (
    ColdLabelAlignmentError,
    cold_label_alignment_artifact_sha256,
    verify_cold_label_alignment,
)
from opennoise.ml.label_alignment.release_group_vocabulary import (
    SourceKind,
    _collect_labels,
)

_SHA = "0" * 64


class LabelAlignmentContractTests(unittest.TestCase):
    """Keep the matcher conservative before any larger source run."""

    def test_unicode_and_initialism_rules_are_explicit(self) -> None:
        self.assertEqual(normalized_label("Forr\u00f3 & B\u00e9guin"), "forro and beguin")
        self.assertEqual(initialism_forms("Intelligent Dance Music"), frozenset({"idm"}))
        self.assertEqual(initialism_forms("Drum and Bass"), frozenset({"dnb"}))
        self.assertTrue(is_generic_root("music"))
        self.assertTrue(is_generic_root("Popular Music"))
        self.assertFalse(is_generic_root("intelligent dance music"))
        self.assertEqual(semantic_alias_target("popular music"), "pop")
        self.assertEqual(semantic_alias_target("pop music"), "pop")

    def test_release_group_extractor_never_descends_into_artist_metadata(self) -> None:
        observations: dict[str, dict[SourceKind, int]] = {}
        _collect_labels(
            {
                "genres": [{"name": "Forr\u00f3"}],
                "tags": [{"name": "Brazil"}, {"name": "Brazil"}],
                "artist-credit": [{"artist": {"genres": [{"name": "nested artist genre"}]}}],
            },
            observations,
        )
        self.assertEqual(
            observations,
            {
                "forro\x00Forr\u00f3": {"musicbrainz_release_group_genre_name": 1},
                "brazil\x00Brazil": {"musicbrainz_release_group_tag_name": 2},
            },
        )

    def test_artifact_rejects_an_incomplete_seed_partition(self) -> None:
        coverage = ColdLabelAlignmentCoverage(
            seed_count=2,
            reconciliation=DispositionCoverage(
                reconciled=0,
                public_only=0,
                musicbrainz_only=0,
                review_only=0,
                ambiguous=0,
                unresolved=2,
            ),
            open_identity_count=0,
            projected_open_identity_count=0,
            open_label_cluster_count=0,
            existing_open_identity_accepted_seed_count=0,
            inferred_unique_normalized_accepted_seed_count=0,
            compositional_review_seed_count=0,
            acronym_initialism_review_seed_count=0,
            semantic_alias_review_seed_count=0,
            ambiguous_existing_identity_review_seed_count=0,
            abstained_seed_count=2,
            generic_root_abstention_count=0,
        )
        payload = {
            "inputs": [
                {
                    "role": "source_neutral_evidence_graph_database",
                    "byte_sha256": _SHA,
                    "byte_count": 1,
                },
                {
                    "role": "source_neutral_evidence_graph_receipt",
                    "byte_sha256": _SHA,
                    "byte_count": 1,
                },
                {"role": "seed_reconciliation", "byte_sha256": _SHA, "byte_count": 1},
            ],
            "seed_identity_sha256": _SHA,
            "settings": ColdLabelAlignmentSettings().model_dump(mode="json"),
            "settings_sha256": _SHA,
            "input_sha256": _SHA,
            "vocabulary_sha256": _SHA,
            "accepted": [],
            "review": [],
            "abstentions": [
                LabelAlignmentAbstention(
                    source_item_id="one",
                    seed_name="one",
                    reconciliation_disposition="unresolved",
                    reason="no_open_label_candidate",
                ).model_dump(mode="json")
            ],
            "masked_evaluation": MaskedEvaluation(
                eligible_high_confidence_seed_count=0,
                masked_seed_count=0,
                retrievable_seed_count=0,
                top_1_recall=None,
                top_k_recall=None,
                accepted_prediction_count=0,
                accepted_precision=None,
                review_prediction_count=0,
                review_precision=None,
                acronym_review_prediction_count=0,
                acronym_review_precision=None,
            ).model_dump(mode="json"),
            "coverage": coverage.model_dump(mode="json"),
            "output_sha256": _SHA,
        }
        with self.assertRaises(ValidationError):
            ColdLabelAlignmentArtifact.model_validate(payload)

    def test_input_roles_reject_partial_supplemental_provenance(self) -> None:
        with self.assertRaises(ValidationError):
            ColdLabelAlignmentArtifact.model_validate(
                {
                    **self._one_seed_artifact(),
                    "inputs": [
                        {
                            "role": "source_neutral_evidence_graph_database",
                            "byte_sha256": _SHA,
                            "byte_count": 1,
                        },
                        {
                            "role": "source_neutral_evidence_graph_receipt",
                            "byte_sha256": _SHA,
                            "byte_count": 1,
                        },
                        {"role": "seed_reconciliation", "byte_sha256": _SHA, "byte_count": 1},
                        {
                            "role": "musicbrainz_release_group_vocabulary_artifact",
                            "byte_sha256": _SHA,
                            "byte_count": 1,
                        },
                    ],
                }
            )

    def test_self_consistent_hash_cannot_certify_forged_coverage(self) -> None:
        artifact = ColdLabelAlignmentArtifact.model_validate_json(
            json.dumps(self._one_seed_artifact())
        )
        forged_coverage = artifact.coverage.model_copy(
            update={"abstained_seed_count": 0, "inferred_unique_normalized_accepted_seed_count": 1}
        )
        forged = artifact.model_copy(update={"coverage": forged_coverage, "output_sha256": _SHA})
        forged = forged.model_copy(
            update={"output_sha256": cold_label_alignment_artifact_sha256(forged)}
        )
        with self.assertRaises(ColdLabelAlignmentError):
            verify_cold_label_alignment(forged)

    def _one_seed_artifact(self) -> dict[str, object]:
        return {
            "inputs": [
                {
                    "role": "source_neutral_evidence_graph_database",
                    "byte_sha256": _SHA,
                    "byte_count": 1,
                },
                {
                    "role": "source_neutral_evidence_graph_receipt",
                    "byte_sha256": _SHA,
                    "byte_count": 1,
                },
                {"role": "seed_reconciliation", "byte_sha256": _SHA, "byte_count": 1},
            ],
            "seed_identity_sha256": _SHA,
            "settings": ColdLabelAlignmentSettings().model_dump(mode="json"),
            "settings_sha256": _SHA,
            "input_sha256": _SHA,
            "vocabulary_sha256": _SHA,
            "accepted": [],
            "review": [],
            "abstentions": [
                LabelAlignmentAbstention(
                    source_item_id="one",
                    seed_name="one",
                    reconciliation_disposition="unresolved",
                    reason="no_open_label_candidate",
                ).model_dump(mode="json")
            ],
            "masked_evaluation": MaskedEvaluation(
                eligible_high_confidence_seed_count=0,
                masked_seed_count=0,
                retrievable_seed_count=0,
                top_1_recall=None,
                top_k_recall=None,
                accepted_prediction_count=0,
                accepted_precision=None,
                review_prediction_count=0,
                review_precision=None,
                acronym_review_prediction_count=0,
                acronym_review_precision=None,
            ).model_dump(mode="json"),
            "coverage": ColdLabelAlignmentCoverage(
                seed_count=1,
                reconciliation=DispositionCoverage(
                    reconciled=0,
                    public_only=0,
                    musicbrainz_only=0,
                    review_only=0,
                    ambiguous=0,
                    unresolved=1,
                ),
                open_identity_count=0,
                projected_open_identity_count=0,
                open_label_cluster_count=0,
                existing_open_identity_accepted_seed_count=0,
                inferred_unique_normalized_accepted_seed_count=0,
                compositional_review_seed_count=0,
                acronym_initialism_review_seed_count=0,
                semantic_alias_review_seed_count=0,
                ambiguous_existing_identity_review_seed_count=0,
                abstained_seed_count=1,
                generic_root_abstention_count=0,
            ).model_dump(mode="json"),
            "output_sha256": _SHA,
        }


if __name__ == "__main__":
    unittest.main()
