"""Frozen fractional math, reserved-role isolation and physical research custody."""

import json
import math
import tempfile
import unittest
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any, override
from unittest.mock import patch

import numpy as np

from opennoise.ml import jamendo_style_prediction as study

UNJUDGED_ID = 10
RESERVED_ID = 99

ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = ROOT / "data/recipes/jamendo-style-prediction-20261020/protocol.json"
RAW = Path("/workspace/jamendo-human-genre-20261019/source")


def inputs() -> study.Inputs:
    """Locate retained approved bytes only; never download missing research data."""
    return study.Inputs(
        RAW / "autotagging-test.tsv",
        RAW / "music-classification-annotations-raw.tsv",
        PROTOCOL,
        study.PROTOCOL,
    )


def artist(identity: int, fold: int, *, complete: bool = True) -> dict[str, Any]:
    """Build a clearly synthetic one-component artist with five fractional targets."""
    return {
        "artist_id": identity,
        "component_id": identity * 10,
        "fold": fold,
        "status": "development",
        "track_count": 2,
        "album_ids": [identity],
        "tag_counts": {"genre---shared": 1, f"genre---fold{fold}": 2},
        "attributes": {
            a: {"eligible_tracks": 2, "positive_votes": 3, "negative_votes": 3}
            for a in study.ATTRIBUTES
        },
        "complete": complete,
        "robust": complete,
    }


class PoisonCells(list[str]):
    @override
    def __iter__(self) -> Iterator[str]:
        raise AssertionError("Reserved trailing fields were interpreted")


