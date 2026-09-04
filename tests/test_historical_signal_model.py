import unittest

import numpy as np
from pydantic import ValidationError

from musix.historical_signal_model import _graph_hierarchy, _idf_candidates, _knn
from musix.models.historical_signal import HistoricalSignalSettings

_MICROGENRE_LEVEL = 2
_MICROGENRE_MAX_MEMBERS = 2


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

    def test_graph_hierarchy_is_deterministic_bounded_and_name_independent(self) -> None:
        genre_ids = tuple(f"genre:{index:02d}" for index in range(32))
        graph = [dict[int, float]() for _ in genre_ids]
        for index in range(len(genre_ids) - 1):
            weight = 0.9 if index // 8 == (index + 1) // 8 else 0.1
            graph[index][index + 1] = weight
            graph[index + 1][index] = weight
        settings = HistoricalSignalSettings(
            hierarchy_umbrella_max_members=32,
            hierarchy_subcommunity_max_members=8,
            hierarchy_microgenre_max_members=2,
        )
        positions = np.array([(index / 31, (31 - index) / 31) for index in range(32)])
        first, first_assignments = _graph_hierarchy(
            graph,
            genre_ids,
            {genre_id: f"first {genre_id}" for genre_id in genre_ids},
            positions,
            settings,
        )
        second, second_assignments = _graph_hierarchy(
            graph,
            genre_ids,
            {genre_id: f"second {genre_id}" for genre_id in genre_ids},
            positions,
            settings,
        )

        self.assertEqual(first_assignments, second_assignments)
        self.assertEqual(
            [(item.hierarchy_id, item.parent_id, item.children_ids) for item in first],
            [(item.hierarchy_id, item.parent_id, item.children_ids) for item in second],
        )
        self.assertEqual(set(first_assignments), set(range(len(genre_ids))))
        microgenres = [item for item in first if item.level == _MICROGENRE_LEVEL]
        self.assertTrue(microgenres)
        self.assertTrue(all(item.member_count <= _MICROGENRE_MAX_MEMBERS for item in microgenres))
        self.assertTrue(all(item.provenance == "graph_derived_h3_similarity" for item in first))

    def test_graph_hierarchy_bundles_disconnected_components_at_the_umbrella_level(self) -> None:
        genre_ids = tuple(f"genre:{index:02d}" for index in range(16))
        graph = [dict[int, float]() for _ in genre_ids]
        for index in range(0, len(genre_ids), 2):
            graph[index][index + 1] = 0.8
            graph[index + 1][index] = 0.8
        positions = np.array([(index / 15, (15 - index) / 15) for index in range(16)])
        hierarchy, assignments = _graph_hierarchy(
            graph,
            genre_ids,
            {genre_id: genre_id for genre_id in genre_ids},
            positions,
            HistoricalSignalSettings(
                hierarchy_umbrella_max_members=32,
                hierarchy_subcommunity_max_members=8,
                hierarchy_microgenre_max_members=2,
            ),
        )

        umbrellas = [item for item in hierarchy if item.level == 0]
        self.assertEqual(len(umbrellas), 1)
        self.assertEqual(umbrellas[0].member_count, len(genre_ids))
        self.assertEqual(len(assignments), len(genre_ids))


if __name__ == "__main__":
    unittest.main()
