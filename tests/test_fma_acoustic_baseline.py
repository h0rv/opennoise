from __future__ import annotations

import bz2
import csv
import io
import json
import tempfile
import unittest
import zlib
from pathlib import Path
from unittest.mock import patch

import numpy as np
from scipy import sparse

from opennoise.ingest.fma_features import (
    MEMBER_NAME,
    SELECTED_COLUMNS,
    project_feature_stream,
    selected_feature_positions,
)
from opennoise.ml.fma_acoustic_baseline import (
    NativeTrack,
    PositiveMetrics,
    artist_group_fold,
    fit_positive_gaussian,
    native_components,
    score_positive_gaussian,
    training_baseline_rankings,
)


def _headers() -> list[list[str]]:
    columns = [*reversed(SELECTED_COLUMNS), ("zcr", "std", 1)]
    return [
        ["feature", *[column[0] for column in columns]],
        ["statistics", *[column[1] for column in columns]],
        ["number", *[str(column[2]) for column in columns]],
    ]


class NativeFeatureTests(unittest.TestCase):
    def test_declared_zcr_alias_selects_mean_not_std(self) -> None:
        columns, positions = selected_feature_positions(_headers())
        selected = [columns[position - 1] for position in positions]
        self.assertEqual(selected, list(SELECTED_COLUMNS))
        self.assertIn(("zcr", "mean", 1), selected)
        self.assertNotIn(("zcr", "std", 1), selected)

    def test_missing_or_duplicated_native_channel_rejected(self) -> None:
        headers = _headers()
        for header in headers:
            header[1] = header[2]
        with self.assertRaises(ValueError):
            selected_feature_positions(headers)

    def test_native_stream_crc_and_full_cell_duplicates(self) -> None:
        text = io.StringIO(newline="")
        writer = csv.writer(text)
        writer.writerows(_headers())
        writer.writerow(["track_id", *([""] * (len(SELECTED_COLUMNS) + 1))])
        writer.writerows(
            [
                [1, *(["1"] * len(SELECTED_COLUMNS)), "2"],
                [2, *(["1"] * len(SELECTED_COLUMNS)), "2"],
                [3, *(["1"] * len(SELECTED_COLUMNS)), "3"],
            ]
        )
        native = text.getvalue().encode()
        member = {
            "payload_path": "native.range",
            "payload_prefix_bytes": len(MEMBER_NAME),
            "uncompressed_bytes": len(native),
            "crc32": zlib.crc32(native),
        }
        source = {"member": member, "declaration_sha256": "declared", "attribution": "FMA"}
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "native.range").write_bytes(MEMBER_NAME.encode() + bz2.compress(native))
            (root / "source-receipt.json").write_text("{}")
            with patch("opennoise.ingest.fma_features.verify_feature_source", return_value=source):
                receipt = project_feature_stream(root, root / "projection")
            self.assertEqual(receipt["rows"], 3)
            self.assertEqual(receipt["native_uncompressed_bytes"], len(native))
            groups = json.loads(
                (root / "projection/duplicate-native-feature-cells.json").read_bytes()
            )
            self.assertEqual(groups, [[1, 2]])
            member["crc32"] = 0
            with (
                patch("opennoise.ingest.fma_features.verify_feature_source", return_value=source),
                self.assertRaises(ValueError),
            ):
                project_feature_stream(root, root / "bad-crc")


class NativeSplitTests(unittest.TestCase):
    def test_missing_artist_bridge_stops_historical_split(self) -> None:
        rows = [
            NativeTrack(1, 30, artist_known=True, album_id=10, genre_ids=(), targets_missing=False),
            NativeTrack(
                2, None, artist_known=False, album_id=10, genre_ids=(), targets_missing=False
            ),
            NativeTrack(3, 5, artist_known=True, album_id=11, genre_ids=(), targets_missing=False),
        ]
        with self.assertRaisesRegex(ValueError, "fresh split revision"):
            native_components(rows, [[2, 3]])

    def test_unresolved_artist_bridges_native_albums(self) -> None:
        rows = [
            NativeTrack(1, 30, artist_known=True, album_id=10, genre_ids=(), targets_missing=False),
            NativeTrack(
                2, 20, artist_known=False, album_id=10, genre_ids=(), targets_missing=False
            ),
            NativeTrack(
                3, 20, artist_known=False, album_id=11, genre_ids=(), targets_missing=False
            ),
            NativeTrack(4, 40, artist_known=True, album_id=11, genre_ids=(), targets_missing=False),
            NativeTrack(
                5, 50, artist_known=True, album_id=None, genre_ids=(), targets_missing=False
            ),
        ]
        groups = native_components(rows, [[4, 5]])
        self.assertEqual(groups, {20: 20, 30: 20, 40: 20, 50: 20})
        self.assertEqual(groups, native_components(list(reversed(rows)), [[5, 4]]))
        self.assertEqual(len({artist_group_fold(group) for group in groups.values()}), 1)

    def test_no_track_id_fallback_for_missing_artist(self) -> None:
        self.assertEqual(
            native_components(
                [
                    NativeTrack(
                        1, None, artist_known=False, album_id=1, genre_ids=(), targets_missing=False
                    )
                ],
                [],
            ),
            {},
        )
        with self.assertRaises(ValueError):
            artist_group_fold(0)


