"""Historical counts preserve zero, reject missingness and never project private fields."""

from __future__ import annotations

import unittest

from opennoise.ml.fma_waveform_popularity import select_counts


class PopularityProjectionTests(unittest.TestCase):
    def test_projects_only_identity_and_count_consuming_whole_stream(self) -> None:
        rows = [
            {"track_id": "1", "artist_id": "2", "track_genres": "[]", "track_listens": "0"},
            {"track_id": "99", "private_contact": "never project this"},
        ]
        iterator = iter(rows)
        self.assertEqual(
            select_counts(iterator, [{"track_id": 1, "artist_id": 2, "genre_ids": []}]),
            [{"track_id": 1, "historical_track_listens": 0}],
        )
        self.assertEqual(list(iterator), [])

    def test_missing_invalid_duplicate_or_misassociated_counts_fail(self) -> None:
        target = [{"track_id": 1, "artist_id": 2, "genre_ids": []}]
        row = {"track_id": "1", "artist_id": "2", "track_genres": "[]", "track_listens": "0"}
        for rows in (
            [],
            [row, row],
            [{**row, "artist_id": "3"}],
            *[[{**row, "track_listens": count}] for count in ("", "-1", "1.5", "NaN", "\u0661")],
        ):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                select_counts(rows, target)
