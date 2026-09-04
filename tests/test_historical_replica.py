import unittest

from musix.historical_replica import deterministic_h2_split, name_tfidf_cosine


class HistoricalReplicaTests(unittest.TestCase):
    def test_name_signal_is_coordinate_free_and_discriminative(self) -> None:
        scores = name_tfidf_cosine(
            {
                "a": "deep house",
                "b": "minimal house",
                "c": "baroque chamber music",
            }
        )
        self.assertGreater(scores[("a", "b")], 0.0)
        self.assertGreater(scores[("a", "b")], scores[("a", "c")])

    def test_split_is_deterministic_and_disjoint(self) -> None:
        identifiers = tuple(f"genre:{number}" for number in range(30))
        train, holdout = deterministic_h2_split(identifiers)
        self.assertEqual((train, holdout), deterministic_h2_split(identifiers))
        self.assertFalse(train & holdout)
        self.assertEqual(train | holdout, set(identifiers))


if __name__ == "__main__":
    unittest.main()
