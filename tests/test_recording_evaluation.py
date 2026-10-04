"""Component isolation, held-out invariance, full denominators and native replay contracts."""

from __future__ import annotations

import copy
import gzip
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

import numpy as np

from opennoise.ml import recording_evaluation as model
from opennoise.pipeline import recording_evaluation as pipeline
from opennoise.pipeline.recording_feature_companion import build_companion

ROOT = Path(__file__).resolve().parents[1]
FACTS = ROOT / "data/examples/recording-facts"
SONIC = ROOT / "data/examples/native-sonic"
COLUMNS = ["varying", "periodic", "missing", "constant"]


def identity(number: int) -> str:
    """Provide separate canonical native-ID-shaped synthetic fixture namespaces."""
    return f"{number:08x}-0000-4000-8000-000000000000"


def fixture(count: int = 40) -> list[dict[str, Any]]:
    """Synthetic per-recording descriptors, never empirical music evidence."""
    return [
        {
            "recording_mbid": identity(i),
            "artist_mbid": identity(1000 + i),
            "credited_artist_mbids": [identity(1000 + i)],
            "values": [float(i), float(i % 7), None, 2.0],
            "join_state": "joined",
            "source": {"capture_index": i},
            "companion": None,
        }
        for i in range(1, count + 1)
    ]


def frames_for(rows: list[dict[str, Any]], ledger: dict[str, Any]) -> list[dict[str, Any]]:
    """Apply the fixed policy once to each held-out component fold."""
    return [model.fit_frame(rows, ledger, fold, COLUMNS) for fold in range(model.POLICY["folds"])]


class RecordingIsolationTests(unittest.TestCase):
    def test_missing_feature_bridge_connects_all_native_co_credits(self) -> None:
        rows = fixture(3)
        rows[1]["credited_artist_mbids"] = [rows[0]["artist_mbid"], rows[2]["artist_mbid"]]
        rows[1]["join_state"] = "unavailable_sonic_source"
        rows[1]["values"] = [None] * len(COLUMNS)
        ledger = model.component_ledger(rows)
        self.assertEqual(ledger["components"], 1)
        self.assertEqual(len({r["fold"] for r in ledger["records"]}), 1)
        self.assertEqual(model.component_ledger(list(reversed(rows))), ledger)
        self.assertFalse(ledger["isolation"]["full_leakage_isolation_established"])
        self.assertEqual(ledger["isolation"]["album_edges"], "unavailable")

    def test_conflicting_companion_credit_connects_conservatively(self) -> None:
        rows = fixture(2)
        rows[0]["join_state"] = "credit_conflict"
        rows[0]["companion"] = {"credit_fact": {"credited_artist_mbids": [rows[1]["artist_mbid"]]}}
        self.assertEqual(model.component_ledger(rows)["components"], 1)

    def test_unknown_credit_cohort_associations_are_not_invented_edges(self) -> None:
        rows = fixture(2)
        for row in rows:
            row["credited_artist_mbids"] = None
            row["artist_mbid"] = identity(9999)
            row["join_state"] = "missing_observation_credit"
        self.assertEqual(model.component_ledger(rows)["components"], 2)

    def test_repeated_observations_do_not_reweight_training_or_drop_queries(self) -> None:
        rows = fixture()
        ledger = model.component_ledger(rows)
        before = frames_for(rows, ledger)
        repeated = rows + [copy.deepcopy(rows[0]) for _ in range(10)]
        after_ledger = model.component_ledger(repeated)
        self.assertEqual(after_ledger["unique_recordings"], len(rows))
        after = frames_for(repeated, after_ledger)
        self.assertEqual(before, after)
        queries, summary = model.compare_recordings(repeated, after_ledger, after)
        self.assertEqual(len(queries), len(repeated))
        self.assertEqual(summary["unique_recording_queries"], len(rows))

    def test_conflicting_duplicate_vectors_quarantine_recording(self) -> None:
        rows = fixture()
        duplicate = copy.deepcopy(rows[0])
        duplicate["values"][0] += 1
        rows.append(duplicate)
        ledger = model.component_ledger(rows)
        frames = frames_for(rows, ledger)
        for frame in frames:
            self.assertNotIn(duplicate["recording_mbid"], frame["training_recordings"])
        queries, _ = model.compare_recordings(rows, ledger, frames)
        for query in (queries[0], queries[-1]):
            self.assertEqual(query["outcome"], "conflicting_recording_observations")
            self.assertEqual(query["numeric"], [])


