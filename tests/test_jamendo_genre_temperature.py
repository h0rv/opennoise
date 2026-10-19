"""Independent math and isolation checks for the frozen multiclass temperature plan."""

import copy
import math
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

import numpy as np

from opennoise.ml import jamendo_genre_temperature as study
from opennoise.ml import jamendo_human_genre as base
from opennoise.ml import jamendo_human_mood as native


def fixture() -> tuple[list[native.Observation], dict[int, int]]:
    """Give all classes ample independent components without touching retained labels."""
    rows = [
        native.Observation(i + 1, i + 1, i + 1, f"{i + 1}.mp3", "1", ("genre---x",), (c,) * 3)
        for i, c in enumerate(base.CLASSES * 18)
    ]
    return rows, {r.track_id: r.track_id for r in rows}


def record(i: int, group: int, probability: list[float]) -> dict[str, Any]:
    """Supply one synthetic already eligible outcome for reporting checks."""
    return {
        "track_id": i,
        "component_id": group,
        "target": [1.0, *([0.0] * 8)],
        "methods": dict.fromkeys(study.METHODS, probability),
        "target_reason": None,
        "scored": True,
    }


class TemperatureTests(unittest.TestCase):
    """Check raw logits, matched outcomes, training boundaries and sealed artifacts."""

    def test_independent_raw_logit_math_and_temperature(self) -> None:
        """Include both absent and present features and all nine class priors."""
        prior = np.arange(1, 10, dtype=float) / 45
        theta = np.array([[0.1 + j * 0.02, 0.7 - j * 0.02] for j in range(9)])
        model = {
            "prior": prior.tolist(),
            "theta": theta.tolist(),
            "vocabulary": ["genre---a", "instrument---b"],
        }
        row = native.Observation(1, 1, 1, "1", "1", ("genre---a", "mood---irrelevant"))
        expected = [
            math.log(prior[j]) + math.log(theta[j, 0]) + math.log(1 - theta[j, 1]) for j in range(9)
        ]
        np.testing.assert_allclose(study.logits(model, row), expected, atol=1e-14)
        raw = [math.exp(v / 4) for v in expected]
        np.testing.assert_allclose(
            study.soften(np.array(expected), 4), [v / sum(raw) for v in raw], rtol=1e-14
        )
        self.assertEqual(
            study.soften(study.logits(model, row), 1).tolist(),
            base.predict(model, row)["genre_instrument_nb"],
        )
        with self.assertRaises(ValueError):
            study.soften(np.array(expected), 3)

    def test_empty_vocabulary_uses_raw_prior_and_softens(self) -> None:
        model = {"prior": [0.2] + [0.1] * 8, "theta": [[]] * 9, "vocabulary": []}
        row = native.Observation(1, 1, 1, "1", "1")
        np.testing.assert_array_equal(study.logits(model, row), np.log(model["prior"]))
        actual = study.soften(study.logits(model, row), 2)
        self.assertAlmostEqual(actual[0] / actual[1], math.sqrt(2))

    def test_component_safe_inner_fits_and_exact_tie(self) -> None:
        rows, groups = fixture()
        result = study.temperature_selection(rows, groups, 0)
        self.assertEqual(len(result["fits"]), 3)
        seen = []
        for cell in result["fits"]:
            self.assertFalse(set(cell["training_track_ids"]) & set(cell["validation_track_ids"]))
            for i in cell["validation_track_ids"]:
                self.assertEqual(study.inner_fold(groups[i], 0), cell["inner"])
            seen += cell["validation_track_ids"]
        self.assertCountEqual(seen, [r.track_id for r in rows])
        with patch.object(study, "logits", return_value=np.zeros(9)):
            tied = study.temperature_selection(rows, groups, 0)
        self.assertEqual(tied["temperature"], 1)
        self.assertEqual(len(set(tied["losses"])), 1)

    def test_gate_fallback_has_no_fit_or_candidate_selection(self) -> None:
        rows, groups = fixture()
        rows = [r for r in rows if r.votes != ("blues",) * 3]
        with patch.object(base, "fit", side_effect=AssertionError("must not fit")):
            result = study.temperature_selection(rows, groups, 0)
        self.assertEqual(result["temperature"], 1)
        self.assertEqual(result["reason"], "inner_training_class_support_failed")
        self.assertIsNone(result["losses"])

    def test_component_weighted_selection_objective(self) -> None:
        rows, groups = fixture()
        # Duplicate one component's rows without changing its total selection weight.
        rows += [native.Observation(1000, 1, 1, "1000", "1", (), ("alternative",) * 3)]
        groups[1000] = groups[1]
        result = study.temperature_selection(rows, groups, 0)
        saved = {r["track_id"]: r["scores"] for r in result["oof_logits"]}
        component_losses = {}
        for t in study.TEMPERATURES:
            by_component = {}
            for r in rows:
                p = study.soften(np.array(saved[r.track_id]), t)
                ll = -sum(
                    math.log(max(p[j], 1e-15)) / 3
                    for j, c in enumerate(base.CLASSES)
                    for v in r.votes or ()
                    if c == v
                )
                by_component.setdefault(groups[r.track_id], []).append(ll)
            component_losses[t] = sum(sum(v) / len(v) for v in by_component.values()) / len(
                by_component
            )
        np.testing.assert_allclose(result["losses"], list(component_losses.values()), atol=1e-14)
        self.assertEqual(
            result["temperature"], min(component_losses, key=lambda t: (component_losses[t], t))
        )

    def test_outer_queries_cannot_enter_inner_census(self) -> None:
        rows, groups = fixture()
        identities = [{"track_id": r.track_id, "component_id": groups[r.track_id]} for r in rows]
        report = study.inner_census(rows, identities)
        self.assertEqual(len(report["cells"]), 15)
        for role in report["roles"]:
            self.assertNotEqual(base.fold(role["component_id"]), role["outer"])
        self.assertEqual(report["fits"], 0)

    def test_t1_fallback_preserves_all_original_outcomes_exactly(self) -> None:
        row = native.Observation(1, 1, 1, "1", "1", (), ("alternative",) * 3)
        outer = base.fold(1)
        model = base.fit([row], {1: 1})
        old_models = [
            {
                "fold": f,
                "training_track_ids": [1] if f != outer else [],
                "model": model if f != outer else None,
            }
            for f in range(5)
        ]
        old = {**record(1, 1, [1.0] + [0.0] * 8), "fold": outer, "methods": None, "scored": False}
        actual, selections = study.predictions(
            [row], [{"track_id": 1, "component_id": 1}], [old], old_models
        )
        for k, v in old.items():
            self.assertEqual(actual[0][k], v)
        self.assertEqual(selections[outer]["reason"], "original_outer_abstention")
        # A supported original query keeps exact NB bytes under failed inner gates.
        query_outer = (outer + 1) % 5
        old2 = {
            **record(1, 1, [1.0] + [0.0] * 8),
            "fold": query_outer,
            "methods": base.predict(model, row),
        }
        actual, _ = study.predictions(
            [row], [{"track_id": 1, "component_id": 1}], [old2], old_models
        )
        self.assertEqual(
            actual[0]["methods"]["temperature_nb"], old2["methods"]["genre_instrument_nb"]
        )
        changed = copy.deepcopy(old2)
        changed["target"] = [0.0, 1.0] + [0.0] * 7
        again, _ = study.predictions(
            [row], [{"track_id": 1, "component_id": 1}], [changed], old_models
        )
        self.assertEqual(actual[0]["methods"], again[0]["methods"])

    def test_fixed_bins_include_right_edge_and_component_weights(self) -> None:
        p = [1.0] + [0.0] * 8
        rows = [native.Observation(i, i, i, str(i), "1") for i in (1, 2, 3)]
        records = [record(1, 1, p), record(2, 1, p), record(3, 3, [0.2] * 5 + [0.0] * 4)]
        result = study.diagnostics(records, rows)
        bins = result["methods"]["temperature_nb"]["bins"]
        self.assertEqual(bins[-1]["tracks"], 2)
        self.assertEqual(bins[-1]["component_mass"], 0.5)
        self.assertEqual(bins[1]["tracks"], 1)
        self.assertAlmostEqual(result["methods"]["temperature_nb"]["mean_confidence"], 0.6)
        report = study.aggregate(records)
        self.assertEqual(report["counts"]["scored_components"], 2)
        self.assertEqual(report["bootstrap"]["valid_draws"], 2000)
        self.assertEqual(len(report["bootstrap"]["comparisons"]), 6)

    def test_seal_physical_bytes_closed_inventory_and_wrong_pin(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            inputs = study.Inputs(
                root / "protocol",
                "p",
                root / "prepared",
                "i",
                root / "census",
                "c",
                root / "baseline",
                "b",
            )
            files = {"census.json": {"fits": 0}}
            output = root / "out"
            pin = base.publish(
                output, {**files, "seal.json": study.seal(inputs, files, "test")}, inputs.paths
            )
            self.assertEqual(study.load_sealed(inputs, output, pin, {"census.json"}, "test"), files)
            with self.assertRaises(ValueError):
                study.load_sealed(inputs, output, "0" * 64, {"census.json"}, "test")
            with (output / "census.json").open("ab") as stream:
                stream.write(b" ")
            with self.assertRaises(ValueError):
                study.load_sealed(inputs, output, pin, {"census.json"}, "test")
            (output / "census.json").write_bytes(base.encoded(files["census.json"]))
            (output / "extra").write_text("bad")
            with self.assertRaises(ValueError):
                study.load_sealed(inputs, output, pin, {"census.json"}, "test")
            with self.assertRaises(ValueError):
                base.publish(output, {}, inputs.paths)

    def test_empty_scored_aggregate_has_explicit_nulls(self) -> None:
        report = study.aggregate([])
        self.assertEqual(report["counts"]["scored_tracks"], 0)
        self.assertIsNone(report["scores"]["temperature_nb"]["component_equal_fractional_log_loss"])
        self.assertEqual(report["bootstrap"]["valid_draws"], 0)
