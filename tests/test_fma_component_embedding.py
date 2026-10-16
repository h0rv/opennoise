"""Synthetic fixed-embedding contracts; no retained corpus fits or outcomes."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
from scipy import sparse

from opennoise.ml import fma_component_balanced as balanced
from opennoise.ml.fma_component_embedding import (
    ARMS,
    STATS,
    compressed_encoder,
    fit_embedding,
    nominate,
    representations,
    run_fold,
    summarize_run,
    summarize_statistics,
    transfer,
    verify_seal,
)


class EmbeddingTests(unittest.TestCase):
    def fixture(self) -> tuple[np.ndarray, sparse.csr_matrix, np.ndarray, np.ndarray]:
        rng = np.random.default_rng(123)
        x = rng.normal(size=(30, 4))
        y = sparse.csr_matrix(np.column_stack([np.arange(30) % 3 == 0, np.arange(30) % 5 == 0]))
        fit = np.arange(30) >= 6  # noqa: PLR2004 - six synthetic heldout rows.
        groups = np.repeat(np.arange(1, 11), 3)
        return x, y, fit, groups

    def test_ridge_normal_equations_and_heldout_isolation(self) -> None:
        x, y, fit, groups = self.fixture()
        model = fit_embedding(x, y, fit, groups)
        weights = balanced.equal_component_weights(groups[fit])
        weights /= weights.sum()
        z = (x[fit][:, model.active_columns] - model.center[model.active_columns]) / model.scale[
            model.active_columns
        ]
        centered = y[fit][:, model.active_labels].toarray() - model.target_mean
        gradient = (
            z.T @ (weights[:, None] * (z @ model.coefficients - centered)) + model.coefficients
        )
        np.testing.assert_allclose(gradient, 0, atol=1e-14)
        changed_x = x.copy()
        changed_x[~fit] = 100000
        changed_y = y.toarray()
        changed_y[~fit] = ~changed_y[~fit]
        changed_groups = groups.copy()
        changed_groups[~fit] = 999
        other = fit_embedding(changed_x, sparse.csr_matrix(changed_y), fit, changed_groups)
        for field in ("center", "scale", "target_mean", "coefficients", "encoder"):
            np.testing.assert_array_equal(getattr(model, field), getattr(other, field))

    def test_sign_zero_rank_and_ambiguous_boundary(self) -> None:
        matrix = np.diag(np.arange(12.0, 0.0, -1))
        encoder, singular = compressed_encoder(matrix)
        self.assertEqual(encoder.shape, (12, 8))
        np.testing.assert_array_equal(singular, np.arange(12.0, 0.0, -1))
        self.assertTrue(all(encoder[np.argmax(abs(encoder[:, i])), i] > 0 for i in range(8)))
        with self.assertRaisesRegex(ValueError, "ambiguous_rank8_boundary"):
            compressed_encoder(np.eye(9))
        empty, _ = compressed_encoder(np.zeros((4, 2)))
        self.assertEqual(empty.shape, (4, 0))

    def test_feature_only_application_and_explicit_support(self) -> None:
        x, y, fit, groups = self.fixture()
        model = fit_embedding(x, y, fit, groups)
        rows = np.vstack(
            [x[0], np.full(4, np.nan), model.center, model.center + 10000 * model.scale]
        )
        _, _, descriptor, raw_ok, embedding_ok = representations(model, rows)
        np.testing.assert_array_equal(descriptor, [True, False, True, False])
        np.testing.assert_array_equal(raw_ok, [True, False, False, False])
        self.assertFalse(embedding_ok[1])
        self.assertFalse(embedding_ok[2])

    def test_candidate_nomination_ignores_labels_and_excludes_holdout(self) -> None:
        x, y, fit, groups = self.fixture()
        data = balanced.Corpus(
            np.arange(1, 31), groups, np.repeat(np.arange(5), 6), x, y, (1, 2), groups, groups
        )
        selected = nominate(data, fit)
        self.assertTrue(fit[selected].all())
        self.assertEqual(len(selected), len(set(groups[fit])))
        data.targets = sparse.csr_matrix(np.ones((30, 2)))
        np.testing.assert_array_equal(selected, nominate(data, fit))
        self.assertEqual(len(set(groups[selected])), len(selected))

    def test_unlabeled_neighbors_and_below_encoder_support_votes(self) -> None:
        y = sparse.csr_matrix(np.array([[0, 0, 0], [0, 0, 1], [1, 0, 1], [1, 0, 0]]))
        self.assertEqual(transfer([0], y), [])
        self.assertEqual(transfer([1], y), [2])
        self.assertEqual(transfer([2, 3], y), [0, 2])
        self.assertEqual(transfer([1, 3], y), [0, 2])

    def test_staged_full_denominators_and_unlabeled_queries(self) -> None:
        x, y, _fit, groups = self.fixture()
        x[0] = np.nan
        data = balanced.Corpus(
            np.arange(1, 31), groups, np.repeat(np.arange(5), 6), x, y, (1, 2), groups, groups
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            seal = root / "seal.json"
            seal.write_text("{}")
            with (
                patch("opennoise.ml.fma_component_embedding.verify_seal", return_value={}),
                patch("opennoise.ml.fma_component_balanced.load_corpus", return_value=data),
            ):
                run_fold(seal, root / "run", 0)
            with np.load(root / "run/fold-0/statistics.npz") as saved:
                stats = saved["values"]
                self.assertEqual(stats.shape, (2, len(ARMS), len(STATS)))
                np.testing.assert_array_equal(stats[:, :, 0].sum(axis=0), np.full(5, 6))
                np.testing.assert_array_equal(stats[:, :, 1].sum(axis=0), np.full(5, 3))
                np.testing.assert_array_equal(stats[:, :, 2].sum(axis=0), np.full(5, 4))
            receipt = json.loads((root / "run/fold-0/receipt.json").read_text())
            self.assertEqual(receipt["abstentions"]["raw44_neighbors"]["missing_descriptors"], 1)

    def test_paired_zero_differences_and_undefined_bootstrap(self) -> None:
        stats = np.zeros((2, 5, len(STATS)))
        stats[:, :, 0] = 1
        report = summarize_statistics(stats)
        result = report["paired_bootstrap"]["comparisons"]["ridge8_neighbors_minus_raw44_neighbors"]
        self.assertIsNone(result["component_mean_recall10"]["interval"])
        self.assertEqual(result["component_mean_recall10"]["undefined_draws"], 2000)
        self.assertEqual(result["query_coverage"]["interval"], [0, 0])
        stats[0, 1, 0] = 2
        with self.assertRaisesRegex(ValueError, "denominators"):
            summarize_statistics(stats)

    def test_bad_seal_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory) / "seal.json"
            p.write_text(json.dumps({"revision": "wrong"}))
            with self.assertRaisesRegex(ValueError, "seal"):
                verify_seal(p)

    def test_unlabeled_neighbor_list_is_not_genre_ranking_coverage(self) -> None:
        x, y, fit, groups = self.fixture()
        data = balanced.Corpus(
            np.arange(1, 31), groups, np.repeat(np.arange(5), 6), x, y, (1, 2), groups, groups
        )
        # Synthetic nominated representatives with no supplied tags; other fit rows train encoder.
        selected = []
        for group in np.unique(groups[fit]):
            indices = np.flatnonzero(
                fit & (groups == group) & (np.asarray(y.sum(axis=1)).ravel() == 0)
            )
            if len(indices):
                selected.append(indices[0])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            seal = root / "seal.json"
            seal.write_text("{}")
            with (
                patch("opennoise.ml.fma_component_embedding.verify_seal", return_value={}),
                patch("opennoise.ml.fma_component_balanced.load_corpus", return_value=data),
                patch(
                    "opennoise.ml.fma_component_embedding.nominate", return_value=np.array(selected)
                ),
            ):
                run_fold(seal, root / "run", 0)
            with np.load(root / "run/fold-0/statistics.npz") as saved:
                stats = saved["values"]
                self.assertGreater(stats[:, 0, 12].sum(), 0)
                self.assertEqual(stats[:, 0, 6].sum(), 0)
                self.assertEqual(stats[:, 0, 2].sum(), 4)

    def test_summary_giant_component_separate_and_tamper_rejected(self) -> None:
        x, y, _, groups = self.fixture()
        data = balanced.Corpus(
            np.arange(1, 31), groups, np.repeat(np.arange(5), 6), x, y, (1, 2), groups, groups
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            seal = root / "seal.json"
            seal.write_text("{}")
            with (
                patch(
                    "opennoise.ml.fma_component_embedding.verify_seal",
                    return_value={"protocol": {"interpretation": ["synthetic"]}},
                ),
                patch("opennoise.ml.fma_component_balanced.load_corpus", return_value=data),
            ):
                for fold in range(5):
                    run_fold(seal, root / "run", fold)
                ranks = root / "run/fold-0/ranks.jsonl.zst"
                original = ranks.read_bytes()
                ranks.write_bytes(original + b"changed")
                with self.assertRaisesRegex(ValueError, "changed"):
                    summarize_run(seal, root / "run")
                ranks.write_bytes(original)
                report = summarize_run(seal, root / "run")
                self.assertEqual(
                    report["giant_component"]["arms"]["raw44_neighbors"]["totals"]["queries"], 3
                )
                self.assertEqual(
                    report["other_components"]["arms"]["raw44_neighbors"]["totals"]["queries"], 27
                )

    def test_impossible_availability_rejected(self) -> None:
        stats = np.zeros((1, 5, len(STATS)))
        stats[:, :, 0] = 1
        stats[0, 0, 12] = 1
        with self.assertRaisesRegex(ValueError, "Numerator"):
            summarize_statistics(stats, bootstrap=False)
