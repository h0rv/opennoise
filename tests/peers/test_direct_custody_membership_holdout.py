"""Focused behavior tests for direct custody membership holdout mechanics."""

from __future__ import annotations

import unittest

from opennoise.peers.direct_custody_membership_holdout import (
    _build_peer_rows,
    _held_out_artists,
    _ranked_target_metrics,
    _split_memberships,
)


class DirectCustodyMembershipHoldoutTests(unittest.TestCase):
    def test_hash_split_is_stable_and_retains_four_train_artists(self) -> None:
        artists = tuple(f"artist-{number}" for number in range(5))
        first = _held_out_artists("seed-a", artists)
        second = _held_out_artists("seed-a", artists)
        self.assertEqual(first, second)
        self.assertEqual(len(first), 1)
        self.assertEqual(len(set(artists) - set(first)), 4)

    def test_small_seeds_are_retained_in_train_but_not_scored(self) -> None:
        memberships: dict[str, tuple[str, ...]] = {
            "small": ("a", "b", "c", "d"),
            "large": tuple("abcdef"),
        }
        train, held_out = _split_memberships(memberships)
        self.assertEqual(train["small"], memberships["small"])
        self.assertNotIn("small", held_out)
        self.assertEqual(len(train["large"]), 5)
        self.assertEqual(len(held_out["large"]), 1)

    def test_peer_ranker_reports_unsupported_positives_separately_from_recovery(self) -> None:
        outcome = _ranked_target_metrics(
            held_out={"source": ("target", "unsupported")},
            train={"source": (), "peer": ("target",)},
            peer_rows={"source": (("peer", 2, 0.5),)},
            score_index=2,
        )
        self.assertEqual(outcome.totals.recalled, 1)
        self.assertEqual(outcome.totals.supported, 1)
        self.assertEqual(outcome.totals.reciprocal_rank_sum, 1.0)
        self.assertEqual(outcome.macro_recall, 0.5)
        self.assertEqual(outcome.supported_targets, frozenset({("source", "target")}))

    def test_train_peer_graph_excludes_withheld_membership_and_changes_signal_ranking(self) -> None:
        train: dict[str, tuple[str, ...]] = {
            # ``held-artist`` is deliberately absent from source's train row.
            "source": ("rare-1", "rare-2", "hub-1", "hub-2", "hub-3"),
            "rare-peer": ("rare-1", "rare-2", "held-artist", "rare-only"),
            "hub-peer": ("hub-1", "hub-2", "hub-3", "hub-only"),
            **{
                f"hub-{number}": ("hub-1", "hub-2", "hub-3", f"hub-only-{number}")
                for number in range(4, 12)
            },
        }
        idf_rows, count_rows, _candidate_count = _build_peer_rows(train)
        idf_source = idf_rows["source"]
        count_source = count_rows["source"]
        rare_idf = next(row for row in idf_source if row[0] == "rare-peer")
        rare_count = next(row for row in count_source if row[0] == "rare-peer")
        self.assertEqual(rare_idf[1], 2)
        self.assertEqual(rare_count[1], 2)
        self.assertEqual(idf_source[0][0], "rare-peer")
        self.assertNotEqual(count_source[0][0], "rare-peer")


if __name__ == "__main__":
    unittest.main()
