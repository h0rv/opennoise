"""Verify independent auditor handling of unresolved graph bridges and cold positives."""

import unittest
from collections import Counter

from scripts.audit_fma_acoustic_model import independent_components, replay_metrics


class FMAAcousticModelAuditTests(unittest.TestCase):
    def test_unresolved_artist_bridges_albums_and_duplicates_without_becoming_fact(self) -> None:
        rows: dict[int, dict[str, object]] = {
            1: {"artist_id": 10, "album_id": 1},
            2: {"artist_id": 999, "album_id": 1},
            3: {"artist_id": 999, "album_id": 2},
            4: {"artist_id": 20, "album_id": 2},
            5: {"artist_id": 30, "album_id": None},
            6: {"artist_id": None, "album_id": 2},
        }
        self.assertEqual(independent_components(rows, [[4, 5]]), {10: 10, 999: 10, 20: 10, 30: 10})

    def test_missing_queries_and_unseen_labels_stay_positive_denominators(self) -> None:
        rows: list[dict[str, object]] = [
            {"genre_ids": [1]},
            {"genre_ids": [2]},
            {"genre_ids": [3]},
            {"genre_ids": None},
        ]
        result = replay_metrics(
            rows,
            [[1], [], [], []],
            [None, "missing_feature_row", None, None],
            [1, 2, 3],
            Counter({1: 200, 2: 2}),
        )
        self.assertEqual(result["queries"], 4)
        self.assertEqual(result["labeled_queries"], 3)
        self.assertEqual(result["source_positive_count"], 3)
        self.assertEqual(result["recall_at_10"], 1 / 3)
        self.assertEqual(result["rare_positive_count"], 2)
        self.assertEqual(result["cold_positive_count"], 2)
        self.assertEqual(result["training_unseen_positive_count"], 1)
        self.assertEqual(result["below_five_seen_positive_count"], 1)
        self.assertEqual(result["training_unseen_recall_at_10"], 0)
        self.assertEqual(result["abstentions"], {"missing_feature_row": 1})
        self.assertFalse(result["precision_available"])


if __name__ == "__main__":
    unittest.main()
