"""Synthetic denominator and paired-resampling contracts, without native outcomes."""

from __future__ import annotations

import unittest

import numpy as np

from opennoise.ml.fma_component_balanced_metrics import ARMS, DRAWS, summarize


class ComponentMetricsTests(unittest.TestCase):
    def test_pooled_ratio_is_not_component_mean(self) -> None:
        rows = np.array(
            [
                [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
                [9, 9, 9, 0, 0, 0, 9, 9, 9, 9, 9],
            ],
            dtype=float,
        )
        stats = np.repeat(rows[:, None, :], 3, axis=1)
        result = summarize(stats, bootstrap=False)
        metric = result["arms"][ARMS[0]]["metrics"]
        self.assertEqual(metric["positive_recall10"], 0.1)
        self.assertEqual(metric["component_mean_recall10"], 0.5)
        self.assertEqual(result["largest_query_component"]["component_index"], 1)
        self.assertIsNone(result["paired_bootstrap"])

    def test_identical_arms_have_exact_zero_paired_differences(self) -> None:
        stats = np.ones((2, 3, 11))
        result = summarize(stats)["paired_bootstrap"]
        for comparison in result["comparisons"].values():
            for metric in comparison.values():
                self.assertEqual(metric["difference"], 0)
                self.assertEqual(metric["interval"], [0, 0])
                self.assertEqual(metric["valid_draws"], DRAWS)

    def test_undefined_draws_are_omitted_per_metric_without_reroll(self) -> None:
        stats = np.ones((2, 3, 11))
        stats[0] = 0
        stats[0, :, 0] = 1
        result = summarize(stats)["paired_bootstrap"]["comparisons"]
        comparison = next(iter(result.values()))
        rng = np.random.Generator(np.random.PCG64(20261016))
        undefined = sum(np.all(rng.integers(0, 2, size=2) == 0) for _ in range(DRAWS))
        self.assertEqual(comparison["positive_recall10"]["undefined_draws"], undefined)
        self.assertEqual(comparison["positive_recall10"]["valid_draws"], DRAWS - undefined)
        self.assertEqual(comparison["query_coverage"]["undefined_draws"], 0)

    def test_empty_and_unlabeled_cohorts_preserve_nulls(self) -> None:
        for stats in (np.zeros((0, 3, 11)), np.zeros((2, 3, 11))):
            result = summarize(stats)
            for arm in result["arms"].values():
                self.assertTrue(all(value is None for value in arm["metrics"].values()))
            for comparison in result["paired_bootstrap"]["comparisons"].values():
                for metric in comparison.values():
                    self.assertIsNone(metric["interval"])
                    self.assertEqual(metric["undefined_draws"], DRAWS)

    def test_invalid_pairing_and_numerators_rejected(self) -> None:
        stats = np.ones((2, 3, 11))
        stats[0, 0, 0] = 2
        with self.assertRaisesRegex(ValueError, "paired"):
            summarize(stats)
        stats[:] = 1
        stats[0, 0, 3] = 2
        with self.assertRaisesRegex(ValueError, "numerator"):
            summarize(stats)
