"""Synthetic weighted-moment checks; no retained corpus or model outcomes."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
from scipy import sparse

from opennoise.ml.fma_acoustic_baseline import NativeTrack, artist_group_fold
from opennoise.ml.fma_component_balanced import (
    Corpus,
    component_fold,
    equal_component_weights,
    fit_component_gaussian,
    load_corpus,
    query_stats,
    run_fold,
    training_roster,
    verify_seal,
)


class ComponentBalancedTests(unittest.TestCase):
    def test_component_mass(self) -> None:
        groups = np.array([1, 1, 1, 2, 3, 3])
        w = equal_component_weights(groups)
        for group in [1, 2, 3]:
            self.assertAlmostEqual(float(w[groups == group].sum()), 1)

    def test_weighted_moments_and_no_holdout_influence(self) -> None:
        x = np.array([[0.0], [0.0], [2.0], [2.0], [10.0], [14.0], [1000.0]])
        groups = np.array([1, 1, 1, 1, 2, 2, 3])
        targets = sparse.csr_matrix(np.array([[1], [1], [1], [1], [1], [0], [1]]))
        train = np.array([True] * 6 + [False])
        model = fit_component_gaussian(x, targets, train, groups)
        self.assertAlmostEqual(float(model.center[0]), 6.5)
        self.assertAlmostEqual(float(model.scale[0] ** 2), 32.75)
        # Positive component means are1 and10: equal mass gives5.5, not recordmean2.8.
        recovered_mean = -model.linear[0, 0] / (2 * model.quadratic[0, 0])
        self.assertAlmostEqual(float(recovered_mean * model.scale[0] + model.center[0]), 5.5)
        altered = x.copy()
        altered[-1] = -1e100
        other = fit_component_gaussian(altered, targets, train, groups)
        np.testing.assert_array_equal(model.intercept, other.intercept)
        recovered_variance = -0.5 / model.quadratic[0, 0]
        self.assertAlmostEqual(float(recovered_variance), 0.5 * (20.75 / 32.75) + 0.5)
        changed_targets = targets.copy().tolil()
        changed_targets[-1, 0] = 0
        changed_groups = groups.copy()
        changed_groups[-1] = 1
        other = fit_component_gaussian(x, changed_targets.tocsr(), train, changed_groups)
        np.testing.assert_array_equal(model.intercept, other.intercept)
        self.assertTrue(model.active_labels[0])  # Shared5row gate, only2positive components.

    def test_finite_component_normalization_and_source_prior(self) -> None:
        x = np.array([[0.0], [1.0], [2.0], [3.0], [4.0], [np.nan]])
        groups = np.array([1, 1, 1, 1, 1, 2])
        model = fit_component_gaussian(
            x, sparse.csr_matrix(np.ones((6, 1))), np.ones(6, dtype=bool), groups
        )
        self.assertEqual(model.training_rows, 5)
        self.assertAlmostEqual(float(model.center[0]), 2)
        mean = -model.linear / (2 * model.quadratic)
        variance = -0.5 / model.quadratic
        prior = np.exp(
            model.intercept + 0.5 * (mean * mean / variance + np.log(variance)).sum(axis=1)
        )
        self.assertAlmostEqual(float(prior[0]), 2.5 / 3)

    def test_deterministic_group_fold_and_invalid_identity(self) -> None:
        self.assertEqual(component_fold(7), component_fold(7))
        self.assertIn(component_fold(7), range(5))
        with self.assertRaises(ValueError):
            component_fold(True)  # noqa: FBT003 - reject bool masquerading as native ID.

    def test_full_denominator_missing_and_rr(self) -> None:
        active = np.array([True, True, False])
        missing = query_stats([0, 2], [], active)
        np.testing.assert_array_equal(missing, [1, 1, 2, 0, 0, 0, 0, 0, 1, 0, 0])
        ranked = query_stats([0, 2], [1, 0], active)
        np.testing.assert_array_equal(ranked, [1, 1, 2, 1, 0.5, 1, 1, 2, 1, 1, 1])
        empty = query_stats([], [0], active)
        np.testing.assert_array_equal(empty, [1, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0])

    def test_nonbinary_targets_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "binary"):
            fit_component_gaussian(
                np.arange(6.0)[:, None],
                sparse.csr_matrix(np.full((6, 1), 2)),
                np.ones(6, dtype=bool),
                np.arange(1, 7),
            )

    def test_changed_protocol_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "seal.json"
            path.write_text(
                json.dumps(
                    {
                        "revision": "fma-component-balanced-execution-v1",
                        "protocol": {},
                        "protocol_sha256": "wrong",
                        "code": {},
                    }
                )
            )
            with self.assertRaisesRegex(ValueError, "Protocol"):
                verify_seal(path)

    def test_tentative_unresolved_fold_replayed_but_excluded(self) -> None:
        identity = next(i for i in range(1, 100) if artist_group_fold(i) == 0)
        tracks = (
            NativeTrack(
                1, identity, artist_known=True, album_id=None, genre_ids=(1,), targets_missing=False
            ),
            NativeTrack(
                2,
                identity,
                artist_known=False,
                album_id=None,
                genre_ids=(1,),
                targets_missing=False,
            ),
        )
        ledger = [
            {
                "track_id": r.track_id,
                "artist_id": identity,
                "artist_known": r.artist_known,
                "album_id": None,
                "component_id": identity,
                "fold": 0,
            }
            for r in tracks
        ]
        self.assertEqual(training_roster(tracks, {identity: identity}, ledger), [tracks[0]])
        ledger[1]["component_id"] = identity + 1
        with self.assertRaisesRegex(ValueError, "replay"):
            training_roster(tracks, {identity: identity}, ledger)

    def test_changed_input_manifest_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "MANIFEST.json").write_text("{}")
            with self.assertRaisesRegex(ValueError, "manifest"):
                load_corpus({"source": directory})

    def test_stage_fits_only_other_folds_and_keeps_missing_queries(self) -> None:
        x = np.arange(60.0, dtype=float).reshape(30, 2)
        folds = np.repeat(np.arange(5), 6)
        x[0] = np.nan
        data = Corpus(
            np.arange(1, 31),
            np.repeat(np.arange(1, 11), 3),
            folds,
            x,
            sparse.csr_matrix(np.ones((30, 1))),
            (21,),
            np.repeat(np.arange(1, 11), 3),
            np.zeros(30),
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            seal = root / "seal.json"
            seal.write_text("{}")
            with (
                patch("opennoise.ml.fma_component_balanced.verify_seal", return_value={}),
                patch("opennoise.ml.fma_component_balanced.load_corpus", return_value=data),
            ):
                run_fold(seal, root / "out", 0)
            with np.load(root / "out/fold-0/recording.npz") as model:
                np.testing.assert_allclose(model["center"], x[folds != 0].mean(axis=0))
            with np.load(root / "out/fold-0/statistics.npz") as saved:
                stats = saved["values"]
                np.testing.assert_array_equal(stats[:, :, 0].sum(axis=0), [6, 6, 6])
                np.testing.assert_array_equal(stats[:, :, 2].sum(axis=0), [6, 6, 6])
            receipt = json.loads((root / "out/fold-0/receipt.json").read_text())
            self.assertEqual(receipt["abstentions"]["recording"]["missing_descriptors"], 1)
            self.assertEqual(receipt["training_queries"], 24)
