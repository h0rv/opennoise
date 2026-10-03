from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from typing import Any

from opennoise.common import sha256_file
from opennoise.ml.fma_memberships import (
    calibration_half,
    component_threshold,
    evaluate_rows,
    fit_thresholds,
    replay_membership_pack,
    suggest,
)


def row(component: int, labels: list[int], ranks: list[int], fold: int = 1) -> dict[str, Any]:
    """Build a native query fixture without invented negatives."""
    return {
        "track_id": component,
        "component_id": component,
        "genre_ids": labels,
        "ranked_genre_ids": ranks,
        "fold": fold,
        "reason": None,
    }


class PositiveMembershipTests(unittest.TestCase):
    def test_minimum_components_and_impossible_tail_abstain(self) -> None:
        self.assertIsNone(component_threshold([1] * 19, 164))
        self.assertEqual(component_threshold([1] * 20, 164), 1)
        self.assertIsNone(component_threshold([165] * 20, 164))

    def test_train_confirmation_and_test_forbidden_in_calibration(self) -> None:
        calibration = next(c for c in range(1, 100) if calibration_half(c))
        confirmation = next(c for c in range(1, 100) if not calibration_half(c))
        for bad in (
            row(calibration, [1], [1], 0),
            row(calibration, [1], [1], 2),
            row(confirmation, [1], [1]),
        ):
            with self.assertRaisesRegex(ValueError, "non-calibration"):
                fit_thresholds([bad], [1])

    def test_many_tracks_from_same_component_are_one_support_unit(self) -> None:
        component = next(c for c in range(1, 100) if calibration_half(c))
        result = fit_thresholds([row(component, [1], [1])] * 100, [1])
        self.assertEqual(result[1]["positive_components"], 1)
        self.assertIsNone(result[1]["threshold_rank"])

    def test_missing_positive_rank_is_retained_and_unknown_absence_is_not_negative(self) -> None:
        components = [c for c in range(1, 100) if calibration_half(c)][:20]
        records = [row(c, [1], []) for c in components]
        result = fit_thresholds(records, [1, 2])
        self.assertEqual(result[1]["component_worst_positive_ranks"], [3] * 20)
        self.assertEqual(result[2]["positive_components"], 0)
        self.assertIsNone(result[1]["threshold_rank"])

    def test_worst_rank_across_component_used_not_average(self) -> None:
        components = [c for c in range(1, 100) if calibration_half(c)][:20]
        records = [row(c, [1], [1, 2]) for c in components]
        records += [row(c, [1], [2, 1]) for c in components]
        self.assertEqual(fit_thresholds(records, [1, 2])[1]["threshold_rank"], 2)

    def test_bounded_overlap_is_explicit_not_probability(self) -> None:
        thresholds = {
            label: {
                "threshold_rank": 30,
                "positive_components": 20,
                "component_worst_positive_ranks": [30] * 20,
            }
            for label in range(1, 31)
        }
        result = suggest(row(1, [], list(range(1, 31))), thresholds)
        self.assertEqual(len(result["memberships"]), 20)
        self.assertEqual(result["uncapped_memberships"], 30)
        self.assertFalse(result["musical_probability"])
        self.assertFalse(result["memberships"][-1]["set_stable_under_plus_minus_2_rank"])

    def test_unlabelled_queries_and_missing_positives_stay_in_denominator(self) -> None:
        thresholds = {
            1: {
                "threshold_rank": 1,
                "positive_components": 20,
                "component_worst_positive_ranks": [1] * 20,
            }
        }
        missing = {**row(2, [1], []), "reason": "missing_feature_row"}
        report, _ = evaluate_rows([row(1, [], [1]), missing], thresholds, {1: 10})
        self.assertEqual(report["queries"], 2)
        self.assertEqual(report["unlabeled_queries"], 1)
        self.assertEqual(report["source_positives"], 1)
        self.assertEqual(report["bounded_positive_recall"], 0)
        self.assertEqual(report["abstentions"], {"missing_feature_row": 1})


class SavedMembershipTests(unittest.TestCase):
    baseline = Path(__file__).resolve().parents[1] / "data/examples/fma-acoustic-baseline"
    pack = Path(__file__).resolve().parents[1] / "data/examples/fma-source-memberships"

    def test_all_exact_memberships_metrics_and_calibration_replay(self) -> None:
        result = replay_membership_pack(self.baseline, self.pack)
        self.assertTrue(result["all_thresholds_metrics_memberships_match"])
        self.assertEqual(result["confirmation_queries"], 3236)
        self.assertFalse(result["model_refit"])

    def test_self_rehashed_changed_threshold_still_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            copied = Path(temporary) / "pack"
            shutil.copytree(self.pack, copied)
            thresholds_path = copied / "thresholds.json"
            thresholds = json.loads(thresholds_path.read_bytes())
            thresholds[next(iter(thresholds))]["threshold_rank"] = 1
            thresholds_path.write_text(json.dumps(thresholds))
            receipt_path = copied / "pack-receipt.json"
            receipt = json.loads(receipt_path.read_bytes())
            digest, size = sha256_file(thresholds_path)
            receipt["files"]["thresholds.json"] = {"sha256": digest, "bytes": size}
            receipt_path.write_text(json.dumps(receipt))
            with self.assertRaisesRegex(ValueError, "threshold replay differs"):
                replay_membership_pack(self.baseline, copied)
