"""Synthetic checks of component weighting and input failure behavior."""

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
import zstandard

from opennoise.ml import fma_component_diagnostics as diagnostic


class ComponentDiagnosticsTests(unittest.TestCase):
    """Keep paired sampling and roster failures distinct from track-level averaging."""

    def test_ratio_and_paired_resampling(self) -> None:
        """Unequal component mass must use resampled sums, preserving paired arms."""
        values = np.array([[1, 1, 1, 1, 1, 1, 1], [9, 9, 9, 0, 0, 0, 0]], dtype=float)
        report = diagnostic.summarize_components([1, 2], values, {})
        self.assertAlmostEqual(report["metrics"]["acoustic_recall10"]["point"], 0.1)
        self.assertAlmostEqual(report["component_equal"]["acoustic_recall10"]["mean"], 0.5)
        self.assertEqual(
            report["metrics"]["paired_recall10_difference"]["component_bootstrap_percentile95"],
            [0.0, 0.0],
        )
        self.assertEqual(
            report["metrics"]["acoustic_recall10"]["component_bootstrap_percentile95"], [0.0, 1.0]
        )
        self.assertEqual(report["leave_one_component_out"]["paired_mrr_difference"]["min"], 0.0)
        self.assertAlmostEqual(
            diagnostic.concentration(np.array([1.0, 9.0]))[
                "inverse_herfindahl_effective_components"
            ],
            100 / 82,
        )

    def test_no_labeled_denominator_rejected(self) -> None:
        """Undefined deletion statistics must fail instead of emitting NaN."""
        with self.assertRaisesRegex(ValueError, "two labeled"):
            diagnostic.summarize_components([1, 2], np.zeros((2, 7)), {})

    def test_hash_tamper_rejected(self) -> None:
        """A changed pinned input cannot enter an otherwise valid analysis."""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "input"
            path.write_bytes(b"original")
            spec = {
                "inputs": {
                    str(path): {"bytes": 8, "sha256": hashlib.sha256(b"original").hexdigest()}
                }
            }
            diagnostic._verify(spec)  # noqa: SLF001
            path.write_bytes(b"modified")
            with self.assertRaises(ValueError):
                diagnostic._verify(spec)  # noqa: SLF001

    def test_wrong_roster_rejected(self) -> None:
        """Missing known heldout query cannot silently shrink denominators."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "test-acoustic-ranks.jsonl.zst").write_bytes(
                zstandard.ZstdCompressor().compress(b"")
            )
            ledger = {1: {"fold": 2, "artist_known": True, "component_id": 1}}
            with self.assertRaises(ValueError):
                diagnostic._aggregate(root, "test", 2, ledger, {1: {1}}, [1])  # noqa: SLF001

    def test_changed_frozen_analysis_rejected(self) -> None:
        """A different declaration cannot claim a silently ignored bootstrap seed."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            declaration = root / "declaration.json"
            declaration.write_text(
                json.dumps(
                    {
                        "revision": "fma-fixed-rank-component-diagnostics-v1",
                        "limits": {
                            "wall_seconds": 120,
                            "address_space_bytes": 1000000000,
                            "new_output_bytes": 10000000,
                        },
                        "prespecified_analysis": {"seed": 99},
                    }
                )
            )
            with self.assertRaisesRegex(ValueError, "Unsupported prespecified"):
                diagnostic.run(declaration, root, root, root / "out")
