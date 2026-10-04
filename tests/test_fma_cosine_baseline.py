from __future__ import annotations

import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path

import numpy as np
from scipy import sparse

from opennoise.ml.fma_acoustic_baseline import fit_positive_gaussian
from opennoise.ml.fma_cosine_baseline import PositiveCosine


class PositiveCosineTests(unittest.TestCase):
    @staticmethod
    def fit(x: np.ndarray, y: np.ndarray, mask: np.ndarray) -> PositiveCosine:
        gaussian = fit_positive_gaussian(x, sparse.csr_matrix(y), mask)
        return PositiveCosine.from_gaussian({**asdict(gaussian), "labels": np.array([3, 7, 11])})

    def test_heldout_features_and_targets_cannot_change_reused_parameters(self) -> None:
        x = np.array([[float(i), float(i % 3)] for i in range(14)])
        class_boundary, training_rows = 5, 10
        y = np.array(
            [[int(i < class_boundary), int(i >= class_boundary), int(i == 1)] for i in range(14)]
        )
        mask = np.arange(14) < training_rows
        first = self.fit(x, y, mask)
        x[~mask] = 1e12
        y[~mask] = 1 - y[~mask]
        second = self.fit(x, y, mask)
        for name, value in asdict(first).items():
            np.testing.assert_array_equal(value, getattr(second, name))
        self.assertFalse(first.active_labels[2])

    @staticmethod
    def directional_model() -> PositiveCosine:
        return PositiveCosine.from_gaussian(
            {
                "center": np.zeros(2),
                "scale": np.ones(2),
                "active_columns": np.ones(2, dtype=bool),
                "quadratic": np.array([[-0.5, -0.5], [-0.25, -0.25], [-0.5, -0.5]]),
                "linear": np.array([[1.0, 0], [0.5, 0], [0, 1.0]]),
                "label_feature_support": np.array([5, 7, 4]),
                "labels": np.array([3, 7, 11]),
            }
        )

    def test_cosine_formula_ties_and_inactive_labels(self) -> None:
        model = self.directional_model()
        scores, reasons = model.score(np.array([[3.0, 4.0], [-1.0, 0]]))
        np.testing.assert_allclose(scores[:, :2], [[0.6, 0.6], [-1.0, -1.0]])
        self.assertTrue(np.isneginf(scores[:, 2]).all())
        self.assertEqual(reasons, [None, None])
        np.testing.assert_array_equal(np.argsort(-scores, kind="stable"), [[0, 1, 2], [0, 1, 2]])

    def test_missing_outside_and_directionless_queries_abstain(self) -> None:
        scores, reasons = self.directional_model().score(
            np.array([[np.nan, 1.0], [13.0, 0], [0.0, 0]])
        )
        self.assertEqual(
            reasons, ["missing_descriptors", "outside_training_support", "zero_query_norm"]
        )
        self.assertTrue(np.isneginf(scores).all())

    def test_no_supported_prototypes_abstain(self) -> None:
        arrays = asdict(self.directional_model())
        arrays["active_labels"][:] = False
        model = PositiveCosine(**arrays)
        scores, reasons = model.score(np.array([[1.0, 1.0]]))
        self.assertEqual(reasons, ["no_supported_prototypes"])
        self.assertTrue(np.isneginf(scores).all())

    def test_zero_class_mean_is_excluded(self) -> None:
        model = self.fit(np.arange(20.0).reshape(10, 2), np.ones((10, 3)), np.ones(10, dtype=bool))
        self.assertFalse(model.active_labels.any())

    def test_nonfinite_recovered_directions_fail_closed(self) -> None:
        arrays = asdict(self.directional_model())
        arrays["quadratic"] = np.full((3, 2), -1e-300)
        arrays["linear"] = np.full((3, 2), 1e300)
        with self.assertRaisesRegex(ValueError, "nonfinite recovered"):
            PositiveCosine.from_gaussian(arrays)

    def test_saved_model_roundtrip_preserves_ranks_and_reasons(self) -> None:
        model = self.directional_model()
        queries = np.array([[1.0, 2.0], [np.nan, 3], [0.0, 0]])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "model.npz"
            np.savez_compressed(path, **asdict(model))
            with np.load(path, allow_pickle=False) as loaded:
                replay = PositiveCosine(**dict(loaded))
            expected, reasons = model.score(queries)
            actual, replay_reasons = replay.score(queries)
        np.testing.assert_array_equal(actual, expected)
        self.assertEqual(reasons, replay_reasons)
