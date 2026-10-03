import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from opennoise.ml.sonic_retrieval import fit_index, freeze_queries, nearest, source_overlap
from scripts import build_fma_sonic_retrieval as builder


class SonicRetrievalTests(unittest.TestCase):
    def test_training_only_fit_and_component_exclusion(self) -> None:
        features = np.array([[0.0, 2.0], [2.0, 2.0], [99999.0, -4.0]])
        index = fit_index(
            np.array([1, 2, 3]), np.array([10, 20, 30]), features, np.array([True, True, False])
        )
        np.testing.assert_equal(index.center, [1.0, 2.0])
        found, _, reason = nearest(index, np.array([0.0, 2.0]), 10)
        self.assertEqual(found, [2])
        self.assertIsNone(reason)
        self.assertEqual(nearest(index, features[2], 30)[2], "outside_training_support")

    def test_missing_and_unknown_components_abstain(self) -> None:
        index = fit_index(
            np.array([1, 2]), np.array([1, 2]), np.array([[0.0], [2.0]]), np.array([True, True])
        )
        self.assertEqual(nearest(index, np.array([np.nan]), 3)[2], "missing_descriptors")
        self.assertEqual(nearest(index, np.array([1.0]), 0)[2], "unresolved_component")

    def test_ties_are_exact_identity_sorted(self) -> None:
        index = fit_index(
            np.array([7, 2]), np.array([1, 2]), np.array([[0.0], [2.0]]), np.array([True, True])
        )
        self.assertEqual(nearest(index, np.array([1.0]), 3)[0], [2, 7])

    def test_query_selection_does_not_depend_on_order_or_targets(self) -> None:
        self.assertEqual(freeze_queries([1, 2, 3], "seed", 2), freeze_queries([3, 2, 1], "seed", 2))
        with self.assertRaises(ValueError):
            freeze_queries([1, 1], "seed", 2)
        with self.assertRaises(ValueError):
            freeze_queries([0, 1], "seed", 2)

    def test_unlabelled_targets_remain_unknown(self) -> None:
        result = source_overlap([], [[1], []])
        self.assertEqual(result["observed_positives"], 0)
        self.assertEqual(result["neighbors_with_unknown_annotations"], 1)
        self.assertFalse(result["musical_precision_available"])
        self.assertEqual(source_overlap([1, 2], [[1], [3]])["recovered_positives"], 1)

    def test_component_filter_and_ties_cross_numeric_batches(self) -> None:
        identities = np.arange(1, 2051)
        components = np.arange(1, 2051)
        values = np.arange(2050, dtype=float).reshape(-1, 1)
        index = fit_index(identities, components, values, np.ones(2050, dtype=bool))
        found, _, _ = nearest(index, np.array([1024.5]), 1025, limit=3)
        self.assertEqual(found, [1026, 1024, 1027])

    def test_finite_extremes_cannot_produce_a_nonfinite_index(self) -> None:
        with self.assertRaises(ValueError):
            fit_index(
                np.array([1, 2]),
                np.array([1, 2]),
                np.array([[1e308], [-1e308]]),
                np.array([True, True]),
            )

    def test_self_resealed_policy_tampering_rejects_before_descriptor_access(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "declaration.json").write_text("{}")
            with patch.object(builder, "binding", return_value={}):
                policy = builder.declared_policy(root, root, [1], 1)
                for field, invalid in (
                    ("arms", ["fixed_hash_order"]),
                    ("seed", "different"),
                    ("eligible_query_tracks", 99),
                    ("source_absences_are_negatives", True),
                    ("support_gate", "none"),
                ):
                    with self.subTest(field=field):
                        tampered = {**policy, field: invalid}
                        target = root / "retrieval.json"
                        target.write_text(json.dumps(tampered))
                        rows = [SimpleNamespace(track_id=1, artist_known=True)]
                        with (
                            patch.object(builder, "load_metadata", return_value=(rows, [], {})),
                            patch.object(
                                builder, "_json_rows", return_value=[{"track_id": 1, "fold": 1}]
                            ),
                            patch.object(builder, "load_features") as descriptors,
                            self.assertRaisesRegex(ValueError, "frozen retrieval policy"),
                        ):
                            builder.run(root, root, root, target, root / "fresh")
                        descriptors.assert_not_called()
