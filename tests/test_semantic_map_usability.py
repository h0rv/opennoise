import os
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")
CHROMIUM = shutil.which("chromium") or "/usr/bin/chromium"
RUN_BROWSER_TESTS = os.environ.get("MUSIX_RUN_BROWSER_TESTS") == "1"


@unittest.skipUnless(
    RUN_BROWSER_TESTS and NODE and Path(CHROMIUM).exists(),
    "set MUSIX_RUN_BROWSER_TESTS=1 with Chromium and Node installed",
)
class SemanticMapUsabilityBrowserTests(unittest.TestCase):
    def test_semantic_map_usability_contract(self) -> None:
        result = subprocess.run(  # noqa: S603
            [str(NODE), "scripts/validate_semantic_map_usability.mjs"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertIn('"contract":"semantic-map-usability-v1"', result.stdout)
        self.assertIn('"labels":13', result.stdout)
        self.assertIn('"readable":true', result.stdout)
