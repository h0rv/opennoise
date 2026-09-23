"""Focused capacity controls for the direct-custody co-listen evaluation."""

from __future__ import annotations

import unittest

from opennoise.peers.direct_custody_colisten_capacity_holdout import (
    _all_idf_peer_rows,
    _capped_relations,
)


class DirectCustodyCoListenCapacityHoldoutTests(unittest.TestCase):
    def test_full_peer_expansion_keeps_all_accepted_train_candidate_pairs(self) -> None:
        train: dict[str, tuple[str, ...]] = {
            "source": ("one", "two"),
            **{f"peer-{number:02}": ("one", "two") for number in range(11)},
            "one-shared": ("one",),
        }

        rows, pair_count = _all_idf_peer_rows(train)

        self.assertEqual(pair_count, 66)
        self.assertEqual(len(rows["source"]), 11)
        self.assertNotIn("one-shared", {row[0]: row for row in rows["source"]})

    def test_colisten_sensitivity_cap_is_deterministic_and_per_source_artist(self) -> None:
        relations: dict[str, tuple[tuple[str, int], ...]] = {
            "artist": tuple((f"neighbor-{number:02}", number) for number in range(12))
        }

        capped = _capped_relations(relations)

        self.assertEqual(len(capped["artist"]), 10)
        self.assertEqual(capped["artist"][0], ("neighbor-11", 11))
        self.assertNotIn(("neighbor-00", 0), capped["artist"])
