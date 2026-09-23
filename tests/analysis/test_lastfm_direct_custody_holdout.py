"""Focused behavior tests for the isolated Last.fm direct-custody holdout."""

from __future__ import annotations

import unittest

from opennoise.analysis.lastfm_direct_custody_holdout import _evaluate


class LastFmDirectCustodyHoldoutTests(unittest.TestCase):
    """Keep known train artists excluded and common targets identical by construction."""

    def test_train_relation_recovers_only_heldout_target(self) -> None:
        train: dict[str, tuple[str, ...]] = {"seed": ("known",)}
        targets: dict[str, tuple[str, ...]] = {"seed": ("target",)}
        relations: dict[str, tuple[tuple[str, int], ...]] = {
            "known": (("target", 5),),
            "target": (("known", 5),),
        }

        metric = _evaluate(targets, train, relations)

        self.assertEqual(metric.denominator, 1)
        self.assertEqual(metric.supported_target_count, 1)
        self.assertEqual(metric.recalled_at_20, 1)
        self.assertEqual(metric.recall_at_20, 1.0)

    def test_known_train_artist_cannot_be_recalled_as_a_target(self) -> None:
        train: dict[str, tuple[str, ...]] = {"seed": ("known",)}
        targets: dict[str, tuple[str, ...]] = {"seed": ("known",)}
        relations: dict[str, tuple[tuple[str, int], ...]] = {
            "known": (("other", 5),),
            "other": (("known", 5),),
        }

        metric = _evaluate(targets, train, relations)

        self.assertEqual(metric.supported_target_count, 0)
        self.assertEqual(metric.recalled_at_20, 0)


if __name__ == "__main__":
    unittest.main()
