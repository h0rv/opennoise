import unittest

from musix.history.signals.audit import _histogram, _knn_audit
from musix.models.historical_signal import HistoricalSignalArtifact, HistoricalSignalNeighbor


class HistoricalSignalAuditTests(unittest.TestCase):
    def test_histogram_partitions_every_value_once(self) -> None:
        buckets = _histogram([0, 1, 2, 5, 10], (0, 1, 5, 10))
        self.assertEqual(tuple(bucket.count for bucket in buckets), (1, 2, 1, 1))

    def test_knn_audit_distinguishes_mutual_and_one_way_edges(self) -> None:
        artifact = HistoricalSignalArtifact.model_construct(
            neighbors=(
                _edge("genre:a", "genre:b"),
                _edge("genre:b", "genre:a"),
                _edge("genre:a", "genre:c"),
            )
        )
        audit = _knn_audit(artifact)
        self.assertEqual(audit.directed_edge_count, 3)
        self.assertEqual(audit.reciprocal_pair_count, 1)
        self.assertEqual(audit.one_way_edge_count, 1)
        self.assertAlmostEqual(audit.mutual_directed_edge_fraction, 2 / 3)


def _edge(genre_id: str, neighbor_genre_id: str) -> HistoricalSignalNeighbor:
    return HistoricalSignalNeighbor(
        genre_id=genre_id,
        neighbor_genre_id=neighbor_genre_id,
        rank=1,
        weighted_jaccard=0.5,
        cosine=0.5,
        idf_overlap=1.0,
        shared_artist_count=1,
    )


if __name__ == "__main__":
    unittest.main()
