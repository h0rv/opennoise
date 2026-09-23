"""Focused behavior tests for the isolated Last.fm direct-custody holdout."""

from __future__ import annotations

import unittest

from opennoise.analysis.lastfm_direct_custody_holdout import (
    _control_cohort,
    _evaluate,
    _top_twenty_overlap,
    _weighted_degree,
)
from opennoise.peers.direct_custody_membership_holdout import _build_peer_rows


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

    def test_controls_share_the_lastfm_endpoint_targets_and_use_train_only_votes(self) -> None:
        train: dict[str, tuple[str, ...]] = {
            "seed": ("known-a", "known-b"),
            "peer": ("known-a", "known-b"),
        }
        targets: dict[str, tuple[str, ...]] = {"seed": ("held",)}
        relations: dict[str, tuple[tuple[str, int], ...]] = {
            "known-a": (("held", 5),),
            "held": (("known-a", 5),),
        }
        idf_rows, _ignored_counts, _ignored_candidate_count = _build_peer_rows(train)

        cohort = _control_cohort(targets, train, relations, idf_rows, _weighted_degree(relations))

        self.assertEqual(cohort.target_count, 1)
        self.assertEqual(cohort.lastfm_pair_transfer.denominator, 1)
        self.assertEqual(cohort.direct_train_artist_popularity.denominator, 1)
        self.assertEqual(cohort.direct_idf_peer.denominator, 1)
        self.assertEqual(cohort.lastfm_graph_weighted_degree.denominator, 1)
        self.assertEqual(cohort.lastfm_pair_transfer.recalled_at_20, 1)
        self.assertEqual(cohort.direct_train_artist_popularity.supported_target_count, 0)
        self.assertEqual(cohort.direct_idf_peer.supported_target_count, 0)

    def test_direct_idf_peer_rows_have_the_fixed_ten_peer_cap(self) -> None:
        train: dict[str, tuple[str, ...]] = {"seed": ("shared-a", "shared-b")}
        train.update({f"peer-{index:02d}": ("shared-a", "shared-b") for index in range(11)})

        idf_rows, _ignored_counts, _ignored_candidate_count = _build_peer_rows(train)

        self.assertEqual(len(idf_rows["seed"]), 10)

    def test_separate_signal_overlap_partitions_the_common_target_cohort(self) -> None:
        overlap = _top_twenty_overlap(
            target_count=4,
            lastfm_hits=frozenset({("seed", "both"), ("seed", "lastfm")}),
            listenbrainz_hits=frozenset({("seed", "both"), ("seed", "listenbrainz")}),
        )

        self.assertEqual(overlap.both, 1)
        self.assertEqual(overlap.lastfm_only, 1)
        self.assertEqual(overlap.listenbrainz_only, 1)
        self.assertEqual(overlap.neither, 1)


if __name__ == "__main__":
    unittest.main()
