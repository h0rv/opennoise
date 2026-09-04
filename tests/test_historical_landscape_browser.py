import os
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")
RUN_BROWSER_TESTS = os.environ.get("MUSIX_RUN_BROWSER_TESTS") == "1"


@unittest.skipUnless(
    RUN_BROWSER_TESTS and shutil.which("chromium") and NODE,
    "set MUSIX_RUN_BROWSER_TESTS=1 with Chromium and Node installed",
)
class HistoricalLandscapeBrowserTests(unittest.TestCase):
    def test_hierarchy_drill_back_and_camera_are_semantically_separate(self) -> None:
        result = subprocess.run(  # noqa: S603
            [str(NODE), "scripts/test_historical_landscape_browser.mjs"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
            timeout=45,
        )
        self.assertIn('"Leaf A"', result.stdout)
        self.assertIn('"noJs":true', result.stdout)
