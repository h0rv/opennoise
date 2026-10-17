"""Matched experiment lifecycle on synthetic data, with no retained outcome reads."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
from scipy import sparse

from opennoise.ml.fma_component_balanced import Corpus
from opennoise.ml.fma_nonlinear_experiment import (
    ARMS,
    _receipt,
    fit_stage,
    score_stage,
    summarize,
    verify_stage,
)


class FactorialLifecycleTests(unittest.TestCase):
    def test_all_queries_retained_matched_fits_and_tamper_refused(self) -> None:
        rng = np.random.default_rng(9)
        x = rng.normal(size=(60, 4))
        full = np.column_stack([x, x**2])
        full[0] = np.nan
        groups = np.arange(60) // 3
        y = sparse.csr_matrix(np.column_stack([np.arange(60) % 2 == 0, np.arange(60) % 3 == 0]))
        data = Corpus(np.arange(1, 61), groups, groups % 5, x, y, (1, 2), groups, groups)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            seal = root / "seal.json"
            seal.write_text("{}")
            output = root / "run"
            with (
                patch(
                    "opennoise.ml.fma_nonlinear_experiment.load_inputs", return_value=(data, full)
                ),
                patch(
                    "opennoise.ml.fma_nonlinear_experiment.verify_seal",
                    return_value={"protocol": {"interpretation": ["synthetic"]}},
                ),
            ):
                for fold in range(5):
                    for arm in ARMS:
                        fit_stage(seal, output, fold, arm)
                    for arm in ARMS:
                        score_stage(seal, output, fold, arm)
                        verify_stage(output, seal, fold, arm, "score")
                summarize(seal, output)
                report = json.loads((output / "summary/results.json").read_text())
                for arm in ARMS:
                    self.assertEqual(report["arms"][arm]["all"]["totals"]["queries"], 60)
                    self.assertEqual(report["arms"][arm]["all"]["totals"]["positives"], 50)
                self.assertEqual(len(report["comparisons"]), 4)
                model = output / "fold-0/linear44/fit/model.npz"
                model.write_bytes(model.read_bytes() + b"changed")
                with self.assertRaisesRegex(ValueError, "changed"):
                    verify_stage(output, seal, 0, "linear44", "fit")

    def test_overbudget_never_publishes_completed_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            seal = root / "seal.json"
            seal.write_text("{}")
            folder = root / "run/fold-0/linear44/fit"
            folder.mkdir(parents=True)
            (folder / "model.npz").write_bytes(b"synthetic")
            with (
                patch("opennoise.ml.fma_component_balanced.MAX_OUTPUT_BYTES", 1),
                self.assertRaisesRegex(ValueError, "100MB"),
            ):
                _receipt(folder, seal, 0, {"stage": "fit"})
            self.assertFalse((folder / "receipt.json").exists())
            self.assertTrue((folder / "receipt.pending").exists())
