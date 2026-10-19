"""Independent tiny-matrix, linear-gain and custody checks for the frozen artist task."""

import copy
import math
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from opennoise.ml import jamendo_artist_coherence as study
from opennoise.ml import jamendo_human_genre as base


def features() -> study.FeatureRows:
    """Keep an empty gallery artist and query-only tag to expose IDF/vocabulary leakage."""
    return study.FeatureRows(
        np.array([1, 2, 3, 4]),
        np.array([100, 30, 20, 40]),
        np.array([0, 1, 1, 1]),
        np.array([2.0, 1.0, 1.0, 1.0]),
        (
            {"genre---rock": 1, "instrument---flute": 2, "genre---queryonly": 2},
            {"genre---rock": 1},
            {"genre---jazz": 1, "instrument---flute": 1},
            {},
        ),
    )


def target(c: int) -> np.ndarray:
    """Provide one observed synthetic categorical vote distribution."""
    result = np.zeros(9)
    result[c] = 1
    return result


class ArtistCoherenceTests(unittest.TestCase):
    """Check the actual feature/rank/evaluation split without real-data outcome selection."""

    def test_gallery_only_df_tf_idf_and_one_global_block_norm(self) -> None:
        f = features()
        bank = study.build_index(f, 0)
        self.assertEqual(bank.vocabulary, ("genre---jazz", "genre---rock", "instrument---flute"))
        self.assertNotIn("genre---queryonly", bank.vocabulary)
        self.assertEqual(bank.unseen_query_tags, (("genre---queryonly",),))
        np.testing.assert_array_equal(bank.df, [1, 1, 1])
        expected = math.log(4 / 2) + 1  # N=3 includes the empty gallery artist.
        np.testing.assert_allclose(bank.idf, [expected] * 3)
        self.assertAlmostEqual(bank.query_norms[0][0], 0.5 * expected)
        self.assertAlmostEqual(bank.query_norms[1][0], math.sqrt(0.5**2 + 1) * expected)
        np.testing.assert_allclose(
            bank.query_units[1][0], [0, 0.5 / math.sqrt(1.25), 1 / math.sqrt(1.25)]
        )
        baseline = study.rank(f, bank, 0)[1]["positive_order"]
        candidate = study.rank(f, bank, 1)[1]["positive_order"]
        self.assertEqual([a for a, _ in baseline], [2])
        self.assertEqual([a for a, _ in candidate], [3, 2])
        self.assertAlmostEqual(candidate[0][1], 1 / math.sqrt(2.5))

    def test_exact_component_then_artist_ties_no_zero_padding(self) -> None:
        f = features()
        f.counts[2].clear()
        f.counts[2]["genre---rock"] = 1
        bank = study.build_index(f, 0)
        result = study.rank(f, bank, 0)[1]
        self.assertEqual([a for a, _ in result["positive_order"]], [3, 2])
        self.assertTrue(all(score == 1 for _, score in result["positive_order"]))
        self.assertEqual(
            len(result["positive_order"]), 2
        )  # Empty artist4 is never a zero-score edge.

    def test_empty_profile_no_overlap_and_component_leak_rejected(self) -> None:
        f = features()
        f.counts[0].clear()
        bank = study.build_index(f, 0)
        self.assertEqual(study.rank(f, bank, 0)[1]["reason"], "empty_profile")
        f = features()
        f.counts[0].clear()
        f.counts[0]["genre---jazz"] = 1
        f.counts[1].clear()
        f.counts[1]["genre---rock"] = 1
        f.counts[2].clear()
        f.counts[2]["genre---jazz"] = 1
        bank = study.build_index(f, 0)
        altered = study.Index(
            bank.query_positions,
            bank.gallery_positions,
            bank.vocabulary,
            bank.df,
            bank.idf,
            (np.zeros_like(bank.query_units[0]), bank.query_units[1]),
            bank.gallery_units,
            (np.ones_like(bank.query_norms[0]), bank.query_norms[1]),
            bank.gallery_norms,
            bank.unseen_query_tags,
        )
        self.assertEqual(study.rank(f, altered, 0)[1]["reason"], "no_eligible_positive_overlap")
        f.components[1] = f.components[0]
        with self.assertRaises(ValueError):
            study.build_index(f, 0)

    def test_linear_gain_ideal_includes_unretrieved_and_unjudged_not_negative(self) -> None:
        gallery = {i: target(0) for i in range(10, 20)}
        metric = study.query_metrics(target(0), gallery, [(99, 0.9), (10, 0.8)])
        discounts = [1 / math.log2(i + 1) for i in range(1, 11)]
        self.assertAlmostEqual(metric["idcg10"], sum(discounts))
        self.assertAlmostEqual(metric["ndcg10"], 1 / sum(discounts))
        self.assertEqual(metric["mean_vote_agreement10"], 0.1)
        self.assertEqual(metric["full_judged_slots"], 1)
        self.assertEqual(metric["full_unjudged_slots"], 1)
        self.assertEqual(metric["full_missing_slots"], 8)
        self.assertEqual(metric["full_observed_gain_mean"], 1)
        self.assertNotIn("full_ndcg", metric)
        unjudged = study.query_metrics(target(0), gallery, [(99, 0.9)])
        self.assertIsNone(unjudged["full_observed_gain_mean"])

    def test_exact_random_expectation_and_zero_idcg_denominators(self) -> None:
        gallery = {i: target(1) for i in range(10)}
        gallery[0] = target(0)
        metric = study.query_metrics(target(0), gallery, [(0, 1)])
        # One positive can occupy each of10 ranks uniformly; analytic expected DCG.
        expected = sum(1 / math.log2(i + 1) for i in range(1, 11)) / 10
        self.assertAlmostEqual(metric["random_ndcg10"], expected)
        self.assertEqual(metric["random_mean_vote_agreement10"], 0.1)
        zero = study.query_metrics(target(2), gallery, [(0, 1)])
        self.assertEqual(zero["ndcg10"], 0)
        self.assertEqual(zero["reason"], "zero_idcg")
        missing = study.query_metrics(target(0), {}, [])
        self.assertEqual(missing["ndcg10"], 0)
        self.assertEqual(missing["reason"], "no_judged_gallery")

    def test_fractional_artist_targets_mean_tracks_not_votes_or_membership(self) -> None:
        tracks = [
            {"artist_id": 1, "target_reason": None, "canonical_votes": ["rock", "rock", "pop"]},
            {"artist_id": 1, "target_reason": None, "canonical_votes": ["jazz"] * 3},
            {"artist_id": 1, "target_reason": "wrong_vote_count", "canonical_votes": ["rock"]},
        ]
        y = study.human_targets(tracks)[1]
        self.assertAlmostEqual(y[-1], 1 / 3)
        self.assertAlmostEqual(y[-3], 1 / 6)
        self.assertAlmostEqual(y[5], 0.5)
        self.assertAlmostEqual(y.sum(), 1)

    def test_feature_boundary_contains_no_human_fields_or_selection(self) -> None:
        artists = [
            {
                "artist_id": 1,
                "component_id": 10,
                "fold": 0,
                "track_ids": [1, 2, 3],
                "tag_counts": {"genre---rock": 2},
                "eligible_tracks": 0,
                "positive_classes": [False] * 9,
            }
        ]
        a = study.feature_rows(artists)
        changed = copy.deepcopy(artists)
        changed[0]["eligible_tracks"] = 3
        changed[0]["positive_classes"] = [True] * 9
        b = study.feature_rows(changed)
        np.testing.assert_array_equal(a.track_counts, [3])
        self.assertEqual(a.counts, b.counts)
        self.assertFalse(hasattr(a, "targets"))
        self.assertFalse(hasattr(a, "eligible_tracks"))

    def test_paired_bootstrap_and_fractional_class_weighted_summary(self) -> None:
        rows = []
        for i, (baseline, candidate) in enumerate(((0.1, 0.3), (0.3, 0.9))):
            arms = {}
            for arm, value in zip(study.ARMS, (baseline, candidate), strict=True):
                arms[arm] = {
                    "reason": None,
                    "full_judged_slots": 10,
                    "full_unjudged_slots": 0,
                    "full_missing_slots": 0,
                    "metrics": {
                        "ndcg10": value,
                        "mean_vote_agreement10": value / 2,
                        "random_ndcg10": 0.05,
                        "random_mean_vote_agreement10": 0.025,
                        "reason": None,
                    },
                }
            rows.append({"artist_id": i, "component_id": i, "target": [1] + [0] * 8, "arms": arms})
        bootstrap = study.bootstrap(rows, 20261019)
        key = "genre_instrument_tfidf-minus-genre_tfidf"
        self.assertAlmostEqual(bootstrap["comparisons"][key]["ndcg10"]["difference"], 0.4)
        np.testing.assert_allclose(bootstrap["comparisons"][key]["ndcg10"]["interval"], [0.2, 0.6])
        weighted = study.summary(rows, np.array([1.0, 3.0]))
        self.assertAlmostEqual(weighted["scores"][study.ARMS[0]]["ndcg10"], 0.25)
        self.assertEqual(weighted["weight_mass"], 4)
        self.assertEqual(weighted["positive_weight_queries"], 2)
        empty = study.bootstrap([], 20261020)
        self.assertEqual(empty["valid_draws"], 0)
        self.assertIsNone(empty["comparisons"][key]["ndcg10"]["difference"])

    def test_fractional_gain_is_linear_not_exponential(self) -> None:
        q = np.array([2 / 3, 1 / 3] + [0.0] * 7)
        gallery = {i: np.array([0.5, 0.5] + [0.0] * 7) for i in range(10)}
        gallery[0] = target(0)
        result = study.query_metrics(q, gallery, [(1, 0.5)])
        ideal = 2 / 3 + 0.5 * sum(1 / math.log2(i + 1) for i in range(2, 11))
        self.assertAlmostEqual(result["idcg10"], ideal)
        self.assertAlmostEqual(result["ndcg10"], 0.5 / ideal)
        self.assertEqual(result["mean_vote_agreement10"], 0.05)

    def test_sealed_stage_whitespace_runtime_and_resealed_size_types(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            inputs = study.Inputs(root / "m", root / "h", root / "p", study.PROTOCOL)
            files = {"census.json": {"fits": 0}}
            seal = study.receipt(inputs, files, "test")
            output = root / "census"
            pin = study.publish(output, {**files, "seal.json": seal}, inputs.paths)
            study.load_stage(inputs, output, pin, {"census.json"}, "test", "seal.json")
            with (output / "census.json").open("ab") as stream:
                stream.write(b" ")
            with self.assertRaises(ValueError):
                study.load_stage(inputs, output, pin, {"census.json"}, "test", "seal.json")
            (output / "census.json").write_bytes(base.encoded(files["census.json"]))
            changed = copy.deepcopy(seal)
            changed["files"]["census.json"]["bytes"] = float(
                changed["files"]["census.json"]["bytes"]
            )
            (output / "seal.json").write_bytes(base.encoded(changed))
            with self.assertRaises(ValueError):
                study.load_stage(
                    inputs,
                    output,
                    base.digest(output / "seal.json"),
                    {"census.json"},
                    "test",
                    "seal.json",
                )

    def test_support_gate_fail_closed_before_index_math(self) -> None:
        artists = [
            {
                "artist_id": 1,
                "component_id": 1,
                "fold": 0,
                "track_ids": [1],
                "tag_counts": {},
                "eligible_tracks": 0,
                "positive_classes": [False] * 9,
            }
        ]
        tracks = [{"album_id": 1, "taxonomy_nominated": False, "target_reason": "missing_votes"}]
        report = {"tracks": tracks, "artists": artists, "support": study.support(tracks, artists)}
        inputs = study.Inputs(Path("m"), Path("h"), Path("p"), study.PROTOCOL)
        with (
            patch.object(study, "load_stage", return_value={"census.json": report}),
            patch.object(study, "load_source", return_value=(tracks, artists)),
            patch.object(study, "build_index", side_effect=AssertionError("must not index")),
        ):
            files = study.compute(inputs, Path("census"), "pin")
        self.assertEqual(files["evaluation.json"]["status"], "support_gate_failed")
        self.assertEqual(files["evaluation.json"]["gallery_idf_index_builds"], 0)

    def test_closed_inventory_caps_and_atomic_source_pin_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            inputs = study.Inputs(
                root / "missing-metadata", root / "missing-human", root / "protocol", "0" * 64
            )
            with self.assertRaises(ValueError):
                study.census(inputs, root / "out")
            self.assertFalse((root / "out").exists())
            with patch.object(study, "MAX_BYTES", 1), self.assertRaises(ValueError):
                study.publish(root / "too-big", {"seal.json": {}}, inputs.paths)
            self.assertFalse((root / "too-big").exists())
