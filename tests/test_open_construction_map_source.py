import unittest
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / "src" / "musix" / "static" / "semantic-map.js"


class OpenConstructionMapSourceTests(unittest.TestCase):
    def test_open_view_keeps_a_server_bounded_landscape_renderer_contract(self) -> None:
        source = SOURCE.read_text(encoding="utf-8")
        self.assertIn("initOpenConstructionMap", source)
        self.assertIn("/api/open-construction-map?level=${level}", source)
        self.assertIn("Each server LOD response is capped at 720", source)
        self.assertIn("/api/open-construction-map/neighbors/", source)
        self.assertIn('mapElement.dataset.mapMode === "open"', source)


if __name__ == "__main__":
    unittest.main()
