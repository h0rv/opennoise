"""Behavioral checks for direct-custody co-listen retrieval direction and exclusions."""

from __future__ import annotations

import unittest

from opennoise.peers.direct_custody_colisten_holdout import (
    _endpoint_targets,
    _outcome,
    _scores_from_colisten,
)


class DirectCustodyCoListenHoldoutTests(unittest.TestCase):
    def test_endpoint_cohort_filters_before_all_ranking_arms_share_the_denominator(self) -> None:
        targets = _endpoint_targets(
            {"seed-a": ("endpoint", "unmatched"), "seed-b": ("unmatched",)},
            {"endpoint": (("neighbor", 5),)},
        )
        self.assertEqual(targets, {"seed-a": ("endpoint",)})

    def test_seed_train_artists_do_not_consume_colisten_candidate_ranks(self) -> None:
        train: dict[str, tuple[str, ...]] = {"genre": ("known",), "other": ()}
        relations: dict[str, tuple[tuple[str, int], ...]] = {"known": (("known", 100), ("held", 5))}
        scores = _scores_from_colisten("genre", train, relations)
        self.assertNotIn("known", scores)
        self.assertAlmostEqual(scores["held"], 1.791759469228055)

    def test_seed_to_artist_ranking_reports_missing_colisten_target_as_unsupported(self) -> None:
        outcome = _outcome(
            targets={"genre": ("held", "absent")},
            score_for_seed=lambda _seed: {"held": 1.0},
        )
        self.assertEqual(outcome.recalled10, 1)
        self.assertEqual(outcome.recalled20, 1)
        self.assertEqual(outcome.supported, frozenset({("genre", "held")}))
