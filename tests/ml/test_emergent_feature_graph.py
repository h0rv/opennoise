"""Feature graph topology and identical-profile partition regression tests."""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import cast

import numpy as np
from scipy import sparse

from opennoise.ml.emergent_feature_graph import (
    fit_graph_topics,
    graph_partition,
    musical_feature_graph,
)
from opennoise.ml.emergent_topics import TopicSettings, load_features


def _feature(value: str, namespace: str = "artist_tag") -> dict[str, object]:
    return {"namespace": namespace, "value": value, "weight": 1, "evidence_refs": ["native:test"]}


class FeatureGraphTests(unittest.TestCase):
    def test_modularity_does_not_merge_disconnected_music_families(self) -> None:
        block = np.ones((4, 4)) - np.eye(4)
        graph = sparse.block_diag([sparse.csr_matrix(block), block], format="csr")
        labels = graph_partition(graph)
        self.assertEqual(len(set(labels[:4])), 1)
        self.assertEqual(len(set(labels[4:])), 1)
        self.assertNotEqual(labels[0], labels[4])
        np.testing.assert_array_equal(labels, graph_partition(graph))

    def test_duplicate_facets_do_not_double_graph_evidence_or_split_profiles(self) -> None:
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "features.jsonl"
            rows = [
                {
                    "artist_mbid": f"a-{family}-{i}",
                    "features": [
                        _feature(f"family {family}"),
                        _feature(f"texture {family}"),
                        *(
                            [
                                _feature(f"texture {family}", "artist_genre"),
                                _feature("london", "area"),
                            ]
                            if i % 2
                            else []
                        ),
                    ],
                }
                for family in range(3)
                for i in range(20)
            ]
            path.write_text("".join(json.dumps(row) + "\n" for row in rows))
            data = load_features(path)
            values, graph = musical_feature_graph(data)
            self.assertEqual(len(values), 6)
            self.assertEqual(graph.nnz, 6)
            np.testing.assert_allclose(graph.data, 1)
            model, assignments = fit_graph_topics(data, TopicSettings(depths=(2, 3, 4)))
            self.assertEqual(
                cast("dict[str, object]", model["coverage"])["community_count_by_level"],
                {"broad": 3},
            )
            for family in range(3):
                self.assertEqual(assignments[f"a-{family}-0"], assignments[f"a-{family}-1"])
            self.assertEqual(len({items[0]["community_id"] for items in assignments.values()}), 3)

    def test_isolated_singleton_evidence_abstains_from_fine_levels(self) -> None:
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "features.jsonl"
            rows = [
                {
                    "artist_mbid": f"artist-{family}-{i}",
                    "features": [_feature(f"isolated {family}")],
                }
                for family, count in enumerate((20, 3))
                for i in range(count)
            ]
            path.write_text("".join(json.dumps(row) + "\n" for row in rows))
            data = load_features(path)
            _values, graph = musical_feature_graph(data)
            self.assertEqual(graph.nnz, 0)
            model, assignments = fit_graph_topics(data)
            coverage = cast("dict[str, object]", model["coverage"])
            self.assertEqual(coverage["community_count_by_level"], {"broad": 1})
            self.assertEqual(assignments["artist-1-0"], [])
            self.assertEqual([item["level"] for item in assignments["artist-0-0"]], ["broad"])

    def test_high_degree_bridge_does_not_erase_family_topology(self) -> None:
        block = np.ones((5, 5)) - np.eye(5)
        graph = sparse.block_diag([sparse.csr_matrix(block), block], format="lil")
        graph[4, 5] = graph[5, 4] = 0.01
        labels = graph_partition(graph.tocsr())
        self.assertEqual(len(set(labels[:5])), 1)
        self.assertEqual(len(set(labels[5:])), 1)
        self.assertNotEqual(labels[0], labels[-1])