class PositiveOnlyModelTests(unittest.TestCase):
    @staticmethod
    def fixture() -> tuple[np.ndarray, sparse.csr_matrix, np.ndarray]:
        training_rows = 10
        x = np.array([[float(i), float(i % 3)] for i in range(14)])
        y = sparse.csr_matrix(np.array([[1, int(i % 2 == 0), int(i == 0)] for i in range(14)]))
        return x, y, np.arange(14) < training_rows

    def test_held_out_features_and_targets_do_not_affect_fit(self) -> None:
        x, y, training = self.fixture()
        first = fit_positive_gaussian(x, y, training)
        x[~training] = 1e12
        changed = y.toarray()
        changed[~training] = 0
        second = fit_positive_gaussian(x, sparse.csr_matrix(changed), training)
        for field in ("center", "scale", "quadratic", "linear", "intercept", "active_labels"):
            np.testing.assert_array_equal(getattr(first, field), getattr(second, field))
        self.assertFalse(first.active_labels[-1])

    def test_missing_and_ood_queries_abstain(self) -> None:
        x, y, training = self.fixture()
        model = fit_positive_gaussian(x, y, training)
        scores, reasons = score_positive_gaussian(model, np.array([[np.nan, 0], [1e9, 0], [3, 1]]))
        self.assertEqual(reasons, ["missing_descriptors", "outside_training_support", None])
        self.assertTrue(np.isneginf(scores[:2]).all())
        self.assertTrue(np.isneginf(scores[:, -1]).all())

    def test_training_overflow_cannot_silently_remove_a_descriptor(self) -> None:
        for extreme in (np.full(14, 1e308), np.tile([1e200, -1e200], 7)):
            with self.subTest(extreme=extreme[0]):
                x, y, training = self.fixture()
                x[:, 1] = extreme
                with (
                    np.errstate(all="raise"),
                    self.assertRaisesRegex(ValueError, "normalization overflows"),
                ):
                    fit_positive_gaussian(x, y, training)

    def test_held_out_extremes_do_not_trigger_training_overflow(self) -> None:
        x, y, training = self.fixture()
        first = fit_positive_gaussian(x, y, training)
        x[~training] = 1e308
        with np.errstate(all="raise"):
            second = fit_positive_gaussian(x, y, training)
        for field in ("center", "scale", "quadratic", "linear", "intercept", "active_columns"):
            np.testing.assert_array_equal(getattr(first, field), getattr(second, field))

    def test_constant_training_descriptor_is_still_omitted(self) -> None:
        x, y, training = self.fixture()
        x[:, 1] = 2.0
        model = fit_positive_gaussian(x, y, training)
        np.testing.assert_array_equal(model.active_columns, [True, False])
        np.testing.assert_array_equal(model.center, [4.5, 2.0])
        self.assertEqual(model.scale[1], 0.0)
        scores, reasons = score_positive_gaussian(model, np.array([[4.0, 2.0]]))
        self.assertEqual(reasons, [None])
        self.assertTrue(np.isfinite(scores[:, model.active_labels]).all())

    def test_integer_training_masks_cannot_select_held_out_rows(self) -> None:
        x, y, training = self.fixture()
        training = np.roll(training, 2)
        self.assertFalse(training[0])
        first = fit_positive_gaussian(x, y, training)
        x[~training] = 1e12
        second = fit_positive_gaussian(x, y, training)
        np.testing.assert_array_equal(first.center, second.center)
        for dtype in (np.int8, np.int64, np.uint8, np.float64, object):
            with self.subTest(dtype=dtype), self.assertRaisesRegex(ValueError, "boolean row mask"):
                fit_positive_gaussian(x, y, training.astype(dtype))

    def test_misaligned_training_inputs_fail_before_fitting(self) -> None:
        x, y, training = self.fixture()
        for features, targets, mask in (
            (x, y, training[:, None]),
            (x, y, training[:-1]),
            (x, y, np.ones((), dtype=bool)),
            (x[:, 0], y, training),
            (x, y[:-1], training),
        ):
            with self.subTest(shape=mask.shape), self.assertRaisesRegex(ValueError, "aligned"):
                fit_positive_gaussian(features, targets, mask)

    def test_abstentions_and_rare_cold_targets_keep_denominators(self) -> None:
        metric = PositiveMetrics([1, 2, 3], np.array([200, 30, 0]))
        metric.add([0, 2], [], "missing_feature_row")
        metric.add([1], [1, 0])
        metric.add([], [], "missing_descriptors")
        report = metric.report()
        self.assertEqual(report["source_positive_count"], 3)
        self.assertAlmostEqual(report["recall_at_5"], 1 / 3)
        self.assertEqual(report["rare_positive_count"], 2)
        self.assertEqual(report["cold_positive_count"], 1)
        self.assertEqual(report["training_unseen_positive_count"], 1)
        self.assertEqual(report["cold_recall_at_5"], 0)
        self.assertEqual(sum(report["abstentions"].values()), 2)
        self.assertFalse(report["precision_available"])

    def test_unseen_low_genre_id_cannot_gain_baseline_recovery_credit(self) -> None:
        support = np.array([0, 20, 40])
        popularity, constant = training_baseline_rankings(support)
        self.assertEqual(popularity, [2, 1])
        self.assertEqual(constant, [1, 2])
        for ranking in (popularity, constant):
            metric = PositiveMetrics([1, 2, 3], support)
            metric.add([0], ranking)
            self.assertEqual(metric.report()["recall_at_5"], 0)
            self.assertEqual(metric.report()["mean_reciprocal_rank"], 0)


if __name__ == "__main__":
    unittest.main()
