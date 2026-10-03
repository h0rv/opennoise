"""Recovery-port custody attacks and compatibility with the current frozen FMA contracts."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
from scipy import sparse

from opennoise.analysis.connected_split import (
    TrackIdentity,
    audit_split,
    connected_components,
    seal_source_split,
    verify_source_split,
)
from opennoise.common import canonical_json
from opennoise.ml.fma_acoustic_baseline import (
    NativeTrack,
    PositiveMetrics,
    fit_positive_gaussian,
    native_components,
)
from scripts.build_connected_track_split import main as split_main
from scripts.build_recording_fact_split import main as recording_split_main

ROOT = Path(__file__).resolve().parents[2]


class SealedCustodyTests(unittest.TestCase):
    @staticmethod
    def source() -> bytes:
        return canonical_json(
            {
                "rows": [
                    {
                        "id": f"example:track:{i}",
                        "artist_ids": [f"example:artist:{i}"],
                        "album_ids": [f"example:album:{i}"],
                        "features": {"value": float(i)},
                        "labels": ["source:a"],
                    }
                    for i in range(50)
                ]
            }
        )

    def test_changed_raw_numeric_values_with_same_identities_fail(self) -> None:
        source = self.source()
        manifest = seal_source_split(source, seed="frozen", source_format="numeric")
        changed = json.loads(source)
        changed["rows"][0]["features"]["value"] = 12345.0
        raw = canonical_json(changed)
        next_manifest = seal_source_split(raw, seed="frozen", source_format="numeric")
        self.assertEqual(
            manifest["normalized_records_sha256"], next_manifest["normalized_records_sha256"]
        )
        with self.assertRaisesRegex(ValueError, "prescribed source bytes"):
            verify_source_split(raw, manifest, seed="frozen", source_format="numeric")

    def test_clean_audit_and_rehashed_assignments_do_not_authorize_fold_changes(self) -> None:
        source = self.source()
        manifest = seal_source_split(source, seed="frozen", source_format="numeric")
        assignments = manifest["assignments"]
        self.assertIsInstance(assignments, dict)
        assert isinstance(assignments, dict)
        identity = next(iter(assignments))
        assignments[identity] = "test" if assignments[identity] != "test" else "train"
        # Keep the forged component and overlap audit internally consistent too.
        components = manifest["components"]
        assert isinstance(components, list)
        for component in components:
            if identity in component["tracks"]:
                component["partition"] = assignments[identity]
        records = [
            TrackIdentity(
                track_id=row["id"], artist_ids=row["artist_ids"], album_ids=row["album_ids"]
            )
            for row in json.loads(source)["rows"]
        ]
        manifest["audit"] = audit_split(records, assignments)
        self.assertTrue(manifest["audit"]["known_identity_isolation_passed"])
        rewritten = json.loads(canonical_json(manifest))
        with self.assertRaisesRegex(ValueError, "assignment"):
            verify_source_split(source, rewritten, seed="frozen", source_format="numeric")
        changed_seed = seal_source_split(source, seed="posthoc", source_format="numeric")
        with self.assertRaises(ValueError):
            verify_source_split(source, changed_seed, seed="frozen", source_format="numeric")

    def test_cli_seal_replay_and_fresh_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, output = root / "source.json", root / "split.json"
            source.write_bytes(self.source())
            arguments = [
                "split",
                "--source",
                str(source),
                "--output",
                str(output),
                "--seed",
                "frozen",
                "--input-format",
                "numeric",
            ]
            with patch("sys.argv", arguments), patch("sys.stdout"):
                self.assertEqual(split_main(), 0)
                with self.assertRaises(FileExistsError):
                    split_main()
            with patch("sys.argv", [*arguments, "--verify"]), patch("sys.stdout"):
                self.assertEqual(split_main(), 0)
            original = output.read_bytes()
            source.write_bytes(source.read_bytes() + b"\n")
            with patch("sys.argv", [*arguments, "--verify"]), self.assertRaises(ValueError):
                split_main()
            self.assertEqual(output.read_bytes(), original)

    def test_native_recording_credits_are_a_structural_example_only(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "split.json"
            with patch(
                "sys.argv",
                [
                    "split",
                    "--pack",
                    str(ROOT / "data/examples/recording-facts"),
                    "--output",
                    str(output),
                ],
            ):
                self.assertEqual(recording_split_main(), 0)
            report = json.loads(output.read_bytes())
            self.assertTrue(report["source"]["native_source_replay_passed"])
            self.assertTrue(report["audit"]["known_identity_isolation_passed"])
            self.assertFalse(report["evaluation_ready"])
            self.assertEqual(
                report["audit"]["tracks_missing_identity_kind"]["album_ids"],
                len(report["assignments"]),
            )

    def test_native_sonic_exact_core_credits_demo_retains_missing_album_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "native-split.json"
            with patch(
                "sys.argv",
                [
                    "split",
                    "--pack",
                    str(ROOT / "data/examples/native-sonic"),
                    "--pack-kind",
                    "native-sonic",
                    "--output",
                    str(output),
                ],
            ):
                self.assertEqual(recording_split_main(), 0)
            report = json.loads(output.read_bytes())
            self.assertEqual(len(report["assignments"]), 55)
            self.assertEqual(report["source"]["selected_source_records"], 100)
            self.assertEqual(report["audit"]["tracks_missing_identity_kind"]["recording_ids"], 0)
            self.assertEqual(report["audit"]["tracks_missing_identity_kind"]["album_ids"], 55)
            self.assertEqual(report["audit"]["tracks_missing_identity_kind"]["duplicate_ids"], 55)
            self.assertFalse(report["audit"]["unknown_identity_leakage_excluded"])
            self.assertFalse(report["evaluation_ready"])


class CurrentFmaCompatibilityTests(unittest.TestCase):
    def test_generic_complete_identity_components_equal_current_native_components(self) -> None:
        native = [
            NativeTrack(1, 30, artist_known=True, album_id=10, genre_ids=(), targets_missing=False),
            NativeTrack(2, 20, artist_known=False, album_id=10, genre_ids=(), targets_missing=True),
            NativeTrack(3, 20, artist_known=False, album_id=11, genre_ids=(), targets_missing=True),
            NativeTrack(4, 40, artist_known=True, album_id=11, genre_ids=(), targets_missing=False),
            NativeTrack(
                5, 50, artist_known=True, album_id=None, genre_ids=(), targets_missing=False
            ),
            NativeTrack(
                6, 60, artist_known=True, album_id=None, genre_ids=(), targets_missing=False
            ),
        ]
        groups = native_components(native, [[4, 5]])
        supplied = [
            TrackIdentity(
                track_id=f"fma:track:{row.track_id}",
                artist_ids=(f"fma:artist:{row.artist_id}",),
                album_ids=(f"fma:album:{row.album_id}",) if row.album_id else (),
                duplicate_ids=("fma:duplicate:4-5",) if row.track_id in {4, 5} else (),
            )
            for row in native
        ]
        expected = tuple(
            sorted(
                tuple(
                    sorted(
                        f"fma:track:{r.track_id}"
                        for r in native
                        if r.artist_id is not None and groups[r.artist_id] == component
                    )
                )
                for component in set(groups.values())
            )
        )
        self.assertEqual(connected_components(supplied), expected)

    def test_unknown_holdout_labels_keep_queries_without_inventing_negatives(self) -> None:
        metric = PositiveMetrics([1, 2, 3], np.array([200, 30, 0]))
        metric.add([], [0, 1])
        metric.add([0, 2], [], "missing_feature_row")
        metric.add([1], [1, 0])
        report = metric.report()
        self.assertEqual(
            (report["queries"], report["labeled_queries"], report["unlabeled_queries"]), (3, 2, 1)
        )
        self.assertEqual(report["source_positive_count"], 3)
        self.assertAlmostEqual(report["recall_at_10"], 1 / 3)
        self.assertAlmostEqual(report["mean_reciprocal_rank"], 0.5)
        self.assertEqual(report["training_unseen_positive_count"], 1)
        self.assertEqual(report["abstentions"], {"missing_feature_row": 1})
        self.assertFalse(report["precision_available"])
        unknown = PositiveMetrics([1], np.array([20]))
        unknown.add([], [0])
        unknown_report = unknown.report()
        self.assertEqual(unknown_report["queries"], 1)
        self.assertEqual(unknown_report["labeled_queries"], 0)
        self.assertEqual(unknown_report["source_positive_count"], 0)
        self.assertFalse(unknown_report["precision_available"])

    def test_heldout_features_labels_and_unlabelled_changes_cannot_change_fma_fit(self) -> None:
        features = np.array([[float(i), float(i % 3)] for i in range(14)])
        targets = sparse.csr_matrix(
            np.array([[1, int(i % 2 == 0), int(i == 0)] for i in range(14)])
        )
        training_rows = 10
        training = np.arange(14) < training_rows
        first = fit_positive_gaussian(features, targets, training)
        features[~training] = 1e20
        modified = targets.toarray()
        modified[~training] = 0
        second = fit_positive_gaussian(features, sparse.csr_matrix(modified), training)
        for name in (
            "center",
            "scale",
            "active_columns",
            "quadratic",
            "linear",
            "intercept",
            "active_labels",
            "label_feature_support",
        ):
            np.testing.assert_array_equal(getattr(first, name), getattr(second, name))
        self.assertEqual(first.training_rows, second.training_rows)
