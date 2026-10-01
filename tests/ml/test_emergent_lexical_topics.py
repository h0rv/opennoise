"""Native text representation and source-only projection regression tests."""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import cast

import numpy as np

from opennoise.ml.emergent_lexical_topics import (
    fit_lexical_topics,
    lexical_graph,
    lexical_representation,
)
from opennoise.ml.emergent_topics import TopicSettings, load_features


def _feature(value: str, namespace: str = "artist_tag") -> dict[str, object]:
    return {"namespace": namespace, "value": value, "weight": 1, "evidence_refs": ["native:tag"]}


class LexicalTopicTests(unittest.TestCase):
    def test_text_links_related_values_without_artist_cooccurrence(self) -> None:
        values = ("black metal", "death metal", "jazz", "techno")
        graph, metadata = lexical_graph(values)
        self.assertGreater(graph[0, 1], 0)
        self.assertEqual(graph[0, 2], 0)
        self.assertEqual(graph[2, 3], 0)
        self.assertEqual(graph.diagonal().sum(), 0)
        self.assertEqual(metadata["word_vocabulary_size"], 5)

    def test_native_text_does_not_turn_substring_noise_into_a_link(self) -> None:
        graph, _ = lexical_graph(("trap", "trapeze", "opera", "operatic"))
        self.assertEqual(graph[0, 1], 0)
        self.assertEqual(graph[0, 2], 0)

    def test_profile_equivalence_and_observed_centroid_projection_are_preserved(self) -> None:
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "features.jsonl"
            rows = [
                {
                    "artist_mbid": f"artist-{leaf}-{artist}",
                    "features": [
                        _feature(f"family {leaf // 4}"),
                        _feature(f"branch {leaf // 2}"),
                        _feature(f"texture {leaf}"),
                        *(
                            [
                                _feature(f"texture {leaf}", "artist_genre"),
                                _feature("london", "area"),
                            ]
                            if artist % 2
                            else []
                        ),
                    ],
                }
                for leaf in range(8)
                for artist in range(20)
            ]
            path.write_text("".join(json.dumps(row) + "\n" for row in rows))
            data = load_features(path)
            represented, metadata = lexical_representation(data)
            self.assertEqual(data.group_keys, represented.group_keys)
            np.testing.assert_array_equal(data.artist_groups, represented.artist_groups)
            context = [i for i, (namespace, _) in enumerate(data.features) if namespace == "area"]
            self.assertEqual(represented.group_matrix[:, context].nnz, 0)
            self.assertFalse(metadata["external_pretrained_weights_used"])
            model, assignments = fit_lexical_topics(
                data, TopicSettings(depths=(1, 2, 3)), include_centroids=True
            )
            for leaf in range(8):
                self.assertEqual(assignments[f"artist-{leaf}-0"], assignments[f"artist-{leaf}-1"])
            centers = cast("dict[str, list[float]]", model["centroids"])
            cores = cast("dict[str, list[int]]", model["core_group_ids"])
            for key, center in centers.items():
                absent = np.asarray(data.group_matrix[cores[key]].sum(axis=0)).ravel() == 0
                self.assertTrue(np.all(np.array(center)[absent] == 0))
            communities = {
                str(item["id"]): item
                for item in cast("list[dict[str, object]]", model["communities"])
            }
            for entries in assignments.values():
                present = {item["community_id"] for item in entries}
                for entry in entries:
                    parent = communities[str(entry["community_id"])]["parent_id"]
                    self.assertTrue(parent is None or parent in present)
