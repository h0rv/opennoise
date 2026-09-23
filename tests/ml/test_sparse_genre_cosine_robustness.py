"""Behavioral tests for fixed-fold sparse cosine retrieval checks."""

from __future__ import annotations

import unittest

from opennoise.ml.sparse_genre_cosine_robustness import (
    _MINIMUM_TRAIN_ARTISTS,
    _seed_slices,
    _split_fold,
)
from opennoise.peers.direct_custody_membership_holdout import _split_memberships


class SparseGenreCosineRobustnessTests(unittest.TestCase):
    def test_folds_are_disjoint_and_the_first_matches_the_existing_holdout(self) -> None:
        memberships = {"genre": tuple(f"artist-{index}" for index in range(10))}

        _train, original_heldout = _split_memberships(memberships)
        folds = [_split_fold(memberships, fold_index=index) for index in range(5)]

        self.assertEqual(folds[0][1], original_heldout)
        heldout_artists = [artist for _train, heldout in folds for artist in heldout["genre"]]
        self.assertEqual(len(heldout_artists), len(set(heldout_artists)))
        self.assertEqual(set(heldout_artists), set(memberships["genre"]))
        self.assertTrue(
            all(len(train["genre"]) >= _MINIMUM_TRAIN_ARTISTS for train, _heldout in folds)
        )

    def test_seed_size_slices_are_fixed_and_disjoint(self) -> None:
        memberships = {
            f"seed-{index:03}": tuple(f"artist-{index}-{artist}" for artist in range(5 + index))
            for index in range(685)
        }

        broad, niche = _seed_slices(memberships)

        self.assertEqual(len(broad), 137)
        self.assertEqual(len(niche), 137)
        self.assertFalse(broad & niche)
        self.assertIn("seed-684", broad)
        self.assertIn("seed-000", niche)

    def test_rejects_a_fold_outside_the_fixed_range(self) -> None:
        with self.assertRaisesRegex(ValueError, "fold index"):
            _split_fold({"genre": ("a", "b", "c", "d", "e")}, fold_index=5)
