"""Exact style-label, role-isolation, agreement and artifact-custody regressions."""

import copy
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

import numpy as np

from opennoise.ml import jamendo_artist_style as study


def artist(a: int, fold: int, *, complete: bool = True) -> dict[str, Any]:
    """Provide independently understandable small binary-vote targets."""
    return {
        "artist_id": a,
        "component_id": a * 10,
        "fold": fold,
        "track_ids": [a],
        "tag_counts": {},
        "attributes": {
            x: {"positive_votes": a % 4, "negative_votes": 3 - a % 4, "eligible_tracks": 1}
            for x in study.ATTRIBUTES
        },
        "complete": complete,
        "robust": False,
    }


class ArtistStyleTests(unittest.TestCase):
    """Test selected labels without looking at additional taxonomies or outcomes."""

    def test_exact_positive_negative_disagreement_and_invalid(self) -> None:
        self.assertEqual(
            study.selected_votes(["mood_sad---sad,not_sad,sad"], "sad"),
            (["sad", "not_sad", "sad"], None),
        )
        self.assertEqual(study.selected_votes(["mood_sad---"], "sad"), (None, "missing_votes"))
        self.assertEqual(study.selected_votes(["mood_sad---sad,sad"], "sad")[1], "wrong_vote_count")
        self.assertEqual(study.selected_votes(["mood_sad---sad,SAD,sad"], "sad")[1], "invalid_vote")
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            study.selected_votes(["mood_sad---sad"] * 2, "sad")

    def test_reserved_role_precedes_selected_cell_access(self) -> None:
        identity = {"track_id": 1, "artist_id": 2, "component_id": 3}
        with patch.object(
            study, "selected_votes", side_effect=AssertionError("reserved label access")
        ):
            row = study.style_row(identity, 4, ["mood_sad---not_sad,sad,sad"])
        self.assertEqual(row, {**identity, "status": "reserved"})
        self.assertNotIn("attributes", row)

    def test_expected_fractional_agreement_positive_negative_macro(self) -> None:
        q = np.array([0, 0.25, 0.5, 0.75, 1])
        c = np.array([[1, 0.5, 0.25, 0, 1]])
        result = study.gains(q, c)[0]
        for j in range(5):
            self.assertAlmostEqual(result[j, 0], q[j] * c[0, j])
            self.assertAlmostEqual(result[j, 1], (1 - q[j]) * (1 - c[0, j]))
            self.assertAlmostEqual(result[j, 2], result[j, 0] + result[j, 1])
        np.testing.assert_allclose(result[5], result[:5].mean(axis=0))

    def test_equal_track_probability_and_no_reserved_target_container(self) -> None:
        rows = [artist(1, 0), artist(2, 4), artist(3, 1, complete=False)]
        rows[0]["attributes"]["sad"] = {
            "positive_votes": 4,
            "negative_votes": 2,
            "eligible_tracks": 2,
        }
        observed = study.targets(rows)
        self.assertEqual(set(observed), {1})
        self.assertAlmostEqual(observed[1][-1], 2 / 3)

    def test_role_filter_then_complete_filter_fixed_ten_missing_slots(self) -> None:
        rows = [artist(1, 0), artist(2, 1), artist(3, 1, complete=False), artist(4, 4)]
        rankings = {
            arm: {
                r["artist_id"]: {"positive_order": [(4, 0.99), (3, 0.8), (2, 0.5)], "reason": None}
                for r in rows
            }
            for arm in study.old.ARMS
        }
        with patch.object(study, "bootstrap", return_value={}):
            results, _ = study.evaluate(rows, rankings)
        q = results[0]
        self.assertEqual(
            results[-1], {"artist_id": 4, "component_id": 40, "fold": 4, "status": "reserved"}
        )
        for arm in study.old.ARMS:
            r = q["arms"][arm]
            self.assertEqual([e["artist_id"] for e in r["full_development_top10"]], [3, 2])
            self.assertEqual([e["artist_id"] for e in r["condensed_top10"]], [2])
            self.assertEqual(
                (r["full_judged_slots"], r["full_unjudged_slots"], r["full_missing_slots"]),
                (1, 1, 8),
            )
            self.assertEqual(r["historical_catalog_reserved_slots"], 1)
        expected = study.gains(np.full(5, 1 / 3), np.full((1, 5), 2 / 3))[0]
        np.testing.assert_allclose(q["metrics"][0], expected / 10)
        np.testing.assert_allclose(q["metrics"][2], expected)

    def test_support_failure_prevents_all_numeric_reconstruction(self) -> None:
        report = {"artists": [], "tracks": [], "support": {"gate": False}}
        with (
            patch.object(study, "load_stage", return_value={"census.json": report}),
            patch.object(study, "source", return_value=report),
            patch.object(study.old, "build_index", side_effect=AssertionError("numeric call")),
        ):
            result = study.compute(
                study.Inputs(Path("x"), Path("x"), Path("x"), study.PROTOCOL, Path("x")),
                Path("unused"),
                "unused",
            )
        self.assertEqual(result["evaluation.json"]["status"], "support_gate_failed")

    def test_physical_bytes_closed_inventory_and_external_pin(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            directory = root / "stage"
            data = root / "source"
            data.write_text("input")
            inputs = study.Inputs(data, data, data, study.PROTOCOL, root / "history")
            files = {"census.json": {"support": {"gate": False}}}
            seal = study.receipt(inputs, files, "artist-style-census-v1")
            pin = study.old.publish(directory, {**files, "seal.json": seal}, inputs.paths)
            self.assertEqual(
                study.load_stage(
                    inputs, directory, pin, {"census.json"}, "artist-style-census-v1", "seal.json"
                ),
                files,
            )
            with self.assertRaisesRegex(ValueError, "External"):
                study.load_stage(
                    inputs,
                    directory,
                    "0" * 64,
                    {"census.json"},
                    "artist-style-census-v1",
                    "seal.json",
                )
            payload = directory / "census.json"
            original = payload.read_bytes()
            payload.write_bytes(original + b" ")
            with self.assertRaises(ValueError):
                study.load_stage(
                    inputs, directory, pin, {"census.json"}, "artist-style-census-v1", "seal.json"
                )
            payload.write_bytes(original)
            (directory / "extra.json").write_text("{}")
            with self.assertRaises(ValueError):
                study.load_stage(
                    inputs, directory, pin, {"census.json"}, "artist-style-census-v1", "seal.json"
                )

    def test_empty_retrieval_keeps_query_and_zero_slots(self) -> None:
        rows = [artist(1, 0), artist(2, 1)]
        rankings = {
            arm: {r["artist_id"]: {"positive_order": [], "reason": "empty_profile"} for r in rows}
            for arm in study.old.ARMS
        }
        with patch.object(study, "bootstrap", return_value={}):
            results, summary = study.evaluate(rows, rankings)
        self.assertEqual(summary["overall"]["queries"], 2)
        np.testing.assert_array_equal(results[0]["metrics"][:2], np.zeros((2, 6, 3)))
        self.assertGreater(results[0]["metrics"][2][-1][-1], 0)
        self.assertIsNone(results[0]["arms"][study.old.ARMS[0]]["conditional_observed_agreement"])

    def test_one_attribute_support_failure_blocks_entire_macro(self) -> None:
        rows = [artist(a, a % 4) for a in range(1, 241)]
        for r in rows:
            if r["fold"] != 0:
                r["attributes"]["sad"]["positive_votes"] = 0
        report = study.support([], rows)
        self.assertFalse(report["gate"])
        self.assertFalse(report["folds"][0]["gate"])

    def test_source_failure_is_atomic_and_overlap_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            source.write_text("input")
            inputs = study.Inputs(source, source, source, study.PROTOCOL, root / "history")
            output = root / "output"
            with (
                patch.object(study, "source", side_effect=ValueError("custody")),
                self.assertRaisesRegex(ValueError, "custody"),
            ):
                study.census(inputs, output)
            self.assertFalse(output.exists())
            with self.assertRaises(ValueError):
                study.census(inputs, source)

    def test_retained_real_count_census_without_numeric_calls(self) -> None:
        root = Path("/workspace/jamendo-human-genre-20261019/source")
        old = Path(
            "/workspace/opennoise-jamendo-artist-coherence/.cache/jamendo-artist-coherence-20261019/results"
        )
        if not root.is_dir() or not old.is_dir():
            self.skipTest("Local NC-SA research source not distributed")
        with tempfile.TemporaryDirectory() as tmp:
            historical = Path(tmp) / "historical"
            historical.mkdir()
            for name in study.PROOF_FILES:
                (historical / name).write_bytes((old / name).read_bytes())
            inputs = study.Inputs(
                root / "autotagging-test.tsv",
                root / "music-classification-annotations-raw.tsv",
                Path("data/recipes/jamendo-artist-style-evaluation-20261019/protocol.json"),
                study.PROTOCOL,
                historical,
            )
            with patch.object(
                study.old, "build_index", side_effect=AssertionError("count census must not index")
            ):
                actual = study.source(inputs)
        self.assertEqual(actual["support"]["complete_queries"], 547)
        self.assertEqual(actual["support"]["robust_queries"], 446)
        self.assertEqual(actual["support"]["reserved_tracks"], 2716)
        self.assertNotIn(b"raw_votes", study.base.encoded(actual))
        self.assertTrue(
            all("attributes" not in r for r in actual["tracks"] if r["status"] == "reserved")
        )
        self.assertTrue(
            all("attributes" not in r for r in actual["artists"] if r["status"] == "reserved")
        )

    def test_combined_cap_counts_both_seals_before_publication(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "census"
            directory.mkdir()
            (directory / "seal.json").write_text("12345")
            files = {"receipt.json": {"x": 1}}
            bound = 5 + len(study.base.file_bytes("receipt.json", files["receipt.json"]))
            with patch.object(study, "MAX_BYTES", bound):
                study.check_combined(directory, files)
            with (
                patch.object(study, "MAX_BYTES", bound - 1),
                self.assertRaisesRegex(ValueError, "Combined"),
            ):
                study.check_combined(directory, files)
            inputs = study.Inputs(Path("x"), Path("x"), Path("x"), study.PROTOCOL, Path("x"))
            output = Path(tmp) / "out"
            with (
                patch.object(study, "source", return_value={}),
                patch.object(study, "MAX_BYTES", 1),
                self.assertRaisesRegex(ValueError, "Combined"),
            ):
                study.census(inputs, output)
            self.assertFalse(output.exists())

    def test_replay_combined_cap_precedes_reconstruction(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            directory = root / "census"
            directory.mkdir()
            (directory / "seal.json").write_text("123")
            output = root / "result"
            output.mkdir()
            (output / "receipt.json").write_text('{"census_sha256":"pin"}')
            inputs = study.Inputs(Path("x"), Path("x"), Path("x"), study.PROTOCOL, Path("x"))
            with (
                patch.object(study, "load_stage", return_value={}),
                patch.object(study, "MAX_BYTES", 1),
                patch.object(study, "compute", side_effect=AssertionError("must not compute")),
                self.assertRaisesRegex(ValueError, "Combined"),
            ):
                study.replay(inputs, directory, "pin", output, "unused")

    def test_paired_bootstrap_same_draws_all_terms(self) -> None:
        rng = np.random.Generator(np.random.PCG64(9))
        rows = [{"metrics": rng.random((3, 6, 3)).tolist()} for _ in range(4)]
        actual = study.bootstrap(rows, 42)
        data = np.array([r["metrics"] for r in rows])
        delta = np.stack(
            (data[:, 1] - data[:, 0], data[:, 0] - data[:, 2], data[:, 1] - data[:, 2]), axis=1
        )
        oracle_rng = np.random.Generator(np.random.PCG64(42))
        expected = np.array([delta[oracle_rng.integers(0, 4, 4)].mean(axis=0) for _ in range(2000)])
        np.testing.assert_array_equal(
            actual["intervals"], np.quantile(expected, [0.025, 0.975], axis=0)
        )
        self.assertEqual(actual, study.bootstrap(copy.deepcopy(rows), 42))


if __name__ == "__main__":
    unittest.main()
