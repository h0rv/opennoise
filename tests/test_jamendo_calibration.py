"""Synthetic tests only: no retained human outcomes are fitted here."""

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from typing import Any
from unittest.mock import patch

import numpy as np

from opennoise.ml import jamendo_calibration as cal
from opennoise.ml import jamendo_human_mood as base


class CalibrationTests(unittest.TestCase):
    def test_gradient_matches_finite_differences_and_identity_shrink(self) -> None:
        x, y, w = np.array([-2.0, 0.5, 3.0]), np.array([0.0, 1 / 3, 1.0]), np.array([0.2, 0.3, 0.5])
        point = np.array([0.6, -0.2])
        _, analytic = cal.objective(point, x, y, w)
        numeric = []
        for j in range(2):
            delta = np.zeros(2)
            delta[j] = 1e-6
            numeric.append(
                (
                    cal.objective(point + delta, x, y, w)[0]
                    - cal.objective(point - delta, x, y, w)[0]
                )
                / 2e-6
            )
        np.testing.assert_allclose(analytic, numeric, atol=1e-9)
        np.testing.assert_allclose(cal.weights([1, 1, 2]), [0.25, 0.25, 0.5])

    def test_convex_fit_shrinks_overconfidence_without_reversing_order(self) -> None:
        p = np.array([0.01, 0.05, 0.95, 0.99])
        y = np.array([1 / 3, 1 / 3, 2 / 3, 2 / 3])
        fit = cal.fit_calibrator(p, y, [1, 2, 3, 4])
        self.assertIsNone(fit.reason)
        self.assertGreaterEqual(fit.slope, 0)
        self.assertLess(fit.slope, 1)
        self.assertEqual(sorted(cal.apply(fit, v) for v in p), [cal.apply(fit, v) for v in p])

    def test_degenerate_fallback_preserves_exact_probabilities(self) -> None:
        for p, y, groups, reason in [
            ([], [], [], "insufficient_calibration_components"),
            ([0.0, 1.0], [0.0, 1.0], [1, 1], "insufficient_calibration_components"),
            ([0.1, 0.3], [1.0, 1.0], [1, 2], "one_class_calibration"),
        ]:
            model = cal.fit_calibrator(np.array(p), np.array(y), groups)
            self.assertEqual(model.reason, reason)
            self.assertEqual(cal.apply(model, 0.0), 0.0)
            self.assertEqual(cal.apply(model, 1.0), 1.0)
        with self.assertRaises(ValueError):
            cal.fit_calibrator(np.array([np.nan]), np.array([1.0]), [1])

    def test_constant_input_is_regularized_and_optimizer_failure_stops(self) -> None:
        model = cal.fit_calibrator(np.array([0.4, 0.4]), np.array([0.0, 1.0]), [1, 2])
        self.assertTrue(model.constant_input)
        self.assertIsNone(model.reason)
        with patch.object(cal, "minimize") as minimize:
            minimize.return_value.success = False
            with self.assertRaises(ValueError):
                cal.fit_calibrator(np.array([0.2, 0.8]), np.array([0.0, 1.0]), [1, 2])

    def test_role_and_target_leakage_isolation(self) -> None:
        rows = [
            base.Observation(
                i,
                i,
                i,
                str(i),
                "30",
                ("genre---a",) if i % 2 else ("genre---b",),
                ("happy", "not_happy", "happy") if i % 3 else ("not_happy",) * 3,
            )
            for i in range(1, 101)
        ]
        groups = {r.track_id: r.track_id for r in rows}
        model, calibration, _ = cal.fit_outer(rows, groups, 0)
        self.assertIsNotNone(model)
        self.assertIsNotNone(calibration)
        assert model is not None
        assert calibration is not None
        changed = [
            replace(r, tags=("genre---OUTER_ONLY",), votes=("happy",) * 3)
            if cal.role(groups[r.track_id], 0) == "query"
            else r
            for r in rows
        ]
        other, other_cal, _ = cal.fit_outer(changed, groups, 0)
        assert other is not None
        self.assertEqual(model.vocabulary, other.vocabulary)
        np.testing.assert_array_equal(model.happy, other.happy)
        self.assertEqual(calibration, other_cal)
        changed = [
            replace(r, votes=("happy",) * 3)
            if cal.role(groups[r.track_id], 0) == "calibration"
            else r
            for r in rows
        ]
        other, _, _ = cal.fit_outer(changed, groups, 0)
        assert other is not None
        np.testing.assert_array_equal(model.happy, other.happy)
        self.assertEqual(model.prior, other.prior)

    def test_proper_score_noise_coverage_and_reliability_denominators(self) -> None:
        records: list[dict[str, Any]] = [
            {
                "component_id": g,
                "eligibility_reason": None,
                "probabilities": p,
                "happy_fraction": y,
                "calibration_reason": None,
            }
            for g, p, y in [
                (1, [0.2, 0.4, 0.5], 1 / 3),
                (1, [0.8, 0.6, 0.5], 2 / 3),
                (2, [0.2, 0.4, 0.5], 1.0),
            ]
        ]
        records.append(
            {
                "component_id": 3,
                "eligibility_reason": "wrong_vote_count",
                "probabilities": None,
                "happy_fraction": None,
                "calibration_reason": None,
            }
        )
        result = cal.summary(records)
        self.assertEqual(result["nominated"], 4)
        self.assertEqual(result["eligible"], 3)
        self.assertEqual(result["coverage_all_nominated"], 0.75)
        for name in cal.METHODS:
            m = result["methods"][name]["metrics"]
            self.assertAlmostEqual(
                m["track_individual_vote_brier"] - m["track_mean_target_squared_error"],
                result["vote_noise_track"],
            )
            self.assertAlmostEqual(
                m["component_equal_individual_vote_brier"]
                - m["component_equal_mean_target_squared_error"],
                result["vote_noise_component"],
            )
            self.assertAlmostEqual(
                sum(b["weight"] for b in result["methods"][name]["reliability"]), 2.0
            )
        records.append(
            {
                "component_id": 4,
                "eligibility_reason": None,
                "probabilities": None,
                "happy_fraction": 1.0,
                "calibration_reason": "no_inner_fit",
            }
        )
        result = cal.summary(records)
        self.assertTrue(result["conditional_on_prediction_availability"])
        self.assertEqual(result["missing_eligible_predictions"], 1)
        self.assertEqual(result["eligible_components"], 3)

    def test_no_scored_queries_are_null_not_zero(self) -> None:
        result = cal.summary([])
        self.assertIsNone(result["calibrated_minus_nb"]["component_equal_individual_vote_brier"])
        self.assertEqual(result["per_component"], [])

    def test_seal_and_role_tampering_rejected_without_fit(self) -> None:
        rows = [base.Observation(1, 1, 1, "1", "30")]
        with tempfile.TemporaryDirectory() as tmp:
            sealed = Path(tmp) / "sealed"
            protocol = (
                Path(__file__).parents[1]
                / "data/recipes/jamendo-calibration-20261017/protocol.json"
            )
            with (
                patch.object(base, "_load", return_value=rows),
                patch.object(
                    cal, "predictions", side_effect=AssertionError("No fitting during freeze/load")
                ),
            ):
                cal.freeze(Path(tmp), protocol, sealed)
                pin = base.digest(sealed / "seal.json")
                self.assertEqual(cal.load(sealed, pin), rows)
                with self.assertRaises(ValueError):
                    cal.load(sealed, "0" * 64)
                ledger = json.loads((sealed / "roles.json").read_text())
                ledger[0]["roles"][0] = "wrong"
                (sealed / "roles.json").write_text(json.dumps(ledger))
                with self.assertRaises(ValueError):
                    cal.load(sealed, pin)

    def test_output_rejects_existing_directory_and_symlinks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaises(ValueError):
                cal.fresh(root)
            (root / "link").symlink_to(root)
            with self.assertRaises(ValueError):
                cal.fresh(root / "link" / "new")


if __name__ == "__main__":
    unittest.main()
