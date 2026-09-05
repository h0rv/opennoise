import unittest
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / "src" / "musix" / "static" / "semantic-map.js"


class OpenConstructionMapSourceTests(unittest.TestCase):
    def test_open_view_keeps_a_server_bounded_landscape_renderer_contract(self) -> None:
        source = SOURCE.read_text(encoding="utf-8")
        self.assertIn("initOpenConstructionMap", source)
        self.assertIn("node.node_id ?? node.genre_id", source)
        self.assertIn("data-neighbor-url", Path("src/musix/templates/map.html").read_text())
        self.assertIn("graphEndpoint", source)
        self.assertIn("neighborEndpoint", source)
        self.assertIn("min_x: viewport.x1", source)
        self.assertIn("loadController?.abort();", source)
        self.assertIn("cy.elements().remove();", source)
        self.assertIn("data-open-node-id", source)
        self.assertIn('mapElement.dataset.mapMode === "open"', source)


if __name__ == "__main__":
    unittest.main()
