"""Independent weighted quantile, split isolation, and immutable-ranking tests."""

import json
import shutil
import tempfile
import unittest
from dataclasses import fields
from pathlib import Path
from unittest.mock import patch

import numpy as np
import zstandard
from scipy import sparse

from opennoise.ml.fma_component_balanced import Corpus
from opennoise.ml.fma_fixed_nonlinear import fit_encoder, transform
from opennoise.ml.fma_support_calibration import (
    LEVELS,
    calibration_mask,
    component_quantiles,
    descriptor_state,
)
from opennoise.ml.fma_support_experiment import ARMS, calibrate, fit, score, verify_stage


class SupportCalibrationTests(unittest.TestCase):
    def fixture(self) -> tuple[Corpus, np.ndarray]:
        rng = np.random.default_rng(21)
        x = rng.normal(size=(300, 5))
        full = np.column_stack([x, x**2])
        y = sparse.csr_matrix(rng.integers(0, 2, size=(300, 4)))
        groups = np.arange(300) // 3
        return Corpus(
            np.arange(1, 301), groups, groups % 5, x, y, (1, 2, 3, 4), groups, groups
        ), full

    def test_quantile_is_component_weighted_and_includes_ties(self) -> None:
        scores = np.r_[np.zeros(99), 10.0]
        groups = np.r_[np.zeros(99), 1]
        thresholds, weights = component_quantiles(scores, groups)
        np.testing.assert_array_equal(thresholds, [10, 10, 10])
        self.assertAlmostEqual(weights[:99].sum(), 0.5)
        self.assertAlmostEqual(weights[-1], 0.5)
        for q, t in zip(LEVELS, thresholds, strict=True):
            self.assertGreaterEqual(weights @ (scores <= t), q)
        with self.assertRaisesRegex(ValueError, "finite"):
            component_quantiles(np.array([np.inf]), np.array([1]))
        with self.assertRaisesRegex(ValueError, "Nonempty"):
            component_quantiles(np.array([]), np.array([]))

    def test_split_stable_under_order_and_whole_component(self) -> None:
        groups = np.repeat(np.arange(100), 3)
        masks = calibration_mask(groups)
        np.testing.assert_array_equal(masks[::-1], calibration_mask(groups[::-1]))
        self.assertTrue(masks.any())
        self.assertFalse(masks.all())
        self.assertFalse(set(groups[masks]) & set(groups[~masks]))

    def test_ungated_path_preserves_default_and_finite_norm_separation(self) -> None:
        data, _ = self.fixture()
        model = fit_encoder(
            data.features,
            data.targets,
            ~calibration_mask(data.groups),
            data.groups,
            nonlinear=False,
        )
        rows = np.vstack([data.features[0], model.center + 20 * model.scale, np.full(5, np.nan)])
        scores, vectors, valid = descriptor_state(model, rows)
        original, supported = transform(model, rows)
        np.testing.assert_allclose(vectors[0], original[0])
        self.assertGreater(scores[1], 12)
        self.assertTrue(valid[1])
        self.assertFalse(supported[1])
        self.assertFalse(valid[2])
        self.assertTrue(np.isinf(scores[2]))
        model.encoder = np.zeros((model.encoder.shape[0], 0))
        finite_scores, _, zero_valid = descriptor_state(model, data.features)
        self.assertTrue(np.isfinite(finite_scores).all())
        self.assertFalse(zero_valid.any())

    def test_properfit_state_ignores_calibration_features_and_labels(self) -> None:
        data, _ = self.fixture()
        mask = calibration_mask(data.groups)
        first = fit_encoder(data.features, data.targets, ~mask, data.groups, nonlinear=False)
        x, y = data.features.copy(), data.targets.toarray()
        x[mask], y[mask] = np.nan, 99
        other = fit_encoder(x, sparse.csr_matrix(y), ~mask, data.groups, nonlinear=False)
        for field in fields(first):
            np.testing.assert_array_equal(getattr(first, field.name), getattr(other, field.name))

    def test_full_lifecycle_thresholds_ignore_calibration_labels_and_rank_once(self) -> None:
        data, full = self.fixture()
        mask = calibration_mask(data.groups)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            seal = root / "seal.json"
            seal.write_text("{}")
            output = root / "run"
            with (
                patch("opennoise.ml.fma_support_experiment.load_inputs", return_value=(data, full)),
                patch("opennoise.ml.fma_support_experiment.verify_seal", return_value={}),
            ):
                for arm in ARMS:
                    fit(seal, output, arm)
                calibrate(seal, output)
                copied = root / "changed-labels"
                for arm in ARMS:
                    shutil.copytree(output / ("fit-" + arm), copied / ("fit-" + arm))
                original = data.targets
                changed = original.toarray()
                changed[mask] = 1 - changed[mask]
                data.targets = sparse.csr_matrix(changed)
                calibrate(seal, copied)
                self.assertEqual(
                    (output / "calibrate/thresholds.json").read_bytes(),
                    (copied / "calibrate/thresholds.json").read_bytes(),
                )
                data.targets = original
                score(seal, output)
                verify_stage(output, seal, "score")
                results = json.loads((output / "score/results.json").read_text())
                for arm in ARMS:
                    for point in ("original12", "q90", "q95", "q99"):
                        self.assertEqual(
                            results["arms"][arm][point]["all_calibration"]["totals"]["queries"],
                            int(mask.sum()),
                        )
                with zstandard.open(output / "score/ranks.jsonl.zst", "rt") as stream:
                    records = [json.loads(line) for line in stream]
                self.assertEqual(len(records), int(mask.sum()))
                for record in records:
                    for arm in ARMS:
                        accepted = record["arms"][arm]["accepted"]
                        self.assertLessEqual(accepted[1], accepted[2])
                        self.assertLessEqual(accepted[2], accepted[3])
                (output / "unrelated").write_text("bad")
                with self.assertRaisesRegex(ValueError, "Unexpected"):
                    verify_stage(output, seal, "score")

    def test_unlabeled_neighbors_are_not_ranking_coverage(self) -> None:
        data, full = self.fixture()
        nominated = np.flatnonzero(~calibration_mask(data.groups))[:3]
        y = data.targets.toarray()
        y[nominated] = 0
        data.targets = sparse.csr_matrix(y)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            seal = root / "seal.json"
            seal.write_text("{}")
            output = root / "run"
            with (
                patch("opennoise.ml.fma_support_experiment.load_inputs", return_value=(data, full)),
                patch("opennoise.ml.fma_support_experiment.verify_seal", return_value={}),
                patch("opennoise.ml.fma_component_embedding.nominate", return_value=nominated),
            ):
                for arm in ARMS:
                    fit(seal, output, arm)
                calibrate(seal, output)
                score(seal, output)
            result = json.loads((output / "score/results.json").read_text())
            for arm in ARMS:
                row = result["arms"][arm]["q99"]
                counts = row["availability"]["counts"]
                self.assertGreater(counts["neighbor_queries"], 0)
                self.assertEqual(counts["ranking_queries"], 0)
                self.assertEqual(row["all_calibration"]["metrics"]["query_coverage"], 0)
                self.assertEqual(
                    counts["missing_descriptors"]
                    + counts["outside_threshold"]
                    + counts["norm_failure"]
                    + counts["embedding_accepted"],
                    row["availability"]["queries"],
                )
