"""Fixed rank evidence keeps abstentions and calibrated memberships separate."""

import unittest

from opennoise.ml.fma_artist_ranking import rank_artist_genres


class ArtistRankingTests(unittest.TestCase):
    def test_ties_and_abstention_denominator_use_only_saved_ranks(self) -> None:
        rows = {
            10: {"reason": None, "ranked_genre_ids": [2, 3], "genre_ids": [999]},
            11: {"reason": None, "ranked_genre_ids": [3, 2], "genre_ids": [998]},
            12: {"reason": "missing_descriptors", "ranked_genre_ids": []},
        }
        result = rank_artist_genres([12, 11, 10], rows)
        self.assertEqual(result["ranking_supported_track_count"], 2)
        self.assertEqual(
            result["ranked_source_annotation_candidates"],
            [
                {
                    "genre_id": genre,
                    "mean_reciprocal_track_rank": 0.5,
                    "contributing_track_count": 2,
                }
                for genre in (2, 3)
            ],
        )
        self.assertEqual(result, rank_artist_genres([10, 11, 12], rows))
        self.assertEqual(rank_artist_genres([12], rows)["ranked_source_annotation_candidates"], [])

    def test_missing_duplicates_and_nonempty_abstentions_fail(self) -> None:
        for tracks, rows in (
            ([], {}),
            ([1, 1], {1: {"reason": None, "ranked_genre_ids": [2]}}),
            ([1], {}),
            ([1], {1: {"reason": None, "ranked_genre_ids": [2, 2]}}),
            ([1], {1: {"reason": "missing_feature_row", "ranked_genre_ids": [2]}}),
        ):
            with self.assertRaises(ValueError):
                rank_artist_genres(tracks, rows)
