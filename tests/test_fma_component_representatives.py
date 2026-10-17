"""Synthetic geometry, paired mechanisms and closed-output contracts only."""

import copy
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import BinaryIO, cast
from unittest.mock import patch

import numpy as np
import zstandard
from scipy import sparse

from opennoise.ml import fma_component_representatives as experiment
from opennoise.ml import fma_component_representatives_custody as custody
from opennoise.ml import fma_component_representatives_stats as stats
from tests.test_fma_retrieval_loss import fixture, write_records


class RepresentativeTests(unittest.TestCase):
    def test_saved_scale_support_and_inactive_zero(self) -> None:
        features = np.array([[1.0, 5.0], [12.0, 5.0], [12.1, 5.0], [0.0, 5.0], [1.0, np.nan]])
        units, supported, usable = experiment.raw_geometry(
            features, np.zeros(2), np.array([1.0, 0.0]), np.array([True, False])
        )
        self.assertEqual(supported.tolist(), [True, True, False, True, False])
        self.assertEqual(usable.tolist(), [True, True, False, False, False])
        np.testing.assert_array_equal(units[:, 0], [1, 1, 0, 0, 0])
        with self.assertRaisesRegex(ValueError, "normalization"):
            experiment.raw_geometry(features, np.zeros(2), np.zeros(2), np.array([True, False]))
        units, _, usable = experiment.raw_geometry(
            features, np.zeros(2), np.zeros(2), np.array([False, False])
        )
        self.assertEqual(units.shape, (5, 0))
        self.assertFalse(usable.any())

    def test_farthest_native_ties_and_identical_seconds(self) -> None:
        ids = np.array([1, 2, 3, 4, 5, 6, 7])
        groups = np.array([10, 10, 10, 20, 20, 10, 30])
        folds = np.array([1, 1, 1, 1, 1, 1, 0])
        units = np.array([[1.0, 0], [-1, 0], [-1, 0], [0, 1], [0, 1], [0, -1], [1, 0]])
        usable = np.array([True, True, True, True, True, False, True])
        rows = experiment.choose_representatives(ids, groups, folds, units, usable, [1, 4], 0)
        self.assertEqual([row["second_track_id"] for row in rows], [2, 5])
        self.assertEqual(rows[0]["eligible_records"], 3)
        self.assertEqual(rows[0]["training_records"], 4)
        self.assertEqual(rows[0]["second_cosine_distance"], 2)
        self.assertTrue(rows[1]["identical_unit_vector"])
        self.assertEqual(rows[1]["second_cosine_distance"], 0)
        for originals in ([1, 2], [7], [999], [4, 1]):
            with self.assertRaises(ValueError):
                experiment.choose_representatives(ids, groups, folds, units, usable, originals, 0)

    def test_max_winner_and_component_order_ties(self) -> None:
        winners, scores = experiment.component_neighbors(
            np.array([[0.5, 0.5, 0.1]]),
            np.array([10, 20, 30]),
            np.array([[0.5, 0.8, 100.0]]),
            np.array([5, 25, 0]),
        )
        self.assertEqual(winners.tolist(), [[25, 5, 30]])
        np.testing.assert_allclose(scores, [[0.8, 0.5, 0.1]])
        winners, _ = experiment.component_neighbors(
            np.ones((1, 12)), np.arange(1, 13), np.ones((1, 12)), np.zeros(12, dtype=int)
        )
        self.assertEqual(winners.tolist(), [list(range(1, 11))])

    def test_all_ordered_buckets_and_vote_ties(self) -> None:
        ranking = list(range(1, 12))
        self.assertEqual(stats.bucket(1, {1}, {1}, ranking, "raw_zero_norm"), 0)
        self.assertEqual(stats.bucket(12, {1}, {1}, ranking, None), 1)
        self.assertEqual(stats.bucket(12, {12}, {1}, ranking, None), 2)
        self.assertEqual(stats.bucket(11, {11}, {11}, ranking, None), 3)
        self.assertEqual(stats.bucket(1, {1}, {1}, ranking, None), 4)
        self.assertEqual(experiment.vote_ranking([1, 2], {1: {3, 1}, 2: {2, 3}}), [3, 1, 2])

    def test_expanded_pool_gain_and_loss_conservation(self) -> None:
        component = stats.empty_component(9, 0)
        old = {"ranking": [1], "neighbor_ids": [1, 2], "reason": None, "descriptor_available": True}
        new = {"ranking": [3], "neighbor_ids": [3, 2], "reason": None, "descriptor_available": True}
        popularity = {"ranking": [1, 3], "reason": None, "descriptor_available": True}
        labels = {1: {1}, 2: set(), 3: {3}}
        stats.accumulate(
            component, {1, 3}, [old, new, popularity], [{1}, {1, 3}], labels, {1: 1, 2: 2, 3: 1}
        )
        stats.accumulate(
            component, set(), [old, new, popularity], [{1}, {1, 3}], labels, {1: 1, 2: 2, 3: 1}
        )
        result = stats.summarize([component])
        self.assertEqual(component["transitions"][1][4], 1)
        self.assertEqual(component["transitions"][4][2], 1)
        self.assertEqual(result["gained_added_pool"], 1)
        self.assertEqual(result["lost_hits"], 1)
        self.assertEqual(result["arms"][stats.ARMS[1]]["query_mrr"], 1)
        self.assertEqual(result["arms"][stats.ARMS[0]]["positive_recall10"], 0.5)
        broken = copy.deepcopy(component)
        broken["transitions"][0][0] += 1
        with self.assertRaisesRegex(ValueError, "transitions"):
            stats.summarize([broken])

    def test_empty_and_unlabeled_retrieval_not_fake_abstention(self) -> None:
        component = stats.empty_component(1, 0)
        prediction = {
            "ranking": [],
            "neighbor_ids": [1],
            "reason": None,
            "descriptor_available": True,
        }
        popularity = {"ranking": [], "reason": None, "descriptor_available": True}
        stats.accumulate(
            component, {7}, [prediction, prediction, popularity], [{7}, {7}], {1: set()}, {1: 1}
        )
        self.assertEqual(component["buckets"][0], [0, 0, 1, 0, 0])
        self.assertEqual(component["statistics"][0][-2:], [1, 0])
        result = stats.summarize([])
        self.assertIsNone(result["arms"][stats.ARMS[0]]["positive_recall10"])
        self.assertIsNone(result["arms"][stats.ARMS[0]]["component_equal_mrr"])

    def test_distribution_concentration_has_no_public_rosters(self) -> None:
        self.assertEqual(
            stats.label_histogram([1, 2, 3], {1: set(), 2: {1}, 3: {1}}), [[0, 1], [1, 2]]
        )
        result = stats.concentration({1: 3, 2: 1})
        self.assertEqual(result["inverse_herfindahl"], 1.6)
        self.assertEqual(result["largest_share"], 0.75)
        self.assertNotIn("counts", result)
        self.assertIsNone(stats.concentration({})["inverse_herfindahl"])

    def test_compressed_writer_rejects_before_write(self) -> None:
        buffer = io.BytesIO()
        writer = custody.BoundedWriter(buffer, 3)
        writer.write(b"abc")
        with self.assertRaisesRegex(ValueError, "100 MB"):
            writer.write(b"d")
        self.assertEqual(buffer.getvalue(), b"abc")
        buffer = io.BytesIO()
        with zstandard.ZstdCompressor().stream_writer(
            cast("BinaryIO", custody.BoundedWriter(buffer, 100)), closefd=False
        ) as stream:
            stream.write(b"example")
        self.assertEqual(
            zstandard.ZstdDecompressor().stream_reader(io.BytesIO(buffer.getvalue())).read(),
            b"example",
        )

    def test_replay_rejects_extra_root_and_budget_before_derivation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in ["summary", *(f"fold-{fold}" for fold in range(5))]:
                (root / name).mkdir()
            (root / "unexpected").write_bytes(b"x")
            with self.assertRaisesRegex(ValueError, "exactly five"):
                experiment.replay_summary(root / "seal", root)
            with (
                patch.object(custody, "MAX_OUTPUT_BYTES", 0),
                self.assertRaisesRegex(ValueError, "100 MB"),
            ):
                experiment.replay_summary(root / "seal", root)

    def test_code_binding_contains_all_executed_local_dependencies(self) -> None:
        bound = custody.code()
        self.assertIn("src/opennoise/ml/fma_retrieval_loss_custody.py", bound)
        self.assertIn("src/opennoise/ml/fma_component_representatives_stats.py", bound)
        self.assertIn("scripts/run_fma_component_representatives.py", bound)

    def test_streamed_fold_replays_and_detects_changed_geometry(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            original = root / "original" / "fold-0"
            original.mkdir(parents=True)
            _, records = fixture(original)
            for record in records:
                record["arms"]["raw44_neighbors"]["cosine_distances"] = [0.0, 1.0]
            write_records(original, records)
            with np.load(original / "statistics.npz") as saved:
                values = saved["values"].copy()
            values[0, [0, 2, 3, 4], 4] = 1
            np.savez(original / "statistics.npz", components=np.array([3, 4]), values=values)
            np.savez(
                original / "embedding.npz",
                center=np.zeros(2),
                scale=np.ones(2),
                active_columns=np.ones(2, dtype=bool),
            )
            data = SimpleNamespace(
                ids=np.array([1, 2, 3, 4]),
                groups=np.array([1, 2, 3, 4]),
                inner_folds=np.array([1, 1, 0, 0]),
                features=np.array([[1.0, 0], [0, 1], [1, 0], [1, 0]]),
                labels=[1, 3],
                targets=sparse.csr_matrix([[1, 0], [0, 0], [1, 1], [0, 0]]),
            )
            seal = root / "seal.json"
            seal.write_text("{}")
            spec = {"source": "synthetic", "original_run": str(original.parent)}
            with (
                patch.object(experiment, "verify_seal", return_value=spec),
                patch.object(experiment, "load_corpus", return_value=data),
            ):
                output = root / "output"
                experiment.run_fold(seal, output, 0)
                experiment.replay_fold(seal, output, 0)
                custody.verify_stage(output / "fold-0", seal, "fold-0")
                report = json.loads((output / "fold-0" / "components.json").read_bytes())
                self.assertEqual(report["components"][0]["buckets"][0], [0, 1, 0, 0, 1])
                data.features[2] = [0, 1]
                with self.assertRaisesRegex(ValueError, "raw geometry"):
                    experiment.run_fold(seal, root / "changed", 0)
