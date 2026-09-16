"""Contract tests for the independent semantic-map browser harness."""

from __future__ import annotations

import re
import unittest
from pathlib import Path
from typing import override

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "scripts/capture_semantic_map_browser.mjs"


class SemanticMapBrowserQaTests(unittest.TestCase):
    """Keep the browser evidence checks focused on the product contract."""

    @classmethod
    @override
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
        self.assertIn("zoom reveal is unavailable", self.source)
        self.assertIn("pan did not move camera", self.source)
        self.assertIn("focused.edges <= 12", self.source)
        self.assertIn("Back did not restore map state", self.source)
        self.assertIn("dark mode did not change the map palette", self.source)
        self.assertIn("post-punk did not focus its connection set", self.source)
        self.assertIn("modern_rock_connection_contract", self.source)
        self.assertIn("rock_landmark_retained_after_plus", self.source)
        self.assertIn("modernRock.points === modernRock.edges + 1", self.source)
        self.assertIn("focused view leaked unconnected dots", self.source)
        self.assertIn("IDM list does not match its shown links", self.source)
        self.assertIn("mobile pinch did not zoom the map", self.source)
        self.assertIn("L3 imposed a camera zoom wall", self.source)
        self.assertIn(
            "one-pixel pan changed retained label identity or world-anchor offset", self.source
        )
        self.assertIn("equivalent zoom paths changed label admission or placement", self.source)
        self.assertIn("deep reveal labels overlap", self.source)
        self.assertIn("mobile pinch labels are unreadable", self.source)
        self.assertIn("desktop-one-pixel-pan.png", self.source)
        self.assertIn("desktop-zoom-path-equivalent.png", self.source)
        self.assertIn(
            "fixed-center zoom path lost labels without a matching visible-point exit", self.source
        )
        self.assertIn("desktop-rock-fixed-center-trajectory.png", self.source)
        self.assertIn(
            "deepest certified static label is not readable at the camera cap", self.source
        )
        self.assertIn("desktop-deepest-static-label.png", self.source)

    def test_renderer_keeps_focus_static_and_cleans_pointer_capture(self) -> None:
        renderer = (ROOT / "src/opennoise/static/map-renderer.js").read_text(encoding="utf-8")
        self.assertIn("structuralNeighborhood(state.atlas, id)", renderer)
        self.assertNotIn("dataset.neighborsUrl", renderer)
        self.assertNotIn("neighborUrl", renderer)
        self.assertIn("Structural connections", renderer)
        self.assertIn("pointercancel", renderer)
        self.assertIn("lostpointercapture", renderer)
        self.assertIn("state.displayedIds", renderer)

    def test_prefixed_focus_bookmarks_are_normalized_to_public_ids(self) -> None:
        renderer = (ROOT / "src/opennoise/static/map-renderer.js").read_text(encoding="utf-8")
        self.assertIn("canonicalizeFocusUrl", renderer)
        self.assertIn("history.replaceState", renderer)
        self.assertIn("lastIndexOf(':')", renderer)
        self.assertIn("open_focus=archive%3Aitem887", self.source)
        self.assertIn("normalizedPrefixed.focus_url === 'item887'", self.source)

    def test_preload_observes_canvas_without_production_debug_code(self) -> None:
        self.assertIn("Page.addScriptToEvaluateOnNewDocument", self.source)
        self.assertIn("CanvasRenderingContext2D.prototype.arc", self.source)
        self.assertIn("class QAPath2D", self.source)
        self.assertIn("connected_path_arcs", self.source)
        self.assertIn("label_boxes", self.source)
        self.assertIn("edge_endpoints", self.source)
        self.assertIn("mobile-light.png", self.source)
        self.assertIn("CanvasRenderingContext2D.prototype.fillText", self.source)
        self.assertIn("CanvasRenderingContext2D.prototype.lineTo", self.source)
        self.assertIn("Input.dispatchTouchEvent", self.source)
        self.assertNotIn("src/opennoise/", self.source)


if __name__ == "__main__":
    unittest.main()
