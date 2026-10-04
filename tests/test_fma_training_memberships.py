from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path
from typing import Any
from unittest.mock import patch

import numpy as np
from scipy import sparse

from opennoise.common import sha256_file
from opennoise.ml.fma_acoustic_baseline import (
    NativeTrack,
    PositiveGaussian,
    artist_group_fold,
    fit_positive_gaussian,
    score_positive_gaussian,
)
from opennoise.ml.fma_memberships import evaluate_rows
from opennoise.ml.fma_training_memberships import (
    DECLARATION_SHA256,
    ROLE_SEED,
    fit_thresholds,
    role,
    training_suggest,
)
from scripts import calibrate_fma_training_memberships as runner

FIT_END = 200
VALIDATION_END = 250
SYNTHETIC_FIT_ROWS = 60
BOUNDARY_LABEL = 20


class TrainingMembershipTests(unittest.TestCase):
    def test_roles_are_fixed_whole_training_components(self) -> None:
        for component in range(1, 500):
            expected = int(hashlib.sha256(f"{ROLE_SEED}\0{component}".encode()).hexdigest(), 16) % 5
            self.assertEqual(
                role(0, component, artist_known=True),
                "inner_calibration" if expected == 0 else "inner_fit",
            )
            self.assertEqual(role(1, component, artist_known=True), "validation_diagnostic")
            self.assertEqual(role(2, component, artist_known=True), "test_diagnostic")
            self.assertEqual(role(0, component, artist_known=False), "unresolved_artist")
        with self.assertRaisesRegex(ValueError, "native component"):
            role(0, None, artist_known=True)

    @staticmethod
    def calibration_rows() -> list[dict[str, Any]]:
        components = [
            c for c in range(1, 500) if role(0, c, artist_known=True) == "inner_calibration"
        ][:20]
        return [
            {
                "track_id": c,
                "component_id": c,
                "fold": 0,
                "artist_known": True,
                "role": "inner_calibration",
                "genre_ids": [1],
                "ranked_genre_ids": [1, 2],
                "reason": None,
            }
            for c in components
        ]

    def test_thresholds_reject_outer_fit_unknown_and_duplicate_queries(self) -> None:
        rows = self.calibration_rows()
        for changes in ({"fold": 1}, {"fold": 2}, {"artist_known": False}, {"role": "inner_fit"}):
            with self.assertRaisesRegex(ValueError, "non-calibration"):
                fit_thresholds([{**rows[0], **changes}], [1, 2])
        with self.assertRaisesRegex(ValueError, "repeated query"):
            fit_thresholds([rows[0], rows[0]], [1, 2])

    def test_rare_and_missing_scores_abstain_by_component_not_track_count(self) -> None:
        rows = self.calibration_rows()
        thresholds = fit_thresholds(rows, [1, 2])
        self.assertEqual(thresholds[1]["threshold_rank"], 1)
        self.assertIsNone(thresholds[2]["threshold_rank"])
        self.assertIsNone(fit_thresholds(rows[:19], [1, 2])[1]["threshold_rank"])
        repeated = [{**rows[0], "track_id": i} for i in range(100)]
        self.assertEqual(fit_thresholds(repeated, [1, 2])[1]["positive_components"], 1)
        missing = [{**r, "ranked_genre_ids": []} for r in rows]
        self.assertIsNone(fit_thresholds(missing, [1, 2])[1]["threshold_rank"])

    def test_nonfit_features_and_labels_cannot_change_any_fitted_parameter(self) -> None:
        rng = np.random.default_rng(13)
        x = rng.normal(size=(300, 4))
        y = sparse.csr_matrix(np.tile([1.0, 0.0], (300, 1)))
        roles = np.array(
            [
                role(0 if i < FIT_END else 1 if i < VALIDATION_END else 2, i + 1, artist_known=True)
                for i in range(300)
            ]
        )
        training = roles == "inner_fit"
        original = fit_positive_gaussian(x, y, training)
        changed_x = x.copy()
        changed_x[~training] = np.nan
        changed_y = y.toarray()
        changed_y[~training] = [0, 1]
        changed = fit_positive_gaussian(changed_x, sparse.csr_matrix(changed_y), training)
        for key, value in asdict(original).items():
            np.testing.assert_array_equal(value, getattr(changed, key))

    def test_outer_mutations_cannot_change_calibration_scores_or_thresholds(self) -> None:
        rng = np.random.default_rng(14)
        rows = self.calibration_rows()
        x = rng.normal(size=(100, 4))
        training = np.arange(100) < SYNTHETIC_FIT_ROWS
        y = sparse.csr_matrix(np.tile([1.0, 1.0], (100, 1)))
        model = fit_positive_gaussian(x, y, training)
        scores, _ = score_positive_gaussian(model, x[60:80])

        def thresholds_from_scores(values: np.ndarray) -> dict[int, dict[str, Any]]:
            ranked = np.argsort(-values, axis=1, kind="stable") + 1
            return fit_thresholds(
                [
                    {**row, "ranked_genre_ids": ranking.tolist()}
                    for row, ranking in zip(rows, ranked, strict=True)
                ],
                [1, 2],
            )

        before = thresholds_from_scores(scores)
        x[80:] = 1e20
        changed_y = y.toarray()
        changed_y[80:] = 0
        changed = fit_positive_gaussian(x, sparse.csr_matrix(changed_y), training)
        after_scores, _ = score_positive_gaussian(changed, x[60:80])
        np.testing.assert_array_equal(scores, after_scores)
        self.assertEqual(before, thresholds_from_scores(after_scores))

    def test_missing_and_unlabeled_queries_remain_in_denominators(self) -> None:
        rows = self.calibration_rows()
        thresholds = fit_thresholds(rows, [1, 2])
        report, outputs = evaluate_rows(
            [
                {**rows[0], "ranked_genre_ids": [], "reason": "missing_feature_row"},
                {**rows[1], "genre_ids": []},
            ],
            thresholds,
            {1: 99, 2: 0},
            suggestion_function=training_suggest,
        )
        self.assertEqual(report["queries"], 2)
        self.assertEqual(report["source_positives"], 1)
        self.assertEqual(report["unlabeled_queries"], 1)
        self.assertEqual(report["recovered_source_positives"], 0)
        self.assertEqual(len(outputs), 2)

    def test_stability_includes_just_outside_threshold_competitor(self) -> None:
        thresholds = {
            i: {"threshold_rank": 100, "component_worst_positive_ranks": [100] * 20}
            for i in range(1, 22)
        }
        thresholds[21] = {"threshold_rank": 20, "component_worst_positive_ranks": [20] * 20}
        thresholds[20] = {"threshold_rank": 23, "component_worst_positive_ranks": [23] * 20}
        output = training_suggest(
            {"track_id": 1, "ranked_genre_ids": list(range(1, 22)), "reason": None}, thresholds
        )
        membership = next(v for v in output["memberships"] if v["genre_id"] == BOUNDARY_LABEL)
        self.assertTrue(membership["threshold_stable_under_plus_minus_2_rank"])
        self.assertFalse(membership["set_stable_under_plus_minus_2_rank"])

    def test_runner_uses_only_inner_fit_and_seals_before_outer_scoring(self) -> None:

        tracks = tuple(
            NativeTrack(
                i, i, artist_known=True, album_id=None, genre_ids=(1, 2), targets_missing=False
            )
            for i in range(1, 301)
        )
        features = np.column_stack((np.arange(1, 301), np.sin(np.arange(300)))).astype(np.float32)
        ledger: list[dict[str, Any]] = [
            {
                "track_id": t.track_id,
                "artist_id": t.artist_id,
                "artist_known": True,
                "album_id": None,
                "component_id": t.artist_id,
                "fold": artist_group_fold(t.track_id),
            }
            for t in tracks
        ]
        expected_fit = np.array(
            [role(r["fold"], r["component_id"], artist_known=True) == "inner_fit" for r in ledger]
        )
        outer_ids = {r["track_id"] for r in ledger if r["fold"] != 0}
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in ("metadata", "features", "baseline"):
                (root / name).mkdir()
            for name in (
                "metadata/corpus-receipt.json",
                "features/projection-receipt.json",
                "native.json",
            ):
                (root / name).write_text("{}")
            evaluation = {}
            for fold, name in ((1, "validation"), (2, "test")):
                n = sum(r["fold"] == fold for r in ledger)
                evaluation[name] = {
                    "acoustic": {"queries": n, "labeled_queries": n, "source_positive_count": n * 2}
                }
            baseline = {
                "artifacts": {},
                "metadata_receipt_sha256": sha256_file(root / "metadata/corpus-receipt.json")[0],
                "feature_receipt_sha256": sha256_file(root / "features/projection-receipt.json")[0],
                "evaluation": evaluation,
                "coverage": {},
                "partition": {},
                "limitations": [],
            }
            (root / "baseline/evaluation.json").write_text(json.dumps(baseline))
            runner.write_rows(root / "baseline/native-folds.jsonl.zst", ledger)
            declaration = {
                "limits": runner.LIMITS,
                "native_declaration_sha256": sha256_file(root / "native.json")[0],
                "baseline_evaluation_sha256": sha256_file(root / "baseline/evaluation.json")[0],
                "revision": "test",
            }
            (root / "declaration.json").write_text(json.dumps(declaration))
            args = argparse.Namespace(
                metadata=root / "metadata",
                features=root / "features",
                baseline=root / "baseline",
                native_declaration=root / "native.json",
                declaration=root / "declaration.json",
                output=root / "output",
            )

            def bound_hash(path: Path) -> tuple[str, int]:
                if path == args.declaration:
                    return DECLARATION_SHA256, path.stat().st_size
                return sha256_file(path)

            def checked_fit(
                x: np.ndarray, y: sparse.csr_matrix, mask: np.ndarray
            ) -> PositiveGaussian:
                np.testing.assert_array_equal(mask, expected_fit)
                return fit_positive_gaussian(x, y, mask)

            def checked_score(
                model: PositiveGaussian, x: np.ndarray
            ) -> tuple[np.ndarray, list[str | None]]:
                if any(int(v) in outer_ids for v in x[:, 0]):
                    seal = json.loads((args.output / "pre-diagnostic-seal.json").read_bytes())
                    for name, digest in seal["artifacts"].items():
                        self.assertEqual(sha256_file(args.output / name)[0], digest)
                return score_positive_gaussian(model, x)

            with (
                patch.object(runner, "sha256_file", side_effect=bound_hash),
                patch.object(runner, "load_metadata", return_value=(tracks, (1, 2), {})),
                patch.object(
                    runner, "load_features", return_value=(np.arange(1, 301), features, [], {})
                ),
                patch.object(
                    runner, "native_components", return_value={i: i for i in range(1, 301)}
                ),
                patch.object(runner, "fit_positive_gaussian", side_effect=checked_fit) as fitted,
                patch.object(runner, "score_positive_gaussian", side_effect=checked_score),
            ):
                result = runner.calibrate(args)
            self.assertEqual(fitted.call_count, 1)
            self.assertTrue(result["seal_rechecked_after_diagnostics"])
            self.assertEqual(result["coverage"]["inner_fit"]["queries"], int(expected_fit.sum()))
