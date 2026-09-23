"""Safety tests for the fixed-fold local sparse cosine writer."""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path


class SparseGenreCosineRobustnessWriterTests(unittest.TestCase):
    def test_refuses_an_output_outside_the_local_cache(self) -> None:
        root = Path(__file__).parents[2]
        output = root / "dist" / "forbidden-sparse-robustness.json"
        result = subprocess.run(  # noqa: S603 - fixed interpreter and test-controlled arguments.
            [
                sys.executable,
                "scripts/evaluate_sparse_genre_cosine_robustness.py",
                "--direct-database",
                "ignored.sqlite",
                "--direct-receipt",
                "ignored.json",
                "--colisten-database",
                "ignored.sqlite",
                "--colisten-receipt",
                "ignored.json",
                "--output",
                str(output),
            ],
            check=False,
            cwd=root,
            capture_output=True,
            text=True,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("below .cache", result.stderr)
        self.assertFalse(output.exists())