class StylePredictionMathTests(unittest.TestCase):
    def test_reserved_poison_fields_skip_both_extractors_and_have_no_containers(self) -> None:
        identity = {"artist_id": 1, "track_id": 10, "component_id": 10, "fold": 4}
        cells = PoisonCells(["genre---INVALID", "mood_sad---malformed", "mood_sad---duplicate"])
        for human in (False, True):
            with (
                patch.object(
                    study, "genre_fields", side_effect=AssertionError("genre access")
                ) as genre,
                patch.object(
                    study, "style_fields", side_effect=AssertionError("style access")
                ) as style,
            ):
                row = study.role_row(identity, cells, human=human)
                genre.assert_not_called()
                style.assert_not_called()
                self.assertEqual(row, {**identity, "status": "reserved_skipped"})

    def test_literal_tokens_and_genre_only_no_aliases_or_instrument_features(self) -> None:
        self.assertEqual(
            study.genre_fields(
                ["genre---rock", "genre---rock", "instrument---guitar", "mood/theme---sad"]
            ),
            {"genre---rock"},
        )
        with self.assertRaisesRegex(ValueError, "Noncanonical"):
            study.genre_fields(["genre---Rock"])
        parsed = study.style_fields(["mood_sad---sad,not_sad,sad", "mood_party---party,party"])
        self.assertEqual(parsed["sad"], {"reason": None, "vote_count": 3, "positive_votes": 2})
        self.assertEqual(parsed["party"]["reason"], "wrong_vote_count")
        self.assertEqual(parsed["relaxed"]["reason"], "missing_votes")
        self.assertEqual(
            study.style_fields(["mood_sad---sad,NOT_SAD,sad"])["sad"]["reason"], "invalid_vote"
        )
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            study.style_fields(["mood_sad---sad,not_sad,sad"] * 2)

    def test_sum_bce_ridge_objective_and_gradient_independent_scalar_example(self) -> None:
        x = np.array([[0.0], [1.0]])
        y = np.array([0.0, 1.0])
        theta = np.array([0.2, -0.4])
        value, gradient = study.objective(theta, x, y)
        expected = (
            sum(
                math.log1p(math.exp(b + w * t)) - u * (b + w * t)
                for t, u in zip(x[:, 0], y, strict=True)
                for b, w in [theta]
            )
            + 0.5 * theta[1] ** 2
        )
        self.assertAlmostEqual(value, expected, places=13)
        for i in range(2):
            delta = np.zeros(2)
            delta[i] = 1e-6
            numerical = (
                study.objective(theta + delta, x, y)[0] - study.objective(theta - delta, x, y)[0]
            ) / 2e-6
            self.assertAlmostEqual(gradient[i], numerical, places=8)

    def test_unpenalized_bias_has_analytic_fractional_intercept_solution(self) -> None:
        y = np.array([0, 0, 0, 0, 0, 0.5, 0.5, 1.0])
        model = study.fit_one(np.empty((len(y), 0)), y)
        self.assertEqual(model["coefficients"], [])
        self.assertAlmostEqual(model["bias"], math.log(0.25 / 0.75), places=5)
        self.assertLessEqual(model["gradient_inf_norm"], 1e-5)

    def test_no_finite_optimum_and_optimizer_failure_are_explicit_no_fallback(self) -> None:
        with patch.object(study, "minimize") as optimizer:
            for constant in (0.0, 1.0):
                with self.assertRaisesRegex(ValueError, "Unsupported finite"):
                    study.fit_one(np.ones((6, 1)), np.full(6, constant))
            optimizer.assert_not_called()
        failed = SimpleNamespace(success=False, x=np.zeros(2))
        with (
            patch.object(study, "minimize", return_value=failed),
            self.assertRaisesRegex(study.LogisticContractError, "convergence") as stopped,
        ):
            study.fit_one(np.ones((6, 1)), np.full(6, 0.5))
        self.assertFalse(stopped.exception.diagnostics["optimizer_success"])
        self.assertEqual(stopped.exception.diagnostics["gradient_inf_maximum"], 1e-5)

    def test_raw_frequency_uses_all_tracks_and_target_uses_equal_eligible_tracks(self) -> None:
        row = artist(1, 0)
        row["track_count"] = 4
        self.assertEqual(study.frequencies([row], ["genre---shared"]).tolist(), [[0.25]])
        self.assertEqual(study.target([row]).tolist(), [[0.5] * 5])

    def test_knn_positive_ties_component_order_convex_endpoints_and_empty_fallback(self) -> None:
        labeled = [artist(3, 0), artist(1, 1), artist(2, 2)]
        y = np.array([[1.0] * 5, [0.0] * 5, [0.5] * 5])
        p, edges = study.knn_prediction(np.array([0.5, 0.5, 0]), labeled, y, np.full(5, 0.4))
        self.assertEqual([r["artist_id"] for r in edges], [1, 3])
        self.assertEqual(p.tolist(), [0.5] * 5)
        endpoint, _ = study.knn_prediction(np.array([0.25, 0, 0]), labeled, y, np.full(5, 0.4))
        self.assertEqual(endpoint.tolist(), [1.0] * 5)
        fallback, edges = study.knn_prediction(np.zeros(3), labeled, y, np.full(5, 0.4))
        self.assertEqual(fallback.tolist(), [0.4] * 5)
        self.assertEqual(edges, [])
        labeled[1]["component_id"] = labeled[0]["component_id"]
        with self.assertRaisesRegex(ValueError, "one-component"):
            study.knn_prediction(np.ones(3), labeled, y, np.full(5, 0.4))

    def test_training_only_vocab_and_roles_preserve_unjudged_predictions_no_reserved_input(
        self,
    ) -> None:
        rows = [artist(i + 1, i) for i in range(4)]
        rows.append(artist(UNJUDGED_ID, 0, complete=False))
        rows[-1]["tag_counts"]["genre---unjudged"] = 1
        rows.append(
            {
                "artist_id": 99,
                "component_id": 990,
                "fold": 4,
                "status": "reserved_skipped",
                "track_count": 1,
                "album_ids": [99],
            }
        )

        def fit(x: np.ndarray, _y: np.ndarray) -> dict[str, Any]:
            return {"bias": 0.0, "coefficients": [0.0] * x.shape[1]}

        with patch.object(study, "fit_one", side_effect=fit) as fitter:
            banks, predictions = study.predict(rows)
        self.assertEqual(fitter.call_count, 20)
        for bank in banks:
            self.assertNotIn(f"genre---fold{bank['fold']}", bank["vocabulary"])
            self.assertNotIn(99, bank["training_metadata_artist_ids"])
            self.assertNotIn(99, bank["training_artist_ids"])
            if bank["fold"] != 0:
                self.assertIn("genre---unjudged", bank["vocabulary"])
        unjudged = next(r for r in predictions if r["artist_id"] == UNJUDGED_ID)
        self.assertFalse(unjudged["scored"])
        self.assertEqual(np.array(unjudged["probabilities"]).shape, (3, 5))
        reserved = next(r for r in predictions if r["artist_id"] == RESERVED_ID)
        self.assertNotIn("probabilities", reserved)
        self.assertNotIn("attributes", reserved)
        self.assertNotIn("tag_counts", reserved)

    def test_failed_second_head_reports_context_and_never_retries(self) -> None:
        rows = [artist(i + 1, i) for i in range(4)]
        calls = []
        failed_head = 2

        def fit(x: np.ndarray, _y: np.ndarray) -> dict[str, Any]:
            calls.append(len(x))
            if len(calls) == failed_head:
                raise study.LogisticContractError({"synthetic": True})
            return {"bias": 0.0, "coefficients": [0.0] * x.shape[1]}

        with (
            patch.object(study, "fit_one", side_effect=fit),
            self.assertRaises(study.LogisticContractError) as stopped,
        ):
            study.predict(rows)
        self.assertEqual(len(calls), 2)
        self.assertEqual(
            stopped.exception.diagnostics,
            {"synthetic": True, "fold": 0, "attribute": "electronic", "attempted_head": 2},
        )

    def test_individual_vote_loss_is_not_squared_error_and_clipping_is_log_only(self) -> None:
        p = np.full((1, 3, 5), 0.25)
        y = np.full((1, 1, 5), 1 / 3)
        loss, counts = study.loss_parts(p, y)
        self.assertAlmostEqual(loss[0, 0, 0, 2, 1], 0.25**2 - 2 * 0.25 / 3 + 1 / 3)
        self.assertNotAlmostEqual(loss[0, 0, 0, 2, 1], (0.25 - 1 / 3) ** 2)
        self.assertAlmostEqual(loss[0, 0, 0, 0, 1], (1 / 3) * 0.75**2)
        self.assertAlmostEqual(loss[0, 0, 0, 1, 1], (2 / 3) * 0.25**2)
        extreme = np.array([[[0.0] * 5, [1.0] * 5, [0.25] * 5]])
        copied = extreme.copy()
        losses, counts = study.loss_parts(extreme, y)
        np.testing.assert_array_equal(extreme, copied)
        self.assertTrue(np.isfinite(losses).all())
        self.assertEqual(counts["positive_nonzero_term"][0], [1] * 5)
        self.assertEqual(counts["negative_nonzero_term"][1], [1] * 5)