class RecordingFrameTests(unittest.TestCase):
    def test_heldout_values_and_missingness_cannot_change_feature_frame(self) -> None:
        rows = fixture()
        ledger = model.component_ledger(rows)
        fold = 0
        original = model.fit_frame(rows, ledger, fold, COLUMNS)
        self.assertEqual(original["state"], "fitted")
        heldout = {r["recording_mbid"] for r in ledger["records"] if r["fold"] == fold}
        self.assertTrue(heldout)
        for replacement in ([1e100, 1e100, 1e100, 1e100], [None] * len(COLUMNS)):
            changed = copy.deepcopy(rows)
            for row in changed:
                if row["recording_mbid"] in heldout:
                    row["values"] = replacement.copy()
            self.assertEqual(model.component_ledger(changed), ledger)
            self.assertEqual(model.fit_frame(changed, ledger, fold, COLUMNS), original)

    def test_training_frame_omits_missing_and_constant_columns_without_imputation(self) -> None:
        rows = fixture()
        ledger = model.component_ledger(rows)
        frame = model.fit_frame(rows, ledger, 0, COLUMNS)
        self.assertEqual(frame["columns"], [0, 1])
        selected = [
            r["values"][:2] for r in rows if r["recording_mbid"] in frame["fitted_recordings"]
        ]
        np.testing.assert_allclose(frame["center"], np.array(selected).mean(axis=0))
        np.testing.assert_allclose(frame["scale"], np.array(selected).std(axis=0))
        row = copy.deepcopy(rows[0])
        row["values"][0] = None
        self.assertEqual(model.transform(row, frame), ([], "missing_required_descriptors"))
        row["values"][0] = 1e100
        self.assertEqual(model.transform(row, frame), ([], "outside_training_support"))

    def test_tiny_training_population_yields_explicit_abstention(self) -> None:
        rows = fixture(2)
        ledger = model.component_ledger(rows)
        frames = frames_for(rows, ledger)
        queries, summary = model.compare_recordings(rows, ledger, frames)
        self.assertEqual(summary["observation_outcomes"], {"insufficient_training_support": 2})
        self.assertTrue(all(not row["numeric"] and not row["fixed_hash"] for row in queries))

    def test_rankings_use_training_only_cross_component_pool_and_stable_ties(self) -> None:
        rows = fixture()
        rows[1]["credited_artist_mbids"] = rows[0]["credited_artist_mbids"].copy()
        ledger = model.component_ledger(rows)
        frames = frames_for(rows, ledger)
        loaded = json.loads(pipeline.canonical(frames))
        queries, summary = model.compare_recordings(rows, ledger, loaded)
        meta = {r["recording_mbid"]: r for r in ledger["records"]}
        self.assertIsNone(summary["relevance_metrics"])
        for query in queries:
            neighbors = [r["recording_mbid"] for r in query["numeric"]]
            self.assertEqual(len(neighbors), len(query["fixed_hash"]))
            for neighbor in neighbors + query["fixed_hash"]:
                self.assertNotEqual(meta[neighbor]["fold"], query["fold"])
                self.assertNotEqual(meta[neighbor]["component_id"], query["component_id"])
        shuffled, _ = model.compare_recordings(list(reversed(rows)), ledger, loaded)
        self.assertEqual(
            {q["recording_mbid"]: q["numeric"] for q in queries},
            {q["recording_mbid"]: q["numeric"] for q in shuffled},
        )

    def test_numeric_rankings_match_independent_dense_distance_and_identity_ties(self) -> None:
        rows = fixture()
        for i, row in enumerate(rows):
            row["values"] = [float(i % 3), float(4 - i % 3), None, 2.0]
        ledger = model.component_ledger(rows)
        frames = frames_for(rows, ledger)
        queries, _ = model.compare_recordings(rows, ledger, frames)
        by_id = {r["recording_mbid"]: r for r in rows}
        for query in queries:
            frame = frames[query["fold"]]
            ids = frame["fitted_recordings"]
            matrix = np.array([by_id[i]["values"][:2] for i in ids], dtype=float)
            vector = np.array(by_id[query["recording_mbid"]]["values"][:2], dtype=float)
            distances = np.linalg.norm((matrix - vector) / np.array(frame["scale"]), axis=1)
            expected = sorted(zip(distances.tolist(), ids, strict=True))[
                : model.POLICY["neighbors"]
            ]
            self.assertEqual(
                [r["recording_mbid"] for r in query["numeric"]], [i for _, i in expected]
            )
            np.testing.assert_allclose(
                [r["distance"] for r in query["numeric"]], [v for v, _ in expected]
            )

    def test_incomplete_loaded_frame_roster_cannot_omit_queries(self) -> None:
        rows = fixture()
        ledger = model.component_ledger(rows)
        with self.assertRaisesRegex(ValueError, "one ordered frame"):
            model.compare_recordings(rows, ledger, frames_for(rows, ledger)[:-1])


