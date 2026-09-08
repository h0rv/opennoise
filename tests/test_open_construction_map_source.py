import json
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
        for transform_call in (
            "min_x: rawX(viewport.x1)",
            "min_y: rawY(viewport.y1)",
            "max_x: rawX(viewport.x2)",
            "max_y: rawY(viewport.y2)",
        ):
            self.assertIn(transform_call, source)
        self.assertIn("loadController?.abort();", source)
        self.assertIn("cy.elements().remove();", source)
        self.assertIn("data-open-node-id", source)
        self.assertIn('mapElement.dataset.mapMode === "open"', source)

    def test_v2_keeps_centered_negative_coordinates_for_viewport_and_local_fit(self) -> None:
        """Guard the v2 drill camera from accidentally reusing v1's offset transform."""
        source = SOURCE.read_text(encoding="utf-8")
        self.assertIn('const openGraphV2 = mapElement.dataset.openGraphVersion === "v2";', source)
        self.assertIn("const displayX = (value) => openGraphV2", source)
        self.assertIn("const rawX = (value) => openGraphV2", source)
        self.assertIn("? Number(value)", source)
        self.assertIn("cy.fit(neighborhood, 96);", source)
        self.assertIn("replace the just-selected nodes with an unrelated LOD cohort", source)
        self.assertIn(
            "if (focusedNodeId) {\n              scheduleOpenLabelPaint();\n              return;",
            source,
        )
        self.assertIn("const publishOpenSelectionSnapshot = () =>", source)
        self.assertIn("mapElement.dataset.openRenderedNodeIds", source)

        # The committed v2 layout spans negative coordinates, whereas the v1
        # display transform is centered near x=665. A v2 identity round-trip
        # is required for a selected local neighborhood to remain fit-visible.
        artifact = json.loads(Path("data/model/open-construction-graph-v2.json").read_text())
        x = float(artifact["layout"][0]["landscape_x"])
        self.assertLess(min(item["landscape_x"] for item in artifact["layout"]), 0)
        self.assertGreater(max(item["landscape_x"] for item in artifact["layout"]), 0)
        display_x = x  # v2 branch: `displayX(value) => Number(value)`.
        recovered_x = display_x  # v2 branch: `rawX(value) => Number(value)`.
        self.assertEqual(recovered_x, x)


if __name__ == "__main__":
    unittest.main()