class StylePredictionCustodyTests(unittest.TestCase):
    @override
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.fake = study.Inputs(
            self.root / "metadata", self.root / "human", PROTOCOL, study.PROTOCOL
        )

    def stage(self) -> tuple[Path, str]:
        """Seal a synthetic count payload under mocked source validation only."""
        directory = self.root / "census"
        files = {"census.json": {"identity": "synthetic", "support": {"gate": False}}}
        with patch.object(study, "validate", return_value={"source": {}, "rights": {}}):
            pin = study.publish(
                directory,
                {
                    **files,
                    "seal.json": study.receipt(self.fake, files, "style-prediction-census-v1"),
                },
                self.fake.paths,
            )
        return directory, pin

    def test_whitespace_extra_files_and_resealed_float_size_fail_physical_contract(self) -> None:
        directory, pin = self.stage()
        with patch.object(study, "validate", return_value={"source": {}, "rights": {}}):
            actual = (directory / "census.json").read_bytes()
            (directory / "census.json").write_bytes(b" " + actual)
            with self.assertRaisesRegex(ValueError, "Physical"):
                study.load_stage(self.fake, directory, pin, result=False)
            (directory / "census.json").write_bytes(actual)
            (directory / "extra.json").write_text("{}")
            with self.assertRaisesRegex(ValueError, "inventory"):
                study.load_stage(self.fake, directory, pin, result=False)
            (directory / "extra.json").unlink()
            seal = json.loads((directory / "seal.json").read_bytes())
            seal["files"]["census.json"]["bytes"] = float(seal["files"]["census.json"]["bytes"])
            (directory / "seal.json").write_bytes(study.base.encoded(seal))
            with self.assertRaisesRegex(ValueError, "Physical"):
                study.load_stage(
                    self.fake, directory, study.base.digest(directory / "seal.json"), result=False
                )

    def test_atomic_fit_failure_existing_output_and_combined_size_cap(self) -> None:
        directory, pin = self.stage()
        output = self.root / "result"
        with (
            patch.object(study, "compute", side_effect=ValueError("Frozen convergence failed")),
            self.assertRaisesRegex(ValueError, "convergence"),
        ):
            study.run(self.fake, directory, pin, output)
        self.assertFalse(output.exists())
        output.mkdir()
        with patch.object(study, "compute") as compute:
            with self.assertRaisesRegex(ValueError, "Fresh"):
                study.run(self.fake, directory, pin, output)
            compute.assert_not_called()
        with patch.object(study, "MAX_BYTES", 10), self.assertRaisesRegex(ValueError, "Combined"):
            study.check_combined(directory, {"receipt.json": {}})

    def test_source_protocol_wrong_pin_fails_before_source_or_optimizer(self) -> None:
        invalid = study.Inputs(self.root / "absent", self.root / "absent2", PROTOCOL, "0" * 64)
        with (
            patch.object(study.native, "parse") as parse,
            patch.object(study, "minimize") as optimizer,
        ):
            with self.assertRaisesRegex(ValueError, "protocol"):
                study.source(invalid)
            parse.assert_not_called()
            optimizer.assert_not_called()

    @unittest.skipUnless(
        (RAW / "autotagging-test.tsv").is_file(),
        "Approved retained NC raw source unavailable; no download attempted",
    )
    def test_actual_full_identity_and_prefit_counts_without_old_model_calls(self) -> None:
        with patch.object(study, "minimize", side_effect=AssertionError("Census fit")) as fit:
            report = study.source(inputs())
            fit.assert_not_called()
        support = report["support"]
        self.assertEqual(
            (support["metadata_tracks"], support["artists"], support["components"]),
            (11565, 713, 713),
        )
        self.assertEqual(
            (
                support["development_artists"],
                support["complete"],
                support["robust"],
                support["reserved_artists"],
                support["reserved_tracks"],
            ),
            (558, 547, 446, 155, 2716),
        )
        self.assertEqual([r["vocabulary_size"] for r in support["cells"]], [87] * 4)
        for row in report["artists"]:
            if row["status"] == "reserved_skipped":
                self.assertNotIn("tag_counts", row)
                self.assertNotIn("attributes", row)
        self.assertEqual(
            report["accessor_counts"],
            {
                "reserved_genre_skipped": 2716,
                "reserved_style_skipped": 2716,
                "development_genre_accessed": 8849,
                "development_style_accessed": 8849,
            },
        )
