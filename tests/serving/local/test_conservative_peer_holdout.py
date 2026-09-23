"""Behavior checks for leakage-free conservative peer geometry diagnostics."""

from __future__ import annotations

import unittest

from opennoise.serving.local.conservative_peer_holdout import (
    Point,
    adjacency,
    evaluate_holdout,
    project_unplaced,
    singleton_degree_bounded_edges,
)


class ConservativePeerHoldoutTests(unittest.TestCase):
    def test_holdout_excludes_the_target_coordinate_from_its_prediction(self) -> None:
        anchors = {"a": Point(0.0, 0.0), "b": Point(2.0, 0.0), "c": Point(100.0, 100.0)}
        result = evaluate_holdout(anchors=anchors, peer_adjacency=adjacency((("a", "b"),)))
        self.assertEqual(result.evaluable_target_count, 2)
        self.assertEqual(result.mean_peer_error, 2.0)
        self.assertEqual(result.median_peer_error, 2.0)

    def test_projection_abstains_without_a_placed_direct_peer(self) -> None:
        result = project_unplaced(
            unplaced_ids=("u-with-anchor", "u-isolated"),
            anchors={"a": Point(2.0, 4.0)},
            peer_adjacency=adjacency((("u-with-anchor", "a"), ("u-isolated", "other"))),
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].seed_id, "u-with-anchor")
        self.assertEqual(result[0].point, Point(2.0, 4.0))

    def test_singleton_degree_rule_filters_hubs_before_pair_enumeration(self) -> None:
        edges = singleton_degree_bounded_edges(
            (
                ("artist-a", "one"),
                ("artist-a", "two"),
                ("artist-b", "one"),
                ("artist-b", "two"),
                ("hub", "one"),
                ("hub", "three"),
                ("hub", "four"),
                ("low", "five"),
                ("low", "six"),
                ("hub-two", "five"),
                ("hub-two", "six"),
                ("hub-two", "seven"),
            ),
            maximum_artist_seed_degree=2,
        )
        self.assertEqual(edges, ())
