import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class UiQaTests(unittest.TestCase):
    def test_one_canvas_renderer_replaces_the_retired_svg_fixture(self) -> None:
        renderer = (ROOT / "src/opennoise/static/map-renderer.js").read_text(encoding="utf-8")
        self.assertIn("requestAnimationFrame", renderer)
        self.assertIn("getContext('2d')", renderer)
        self.assertNotIn("cytoscape", renderer.casefold())


if __name__ == "__main__":
    unittest.main()
