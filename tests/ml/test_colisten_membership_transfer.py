"""Behavioral tests for review-only, edge-split co-listen membership transfer."""

from __future__ import annotations

import unittest

from opennoise.ml.colisten_membership_transfer.contracts import (
    CoListenMembershipTransferArtifact,
    CoListenMembershipTransferSettings,
    ReviewCandidate,
    TransferEvaluation,
)
from opennoise.ml.colisten_membership_transfer.pipeline import _evaluation, _is_heldout, _transfer


def _settings_with_a_heldout_target_and_train_source() -> CoListenMembershipTransferSettings:
    """Find a deterministic edge split where target and source cannot leak the same pair."""
    for split_seed in range(10_000):
        settings = CoListenMembershipTransferSettings(split_seed=split_seed, heldout_fraction=0.2)
        if _is_heldout("target", "seed-1", settings) and not _is_heldout(
            "source", "seed-1", settings
        ):
            return settings
    raise AssertionError("test could not find an edge-level train/heldout split")


def _artifact_payload() -> dict[str, object]:
    """Return a small but internally complete artifact payload for tamper regression tests."""
    digest = "a" * 64
    evaluation = {
        "heldout_direct_positive_count": 1,
        "eligible_heldout_artist_count": 1,
        "abstained_no_colisten_or_support_artist_count": 0,
        "scoreable_direct_positive_count": 1,
        "recovered_at_10_count": 1,
        "recovered_at_25_count": 1,
        "recall_at_10": 1.0,
        "recall_at_25": 1.0,
    }
    return {
        "inputs": tuple(
            {
                "role": role,
                "byte_sha256": digest,
                "byte_count": 1,
                "logical_sha256": digest,
            }
            for role in ("graph_database", "graph_receipt", "colisten_database", "colisten_receipt")
        ),
        "graph_receipt_output_sha256": digest,
        "colisten_receipt_output_sha256": digest,
        "settings": {},
        "settings_sha256": digest,
        "coverage": {
            "colisten_artist_count": 1,
            "direct_labeled_colisten_artist_count": 0,
            "direct_cold_colisten_artist_count": 1,
            "eligible_cold_artist_count": 1,
            "abstained_cold_artist_count": 0,
            "candidate_count": 1,
        },
        "candidates": (
            {
                "artist_mbid": "target",
                "stable_seed_id": "seed-1",
                "score": 1.0,
                "supporting_artist_count": 1,
                "supporting_colisten_edge_count": 1,
                "summed_distinct_user_support": 5,
                "retained_supports": (
                    {
                        "source_artist_mbid": "source",
                        "co_listen_evidence_fingerprint": "edge-1",
                        "distinct_user_count": 5,
                        "contribution": 1.0,
                    },
                ),
                "omitted_support_row_count": 0,
            },
        ),
        "heldout_evaluation": dict(evaluation),
        "train_only_global_popularity_baseline": dict(evaluation),
        "direct_only_no_colisten_ablation": dict(evaluation),
        "output_sha256": digest,
    }


class CoListenMembershipTransferTests(unittest.TestCase):
    """Holdout leakage and positive-only accounting tests."""

    def test_edge_level_holdout_is_removed_before_peer_feature_aggregation(self) -> None:
        """Only the source artist's train-side label can recover a target-heldout positive."""
        settings = _settings_with_a_heldout_target_and_train_source()
        evaluation = _evaluation(
            {"target": {"seed-1"}, "source": {"seed-1"}},
            (("source", "target", "edge-1", 5),),
            settings,
        )

        self.assertEqual(evaluation.heldout_direct_positive_count, 1)
        self.assertEqual(evaluation.eligible_heldout_artist_count, 1)
        self.assertEqual(evaluation.recovered_at_10_count, 1)
        self.assertEqual(evaluation.recall_at_25, 1.0)

    def test_heldout_source_label_cannot_enter_transfer_features(self) -> None:
        """A peer's own held-out direct edge is unavailable to every target candidate."""
        settings = _settings_with_a_heldout_target_and_train_source()
        candidates = _transfer(
            (("source", "target", "edge-1", 5),),
            {"source": set()},
            {"target"},
            settings,
        )

        self.assertEqual(candidates, {})

    def test_transfer_provenance_retains_source_and_aggregate_edge_identity(self) -> None:
        """Candidates preserve aggregate paths without inventing a membership fact."""
        settings = CoListenMembershipTransferSettings(maximum_candidates_per_artist=5)
        candidates = _transfer(
            (("source", "target", "edge-1", 7),),
            {"source": {"seed-1"}},
            {"target"},
            settings,
        )

        candidate = candidates["target"][0]
        self.assertEqual(candidate.membership_semantics, "review_only_not_factual_membership")
        self.assertEqual(candidate.summed_distinct_user_support, 7)
        self.assertEqual(candidate.retained_supports[0].source_artist_mbid, "source")
        self.assertEqual(candidate.retained_supports[0].co_listen_evidence_fingerprint, "edge-1")

    def test_evaluation_rejects_nonreplaying_recall_fraction(self) -> None:
        """A report cannot overstate a positive-only held-out result by changing a fraction."""
        with self.assertRaises(ValueError):
            TransferEvaluation(
                heldout_direct_positive_count=2,
                eligible_heldout_artist_count=1,
                abstained_no_colisten_or_support_artist_count=0,
                scoreable_direct_positive_count=2,
                recovered_at_10_count=1,
                recovered_at_25_count=1,
                recall_at_10=1.0,
                recall_at_25=0.5,
            )

    def test_candidate_rejects_incomplete_or_impossible_support_ledger(self) -> None:
        """Provenance count changes cannot survive a rehashed candidate artifact."""
        payload = _artifact_payload()
        candidates = payload["candidates"]
        if not isinstance(candidates, tuple):
            self.fail("candidate test fixture must contain a tuple")
        candidate = candidates[0]
        if not isinstance(candidate, dict):
            self.fail("candidate test fixture must contain a mapping")
        candidate["omitted_support_row_count"] = 1

        with self.assertRaises(ValueError):
            ReviewCandidate.model_validate(candidate)

        diversity_tamper = dict(candidate)
        diversity_tamper["omitted_support_row_count"] = 0
        diversity_tamper["supporting_colisten_edge_count"] = 2
        diversity_tamper["retained_supports"] = (
            candidate["retained_supports"][0],
            {
                "source_artist_mbid": "another-source",
                "co_listen_evidence_fingerprint": "edge-2",
                "distinct_user_count": 5,
                "contribution": 1.0,
            },
        )
        with self.assertRaises(ValueError):
            ReviewCandidate.model_validate(diversity_tamper)

    def test_artifact_rejects_tampered_coverage_or_evaluation_cohort(self) -> None:
        """Coverage and all three ablations must replay one exact candidate and holdout cohort."""
        coverage_tamper = _artifact_payload()
        coverage = coverage_tamper["coverage"]
        if not isinstance(coverage, dict):
            self.fail("coverage test fixture must contain a mapping")
        coverage["candidate_count"] = 0
        with self.assertRaises(ValueError):
            CoListenMembershipTransferArtifact.model_validate(coverage_tamper)

        evaluation_tamper = _artifact_payload()
        direct_only = evaluation_tamper["direct_only_no_colisten_ablation"]
        if not isinstance(direct_only, dict):
            self.fail("evaluation test fixture must contain a mapping")
        direct_only["eligible_heldout_artist_count"] = 0
        with self.assertRaises(ValueError):
            CoListenMembershipTransferArtifact.model_validate(evaluation_tamper)


if __name__ == "__main__":
    unittest.main()
