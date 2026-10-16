"""Independent finite enumeration and synthetic ranking tests; no actual new scores."""

from __future__ import annotations

# ruff: noqa: PLR2004 -- explicit small synthetic cohort cardinalities.
import itertools
import json
import math
import tempfile
import unittest
from collections import defaultdict
from fractions import Fraction
from pathlib import Path
from unittest.mock import patch

import numpy as np

from opennoise.common import canonical_json
from opennoise.ml import fma_waveform_evaluation as evaluation


def enumerate_masks(
    groups: list[list[set[int]]], tags: set[int], k: int
) -> dict[tuple[int, ...], Fraction]:
    """Brute-force the component subsets and within-component track tuples."""
    effective = min(k, len(groups))
    probabilities: dict[tuple[int, ...], Fraction] = defaultdict(Fraction)
    for subset in itertools.combinations(range(len(groups)), effective):
        for choices in itertools.product(*(groups[i] for i in subset)):
            recovered = tuple(sorted(set().union(*choices) & tags))
            probabilities[recovered] += Fraction(
                1, math.comb(len(groups), effective) * math.prod(len(groups[i]) for i in subset)
            )
    return dict(probabilities)


class EvaluationTests(unittest.TestCase):
    def test_exact_null_matches_exhaustive_tracks_with_unequal_components(self) -> None:
        groups = [[{1}, {2}], [{1, 2}], [{3}, set(), {1}], [{2, 3}]]
        for k in (1, 3):
            result = evaluation.conditional_null(groups, {1, 2, 3, 9}, {1, 2}, k)
            actual = {
                tuple(row["tags"]): Fraction(row["numerator"], row["denominator"])
                for row in result["recovered_masks"]
            }
            self.assertEqual(actual, enumerate_masks(groups, {1, 2, 3, 9}, k))
            self.assertEqual(result["recall_all"]["ceiling"], max(len(mask) for mask in actual) / 4)
            self.assertEqual(
                result["recall_known"]["ceiling"],
                max(len(set(mask) & {1, 2}) for mask in actual) / 2,
            )

    def test_null_empty_unknown_and_fewer_than_k_keep_denominators(self) -> None:
        empty = evaluation.conditional_null([], {9}, set(), 3)
        self.assertEqual(empty["hit"]["probability"], 0)
        self.assertEqual(empty["recall_all"]["expectation"], 0)
        self.assertIsNone(empty["recall_known"]["expectation"])
        small = evaluation.conditional_null([[{1}]], {1}, {1}, 3)
        self.assertEqual(small["effective_k"], 1)
        self.assertEqual(small["hit"]["probability"], 1)
        with self.assertRaises(ValueError):
            evaluation.conditional_null([[{1}]], set(range(17)), {1}, 1)

    def test_poisson_binomial_matches_independent_bernoulli_enumeration(self) -> None:
        values = [Fraction(0), Fraction(1, 3), Fraction(2, 3), Fraction(1)]
        expected: dict[int, Fraction] = defaultdict(Fraction)
        for outcomes in itertools.product((0, 1), repeat=len(values)):
            weight = Fraction(1)
            for outcome, chance in zip(outcomes, values, strict=True):
                weight *= chance if outcome else 1 - chance
            expected[sum(outcomes)] += weight
        result = evaluation.poisson_binomial(values)
        actual = {
            row["hits"]: Fraction(row["numerator"], row["denominator"])
            for row in result["distribution"]
        }
        self.assertEqual(actual, dict(expected))
        self.assertEqual(result["expected_hits"], 2)
        self.assertEqual(result["conditional_central_95_hit_count_band"], [1, 3])

    def test_comparators_keep_pool_ties_components_and_unsupported_queries(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            tracks = [
                {"track_id": i, "genre_ids": [1] if i < 4 else [2] if i == 4 else [9]}
                for i in range(1, 7)
            ]
            roster = [
                {
                    "track_id": i,
                    "component_id": 1 if i < 3 else i,
                    "fold": 0 if i <= 4 else 1 if i == 5 else 2,
                }
                for i in range(1, 7)
            ]
            original = {
                "training_ids": [1, 2, 3, 4],
                "eligible_training_ids": [1, 2, 3, 4],
                "queries": [
                    {
                        "track_id": i,
                        "fold": 1 if i == 5 else 2,
                        "reason": None if i == 5 else "out_of_support",
                        "rankings": {
                            arm: [1, 3, 4] if i == 5 else [] for arm in ("raw", "pca", "id")
                        },
                        "metrics": dict.fromkeys(("raw", "pca", "id")),
                    }
                    for i in (5, 6)
                ],
            }
            (root / "evaluation.json").write_bytes(canonical_json(original))
            (root / "declaration.json").write_bytes(canonical_json({"roster": roster}))
            values = np.zeros((6, 52))
            values[0, 48] = 4
            values[1, 48] = 2
            values[2, 48] = 2
            values[3, 48] = 1
            np.savez(root / "features.npz", values=values, track_ids=np.arange(1, 7))
            np.savez(
                root / "model.npz",
                center=np.zeros(52),
                scale=np.ones(52),
                active=np.ones(52, dtype=bool),
            )
            result = evaluation.calculate(
                root, {"tracks": tracks}, {1: 7, 2: 7, 3: 100, 4: 0, 5: 10000, 6: 0}
            )
            query, unsupported = result["queries"]
            self.assertEqual(query["arms"]["simple4"]["ranking"], [4, 2, 3])
            self.assertEqual(query["arms"]["annotation_prevalence"]["ranking"], [1, 3, 4])
            self.assertEqual(query["arms"]["historical_popularity"]["ranking"], [3, 1, 4])
            for arm in unsupported["arms"].values():
                self.assertEqual(arm["ranking"], [])
                self.assertFalse(arm["metrics"]["3"]["hit"])
                self.assertIsNone(arm["metrics"]["3"]["recall_known"])
            self.assertEqual(result["aggregates"]["test"]["total_queries"], 1)

    def test_listens_projection_rejects_missing_boolean_negative_and_unknown_fields(self) -> None:
        for change in ("valid", "missing", "boolean", "negative", "extra"):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as name:
                row = {"track_id": 1, "historical_track_listens": 0}
                if change == "boolean":
                    row["historical_track_listens"] = True
                elif change == "negative":
                    row["historical_track_listens"] = -1
                elif change == "extra":
                    row["private"] = 99
                value = {
                    "revision": "fma-permitted55-historical-listens-v1",
                    "candidate_manifest_sha256": evaluation.waveform.MANIFEST_SHA,
                    "tracks": [] if change == "missing" else [row],
                }
                path = Path(name) / "listens.json"
                path.write_text(json.dumps(value))
                with patch.object(
                    evaluation, "LISTENS_SHA", evaluation.waveform.digest(path.read_bytes())
                ):
                    if change == "valid":
                        self.assertEqual(evaluation.load_listens(path, {1}), {1: 0})
                    else:
                        with self.assertRaises(ValueError):
                            evaluation.load_listens(path, {1})
