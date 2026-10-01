"""Evidence-driven coarse frontier and self-similarity regression tests."""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import cast

import numpy as np
from scipy import sparse

from opennoise.ml.emergent_adaptive_topics import (
    _cross_profile_coherence,
    adaptive_frontiers,
    fit_adaptive_topics,
)
from opennoise.ml.emergent_topics import TopicSettings, _Node, load_features


def _feature(value: str) -> dict[str, object]:
    return {"namespace": "artist_tag", "value": value, "weight": 1, "evidence_refs": ["native:tag"]}


class AdaptiveTopicTests(unittest.TestCase):
    def test_orthogonal_profiles_cannot_pass_on_centroid_self_similarity(self) -> None:
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "features.jsonl"
            rows = [
                {"artist_mbid": f"{family}-{i}", "features": [_feature(family)]}
                for family in ("jazz", "techno")
                for i in range(20)
            ]
            path.write_text("".join(json.dumps(row) + "\n" for row in rows))
            data = load_features(path)
            root = _Node(np.array([0, 1]), np.ones(2), 0, None)
            self.assertAlmostEqual(_cross_profile_coherence(root, data), 0)
            frontiers, _metadata, states = adaptive_frontiers(data, data, TopicSettings())
            self.assertEqual(len(frontiers[0]), 2)
            self.assertTrue(all(state.startswith("supported_") for state in states.values()))

    def test_indivisible_coherent_profile_does_not_force_a_broad_count(self) -> None:
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "features.jsonl"
            rows = [
                {"artist_mbid": f"artist-{i}", "features": [_feature("jazz"), _feature("bebop")]}
                for i in range(40)
            ]
            path.write_text("".join(json.dumps(row) + "\n" for row in rows))
            data = load_features(path)
            model, assignments = fit_adaptive_topics(data)
            coverage = cast("dict[str, object]", model["coverage"])
            self.assertEqual(coverage["community_count_by_level"], {"broad": 1})
            self.assertEqual(assignments["artist-0"], assignments["artist-1"])

    def test_insufficient_source_split_is_explicitly_unsupported(self) -> None:
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "features.jsonl"
            rows = [
                {"artist_mbid": f"{family}-{i}", "features": [_feature(family)]}
                for family in ("jazz", "techno")
                for i in range(3)
            ]
            path.write_text("".join(json.dumps(row) + "\n" for row in rows))
            data = load_features(path)
            frontiers, _metadata, states = adaptive_frontiers(data, data, TopicSettings())
            self.assertEqual(len(frontiers[0]), 1)
            self.assertEqual(set(states.values()), {"abstained_no_supported_coarse_split"})
            self.assertEqual(sparse.csr_matrix(data.group_matrix).shape[0], 2)
