"""Reject fabricated detail and distinguish coherent support from degenerate partitions."""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import cast

from opennoise.analysis.emergent_community_evaluation import (
    FeatureFact,
    assert_feature_holdout_isolation,
    evaluate_communities,
    evaluate_feature_recovery,
    evaluate_topic_run,
    split_feature_evidence,
)
from opennoise.common import canonical_json, sha256_file, sha256_json


def _number(value: object) -> float:
    assert isinstance(value, (int, float))
    return float(value)


class EmergentCommunityEvaluationTests(unittest.TestCase):
    def test_identical_musical_profiles_cannot_be_split_into_microgenres(self) -> None:
        profiles = {f"artist-{i}": ("ambient", "electronic") for i in range(12)}
        half = len(profiles) // 2
        assigned = {artist: "one" if i < half else "two" for i, artist in enumerate(profiles)}
        result = evaluate_communities(profiles, assigned)
        self.assertFalse(result["identical_profile_constraint_passed"])
        self.assertEqual(result["identical_musical_profiles_split_count"], 1)
        self.assertEqual(result["single_profile_community_count"], 2)
        self.assertAlmostEqual(_number(result["within_community_idf_cosine"]), 1)
        self.assertEqual(cast("dict[str, object]", result["null"])["upper_tail_empirical_p"], 1)

    def test_two_distinct_supported_scenes_exceed_a_degree_preserving_null(self) -> None:
        half = 12
        profiles = {
            f"artist-{i}": ("electronic", "ambient" if i < half else "techno", f"distinct-{i}")
            for i in range(24)
        }
        assigned = {f"artist-{i}": "one" if i < half else "two" for i in range(24)}
        result = evaluate_communities(profiles, assigned)
        self.assertTrue(result["identical_profile_constraint_passed"])
        self.assertEqual(result["single_profile_community_count"], 0)
        null = cast("dict[str, object]", result["null"])
        self.assertGreater(_number(null["observed_minus_null_mean"]), 0.05)
        self.assertLessEqual(_number(null["upper_tail_empirical_p"]), 0.05)
        self.assertFalse(result["genre_names_validated"])
        self.assertFalse(result["held_out_prediction_evaluated"])

    def test_cosine_uses_complete_profiles_and_known_pairwise_denominator(self) -> None:
        profiles = {"a": ("same",), "b": ("same",), "c": ("different",)}
        result = evaluate_communities(profiles, dict.fromkeys(profiles, "all"))
        self.assertAlmostEqual(_number(result["within_community_idf_cosine"]), 1 / 3)
        self.assertEqual(cast("dict[str, object]", result["null"])["upper_tail_empirical_p"], 1)

    def test_stability_is_label_invariant_and_reports_abstention_coverage(self) -> None:
        profiles = {str(i): (f"feature-{i}",) for i in range(6)}
        half = 3
        assigned = {str(i): "one" if i < half else "two" for i in range(6)}
        relabeled = {str(i): "x" if i < half else "y" for i in range(6)}
        partial = {str(i): "x" if i < half else "y" for i in range(4)}
        result = evaluate_communities(
            profiles, assigned, resampled_assignments=(relabeled, partial)
        )
        stability = cast("list[dict[str, object]]", result["resample_stability"])
        self.assertEqual(stability[0]["adjusted_rand_index"], 1)
        self.assertEqual(stability[1]["adjusted_rand_index"], 1)
        self.assertEqual(stability[1]["joint_assignment_coverage"], 4 / 6)

    def test_single_community_and_singletons_do_not_claim_stability(self) -> None:
        profiles = {str(i): (f"feature-{i}",) for i in range(6)}
        for assignment in (dict.fromkeys(profiles, "one"), {artist: artist for artist in profiles}):
            result = evaluate_communities(profiles, assignment, resampled_assignments=(assignment,))
            stability = cast("list[dict[str, object]]", result["resample_stability"])
            self.assertIsNone(stability[0]["adjusted_rand_index"])
            self.assertEqual(stability[0]["status"], "unavailable_degenerate_partition")

    def test_abstentions_are_retained_and_zero_musical_evidence_cannot_be_assigned(self) -> None:
        result = evaluate_communities({"a": (), "b": ("ambient",)}, {})
        self.assertEqual(result["abstained_artist_count"], 2)
        self.assertIsNone(result["within_community_idf_cosine"])
        self.assertIsNone(cast("dict[str, object]", result["null"])["upper_tail_empirical_p"])
        with self.assertRaisesRegex(ValueError, "must abstain"):
            evaluate_communities({"a": ()}, {"a": "invented"})
        with self.assertRaisesRegex(ValueError, "unknown source"):
            evaluate_communities({"a": ("ambient",)}, {"other": "invented"})

    def test_observation_order_and_duplicate_features_do_not_change_metrics(self) -> None:
        source = {"a": ("one", "two", "one"), "b": ("one",), "c": ("three",)}
        assigned = {"a": "x", "b": "x", "c": "y"}
        reordered = {artist: tuple(reversed(values)) for artist, values in reversed(source.items())}
        self.assertEqual(
            evaluate_communities(source, assigned), evaluate_communities(reordered, assigned)
        )

    def test_evidence_components_keep_reissues_and_repeated_votes_together(self) -> None:
        facts = [
            FeatureFact("artist-a", "ambient", "release-group-one"),
            FeatureFact("artist-b", "drone", "release-group-one"),
            FeatureFact("artist-a", "ambient", "artist-votes-one"),
            FeatureFact("artist-c", "experimental", "artist-votes-one"),
            *(FeatureFact(f"artist-{i}", "rock", f"independent-{i}") for i in range(100)),
        ]
        train, hidden = split_feature_evidence(facts, salt="fixed-test")
        self.assertTrue(train)
        self.assertTrue(hidden)
        self.assertEqual(set(train) | set(hidden), set(facts))
        self.assertTrue(set(facts[:4]) <= set(train) or set(facts[:4]) <= set(hidden))
        self.assertEqual(
            (train, hidden), split_feature_evidence(reversed(facts), salt="fixed-test")
        )
        assert_feature_holdout_isolation(train, hidden)

    def test_distinct_copies_of_the_same_vote_or_release_cannot_be_held_out(self) -> None:
        train = [FeatureFact("a", "ambient", "release-group-one")]
        with self.assertRaisesRegex(ValueError, "evidence group"):
            assert_feature_holdout_isolation(
                train, [FeatureFact("b", "techno", "release-group-one")]
            )
        with self.assertRaisesRegex(ValueError, "artist-feature pair"):
            assert_feature_holdout_isolation(train, [FeatureFact("a", "ambient", "reissue-two")])

    def test_positive_recovery_keeps_cold_and_unseen_features_in_denominator(self) -> None:
        train = [
            FeatureFact("a", "ambient", "a-source"),
            FeatureFact("b", "drone", "b-source"),
        ]
        held = [
            FeatureFact("a", "drone", "held-a"),
            FeatureFact("cold", "ambient", "held-cold"),
            FeatureFact("b", "new", "held-b"),
        ]
        report = evaluate_feature_recovery(train, held, {"a": ("drone",)})
        self.assertEqual(report["positive_pair_count"], 3)
        self.assertEqual(report["cold_artist_positive_count"], 1)
        self.assertEqual(report["unseen_feature_positive_count"], 1)
        self.assertEqual(report["recall"], 1 / 3)
        self.assertFalse(report["absence_is_negative"])

    def test_recovery_rejects_train_leakage_and_oracle_candidate_identities(self) -> None:
        train = [FeatureFact("a", "ambient", "one")]
        with self.assertRaisesRegex(ValueError, "evidence group"):
            evaluate_feature_recovery(train, [FeatureFact("b", "drone", "one")], {})
        held = [FeatureFact("a", "drone", "two")]
        for ranking in (("ambient",), ("drone",)):
            with self.assertRaisesRegex(ValueError, "unknown or already observed"):
                evaluate_feature_recovery(train, held, {"a": ranking})

    def test_topic_artifact_evaluation_requires_frozen_bytes_and_complete_identities(self) -> None:
        cache = Path(__file__).resolve().parents[2] / ".cache"
        with TemporaryDirectory(dir=cache) as temporary:
            directory = Path(temporary)
            primary = {level: {"one": "a", "two": "a"} for level in ("broad", "sub", "micro")}
            files = {
                "communities.json": b"{}\n",
                "assignments.jsonl": b"{}\n",
                "primary-assignments.json": canonical_json(primary),
                "musical-profiles.jsonl": b"\n".join(
                    canonical_json({"artist_mbid": artist, "musical_features": ["ambient"]})
                    for artist in ("one", "two")
                ),
            }
            for name, content in files.items():
                (directory / name).write_bytes(content)
            report = {
                "revision": "emergent-source-music-topics-v1",
                "scope": "local_research_only",
                "historical_inputs_used": False,
                "artist_names_used_for_construction": False,
                "features_sha256": "1" * 64,
                "files": {
                    name: {"sha256": sha256_file(directory / name)[0], "bytes": len(content)}
                    for name, content in files.items()
                },
            }
            report["output_sha256"] = sha256_json(report)
            (directory / "report.json").write_bytes(canonical_json(report))
            result = evaluate_topic_run(directory=directory, output=directory / "evaluation.json")
            self.assertTrue(result["all_identical_profile_constraints_passed"])
            self.assertFalse(result["spotify_or_every_noise_parity_established"])
            (directory / "musical-profiles.jsonl").write_bytes(b"changed source identities")
            with self.assertRaisesRegex(ValueError, "bytes differ"):
                evaluate_topic_run(directory=directory, output=directory / "other-evaluation.json")
