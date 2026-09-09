"""Adversarial ranking boundaries for the aggregate-only offline experiment."""

from __future__ import annotations

import unittest

from musix.ingest.listenbrainz_offline_experiment import (
    _is_musicbrainz_artist_id,
    _metrics_from_rankings,
    _pair_window_support,
    _ranked_candidates,
)


class ListenBrainzOfflineExperimentAdversarialTests(unittest.TestCase):
    def test_only_canonical_musicbrainz_uuid_endpoints_are_accepted(self) -> None:
        self.assertTrue(
            _is_musicbrainz_artist_id("musicbrainz:artist:00000000-0000-4000-8000-000000000001")
        )
        self.assertFalse(_is_musicbrainz_artist_id("musicbrainz:artist:not-a-uuid"))
        self.assertFalse(
            _is_musicbrainz_artist_id("musicbrainz:artist:00000000-0000-4000-8000-00000000000A")
        )

    def test_pair_support_counts_distinct_windows_not_duplicate_rows(self) -> None:
        pair = (
            "musicbrainz:artist:00000000-0000-4000-8000-000000000001",
            "musicbrainz:artist:00000000-0000-4000-8000-000000000002",
        )

        support = _pair_window_support((frozenset({pair}), frozenset({pair})))

        self.assertEqual(support, {pair: 2})

    def test_ranking_excludes_self_and_previously_seen_train_neighbor(self) -> None:
        query = "musicbrainz:artist:00000000-0000-0000-0000-000000000001"
        seen = "musicbrainz:artist:00000000-0000-0000-0000-000000000002"
        novel = "musicbrainz:artist:00000000-0000-0000-0000-000000000003"

        references = {query: frozenset({novel})}
        rankings = _ranked_candidates(
            references,
            {(query, seen)},
            lambda _query: {query: 100.0, seen: 99.0, novel: 1.0},
        )
        metrics = _metrics_from_rankings(
            "train_degree_popularity",
            rankings,
            references,
        )

        self.assertEqual(metrics.hit_query_count_at_10, 1)
        self.assertEqual(metrics.recall_at_10, 1.0)

    def test_equal_scores_use_stable_artist_id_tie_break(self) -> None:
        query = "musicbrainz:artist:00000000-0000-0000-0000-000000000100"
        reference = "musicbrainz:artist:00000000-0000-0000-0000-000000000000"
        later_ties = {
            f"musicbrainz:artist:00000000-0000-0000-0000-000000000{value:03d}": 1.0
            for value in range(1, 11)
        }
        scores = {**later_ties, reference: 1.0}

        references = {query: frozenset({reference})}
        rankings = _ranked_candidates(
            references,
            set(),
            lambda _query: scores,
        )
        metrics = _metrics_from_rankings(
            "train_degree_popularity",
            rankings,
            references,
        )

        self.assertEqual(metrics.hit_query_count_at_10, 1)
        self.assertEqual(metrics.recall_at_10, 1.0)


if __name__ == "__main__":
    unittest.main()
