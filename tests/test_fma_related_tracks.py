"""Frozen descriptor ranking: training scope, exact ties and native-component isolation."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from opennoise.ml.fma_related_tracks import (
    BATCH,
    MAX_OFFSET,
    build_related_tracks,
    candidate_roster,
    freeze_protocol,
    nearest_batch,
    normalize,
)


class RelatedTracksTests(unittest.TestCase):
    def test_pinned_pack_tamper_fails_before_roster_or_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "evaluation.json").write_text("{}")
            output = root / "declaration.json"
            with self.assertRaisesRegex(ValueError, "hash/size differs"):
                freeze_protocol(root, output)
            self.assertFalse(output.exists())

    def test_changed_frozen_recipe_rejected_before_feature_access(self) -> None:
        roles = [{"track_id": 1, "component_id": 10, "role": "inner_fit", "artist_known": True}]
        with (
            tempfile.TemporaryDirectory() as temporary,
            patch("opennoise.ml.fma_related_tracks._pack", return_value=({}, {}, roles)),
        ):
            root = Path(temporary)
            declaration = root / "declaration.json"
            protocol = freeze_protocol(root, declaration)
            self.assertEqual(protocol["candidate_ids"], [1])
            with self.assertRaises(FileExistsError):
                freeze_protocol(root, declaration)
            protocol["neighbors"] = 10
            declaration.write_text(json.dumps(protocol))
            output = root / "output"
            with self.assertRaisesRegex(ValueError, "protocol differs"):
                build_related_tracks(root, root / "nonexistent_features", declaration, output)
            self.assertFalse(output.exists())

    def test_roster_is_component_unique_and_ignores_nonfit_and_targets(self) -> None:
        roles = [
            {"track_id": identity, "component_id": component, "role": role, "artist_known": True}
            for identity, component, role in (
                (1, 10, "inner_fit"),
                (2, 10, "inner_fit"),
                (3, 20, "inner_fit"),
                (4, 30, "inner_calibration"),
                (5, 40, "validation_diagnostic"),
                (6, 50, "test_diagnostic"),
            )
        ]
        first = candidate_roster(roles)
        self.assertEqual(len(first), 2)
        self.assertIn(3, first)
        self.assertEqual(len(set(first) & {1, 2}), 1)
        mutated = [{**row, "genre_ids": [999]} for row in roles]
        self.assertEqual(first, candidate_roster(list(reversed(mutated))))

    def test_cross_component_neighbors_exact_ties_and_no_candidates(self) -> None:
        candidates = np.array([[0.0, 0.0], [1.0, 0.0], [-1.0, 0.0], [0.0, 2.0]])
        ids = np.array([1, 9, 3, 4])
        components = np.array([1, 2, 3, 4])
        self.assertEqual(
            nearest_batch(np.array([[0.0, 0.0]]), np.array([1]), candidates, ids, components),
            [[3, 9, 4]],
        )
        self.assertEqual(
            nearest_batch(
                np.array([[0.0, 0.0]]), np.array([1]), candidates[:1], ids[:1], components[:1]
            ),
            [[]],
        )

    def test_matches_independent_direct_difference_and_stable_top_six(self) -> None:
        rng = np.random.default_rng(1901)
        candidates = rng.normal(size=(31, 4))
        queries = rng.normal(size=(8, 4))
        ids = np.arange(100, 131)[::-1]
        components = np.arange(31) + 1
        query_components = np.arange(8) + 1
        actual = nearest_batch(queries, query_components, candidates, ids, components)
        expected = []
        for query, component in zip(queries, query_components, strict=True):
            distances = np.sum((candidates - query) ** 2, axis=1)
            distances[components == component] = np.inf
            order = np.lexsort((ids, distances))[:6]
            expected.append(ids[order].tolist())
        self.assertEqual(actual, expected)
        ties = np.ones((20, 4))
        self.assertEqual(
            nearest_batch(queries[:1], np.array([99]), ties, np.arange(20, 0, -1), np.arange(20)),
            [[1, 2, 3, 4, 5, 6]],
        )

    def test_normalization_uses_saved_statistics_without_refitting(self) -> None:
        model = {
            "center": np.array([10.0, 99.0]),
            "scale": np.array([2.0, 0.0]),
            "active_columns": np.array([True, False]),
        }
        values = np.array(
            [[12.0, np.nan], [10 + 2 * MAX_OFFSET, 0], [10 + 2 * (MAX_OFFSET + 1), 0], [np.nan, 0]]
        )
        normalized, supported = normalize(values, model)
        np.testing.assert_allclose(normalized[:3, 0], [1, MAX_OFFSET, MAX_OFFSET + 1])
        self.assertEqual(supported.tolist(), [True, True, False, False])
        changed = values.copy()
        changed[1:] = 100000
        self.assertEqual(normalize(changed, model)[0][0, 0], 1)
        np.testing.assert_equal(model["center"], [10, 99])

    def test_distance_block_limit_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "block bounds"):
            nearest_batch(
                np.zeros((BATCH + 1, 2)),
                np.zeros(BATCH + 1),
                np.zeros((1, 2)),
                np.array([1]),
                np.array([1]),
            )


if __name__ == "__main__":
    unittest.main()
