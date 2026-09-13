"""Contract tests for the independent semantic-map browser harness."""

from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "scripts/capture_semantic_map_browser.mjs"


class SemanticMapBrowserQaTests(unittest.TestCase):
    """Keep the browser evidence checks focused on the product contract."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.source = HARNESS.read_text(encoding="utf-8")

    def test_harness_uses_cdp_and_fixed_desktop_viewport(self) -> None:
        self.assertIn('"Page.captureScreenshot"', self.source)
        self.assertIn('"Input.dispatchMouseEvent"', self.source)
        self.assertIn("width: 1440, height: 900", self.source)
        self.assertIn("prefers-color-scheme", self.source)

    def test_overview_budget_and_occupancy_gates_are_explicit(self) -> None:
        self.assertRegex(self.source, re.compile(r"initial\.points >= 1 && initial\.points <= 50"))
        self.assertRegex(self.source, re.compile(r"initial\.labels >= 1 && initial\.labels <= 35"))
        self.assertIn("initial.edges === 0", self.source)
        self.assertIn("widthFraction >= 0.75", self.source)
        self.assertIn("heightFraction >= 0.70", self.source)

    def test_harness_checks_zoom_pan_focus_back_and_theme(self) -> None:
        self.assertIn("zoom reveal is not monotonic", self.source)
        self.assertIn("pan did not move camera", self.source)
        self.assertIn("focused.edges <= 12", self.source)
        self.assertIn("Back did not restore map state", self.source)
        self.assertIn("dark mode did not change the map palette", self.source)

    def test_preload_observes_canvas_without_production_debug_code(self) -> None:
        self.assertIn("Page.addScriptToEvaluateOnNewDocument", self.source)
        self.assertIn("CanvasRenderingContext2D.prototype.arc", self.source)
        self.assertIn("CanvasRenderingContext2D.prototype.fillText", self.source)
        self.assertIn("CanvasRenderingContext2D.prototype.lineTo", self.source)
        self.assertNotIn("src/opennoise/", self.source)


if __name__ == "__main__":
    unittest.main()
