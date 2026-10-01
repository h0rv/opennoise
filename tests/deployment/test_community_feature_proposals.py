"""Inferred style suggestions must bind their model and observed musical cues."""

import copy
import unittest
from typing import Any

from opennoise.deployment.community_preview import validate_feature_proposals

_TRAINING = "a" * 64
_MODEL = "b" * 64
_RECORD: dict[str, Any] = {
    "observed_music_values": ["ambient"],
    "feature_proposals": [
        {
            "value": "glitch",
            "role": "inferred_feature_proposal",
            "native_fact": False,
            "score_calibrated": False,
            "training_source_sha256": _TRAINING,
            "training_input_sha256": _TRAINING,
            "source_model_sha256": _MODEL,
            "score": 0.4,
            "training_target_artist_support": 4,
            "evidence": [
                {
                    "value": "ambient",
                    "cue_role": "proper_genre",
                    "training_joint_artist_support": 2,
                    "training_cue_artist_support": 5,
                    "query_evidence_refs": ["native-custody:artist:ambient"],
                    "query_evidence_ref_count": 1,
                }
            ],
        }
    ],
}


class FeatureProposalBoundaryTests(unittest.TestCase):
    def test_source_explained_inference_is_accepted(self) -> None:
        validate_feature_proposals(_RECORD, _TRAINING, _MODEL)

    def test_native_claim_and_wrong_model_are_rejected(self) -> None:
        for key, value in [
            ("native_fact", True),
            ("role", "direct_source_observation"),
            ("training_input_sha256", "c" * 64),
            ("source_model_sha256", "d" * 64),
        ]:
            with self.subTest(key=key):
                record = copy.deepcopy(_RECORD)
                record["feature_proposals"][0][key] = value
                with self.assertRaises(ValueError):
                    validate_feature_proposals(record, _TRAINING, _MODEL)

    def test_proposal_cannot_claim_an_observed_value(self) -> None:
        record = copy.deepcopy(_RECORD)
        record["observed_music_values"].append("glitch")
        with self.assertRaisesRegex(ValueError, "observed"):
            validate_feature_proposals(record, _TRAINING, _MODEL)

    def test_unobserved_cues_or_impossible_support_cannot_explain_prediction(self) -> None:
        for key, value in [
            ("value", "house"),
            ("training_joint_artist_support", 6),
            ("query_evidence_refs", []),
            ("training_cue_artist_support", True),
        ]:
            with self.subTest(key=key):
                record = copy.deepcopy(_RECORD)
                record["feature_proposals"][0]["evidence"][0][key] = value
                with self.assertRaises(ValueError):
                    validate_feature_proposals(record, _TRAINING, _MODEL)