class RecordingEvaluationReplayTests(unittest.TestCase):
    def inputs(self, root: Path) -> pipeline.Inputs:
        companion = root / "companion"
        build_companion(FACTS, SONIC, companion)
        return pipeline.Inputs(FACTS, SONIC, companion)

    def test_authentic_sources_full_denominators_export_load_and_replay(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            inputs = self.inputs(root)
            declaration, output = root / "declaration.json", root / "output"
            frozen = pipeline.freeze(inputs, declaration)
            original_source = (inputs.companion / "features.jsonl.gz").read_bytes()
            report = pipeline.run(inputs, declaration, output)
            self.assertEqual(report["summary"]["observation_queries"], 36)
            self.assertEqual(sum(report["summary"]["observation_outcomes"].values()), 36)
            self.assertEqual(len(report["artist_observation_outcomes"]), 10)
            self.assertIsNone(report["summary"]["relevance_metrics"])
            ledger = json.loads((output / "ledger.json").read_bytes())
            self.assertEqual(ledger["components"], 9)
            self.assertEqual(ledger["unique_recordings"], 36)
            self.assertEqual(pipeline.replay(inputs, declaration, output), report)
            self.assertEqual((inputs.companion / "features.jsonl.gz").read_bytes(), original_source)
            loaded = pipeline.load_frames(output)
            self.assertEqual(len(loaded), model.POLICY["folds"])
            self.assertEqual(frozen["policy"], model.POLICY)
            self.assertFalse(report["isolation"]["full_leakage_isolation_established"])

    def test_policy_mutation_rejected_before_fitting(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            inputs = self.inputs(root)
            declaration = root / "declaration.json"
            policy = pipeline.freeze(inputs, declaration)
            changed = copy.deepcopy(policy)
            changed["policy"]["neighbors"] = 1
            declaration.write_bytes(pipeline.canonical(changed))
            with (
                patch.object(model, "fit_frame") as fit,
                self.assertRaisesRegex(ValueError, "frozen"),
            ):
                pipeline.run(inputs, declaration, root / "output")
            fit.assert_not_called()

    def test_resealed_frame_tampering_fails_independent_native_replay(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            inputs = self.inputs(root)
            declaration, output = root / "declaration.json", root / "output"
            pipeline.freeze(inputs, declaration)
            report = pipeline.run(inputs, declaration, output)
            frames = pipeline.load_frames(output)
            fitted = next(frame for frame in frames if frame["state"] == "fitted")
            fitted["center"][0] += 1
            (output / "frames.json").write_bytes(pipeline.canonical(frames))
            report["files"]["frames.json"] = pipeline.binding(output / "frames.json")
            (output / "report.json").write_bytes(pipeline.canonical(report))
            with self.assertRaisesRegex(ValueError, "independently refitted"):
                pipeline.replay(inputs, declaration, output)

    def test_every_nonjoined_observation_has_empty_results(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            inputs = self.inputs(root)
            declaration, output = root / "declaration.json", root / "output"
            pipeline.freeze(inputs, declaration)
            pipeline.run(inputs, declaration, output)
            with gzip.open(output / "queries.jsonl.gz", "rt") as stream:
                queries = [json.loads(line) for line in stream]
            rejected = [row for row in queries if row["join_state"] != "joined"]
            self.assertEqual(len(rejected), 12)
            self.assertTrue(all(not row["numeric"] and not row["fixed_hash"] for row in rejected))

    def test_distance_budget_fails_without_output(self) -> None:
        with (
            tempfile.TemporaryDirectory() as temporary,
            patch.object(pipeline, "MAX_DISTANCE_PAIRS", 1),
        ):
            root = Path(temporary)
            inputs = self.inputs(root)
            declaration = root / "declaration.json"
            pipeline.freeze(inputs, declaration)
            with self.assertRaisesRegex(ValueError, "distance-pair budget"):
                pipeline.run(inputs, declaration, root / "output")
            self.assertFalse((root / "output").exists())


if __name__ == "__main__":
    unittest.main()
