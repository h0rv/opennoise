import unittest

from pydantic import ValidationError

from musix.historical_signal_model import _idf_candidates, _knn
from musix.models.historical_signal import HistoricalSignalSettings


class HistoricalSignalModelTests(unittest.TestCase):
    def test_idf_overlap_is_not_relabelled_weighted_jaccard(self) -> None:
        memberships = {
            "genre:a": {"artist:shared", "artist:a-only"},
            "genre:b": {"artist:shared"},
            "genre:c": {"artist:c-only"},
        }
        settings = HistoricalSignalSettings(neighbors_per_genre=2)
        candidates, _artist_degrees = _idf_candidates(memberships, settings)
        neighbors = _knn(tuple(sorted(memberships)), candidates, settings)
        relation = next(
            item
            for item in neighbors
            if item.genre_id == "genre:a" and item.neighbor_genre_id == "genre:b"
        )
        self.assertNotEqual(relation.idf_overlap, relation.weighted_jaccard)
        self.assertGreater(relation.idf_overlap, relation.weighted_jaccard)

    def test_embedding_method_and_method_identifier_are_bound(self) -> None:
        with self.assertRaises(ValidationError):
            HistoricalSignalSettings(embedding_method="normalized_laplacian_spectral")
        spectral = HistoricalSignalSettings(
            method="idf_membership_knn_spectral_v1",
            embedding_method="normalized_laplacian_spectral",
        )
        self.assertEqual(spectral.method, "idf_membership_knn_spectral_v1")


if __name__ == "__main__":
    unittest.main()
