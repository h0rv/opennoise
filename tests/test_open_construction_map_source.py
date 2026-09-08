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

    def test_v2_keeps_reversible_display_coordinates_for_viewport_and_local_fit(self) -> None:
        """The responsive overview transform must not change source-coordinate queries."""
        source = SOURCE.read_text(encoding="utf-8")
        self.assertIn('const openGraphV2 = mapElement.dataset.openGraphVersion === "v2";', source)
        self.assertIn("openDisplayTransform?.x.forward(Number(value))", source)
        self.assertIn("openDisplayTransform?.x.inverse(Number(value))", source)
        self.assertIn("const monotonicAxisTransform = (items, key, positions) =>", source)
        self.assertIn("cy.fit(neighborhood, 96);", source)
        self.assertIn("replace the just-selected nodes with an unrelated LOD cohort", source)
        self.assertIn(
            "if (focusedNodeId) {\n              scheduleOpenLabelPaint();\n              return;",
            source,
        )
        self.assertIn("const publishOpenSelectionSnapshot = () =>", source)
        self.assertIn("mapElement.dataset.openRenderedNodeIds", source)

        # The committed v2 layout spans negative coordinates. Its display
        # transform must be reversible so deeper viewport requests and a local
        # neighborhood still address those immutable source coordinates.
        artifact = json.loads(Path("data/model/open-construction-graph-v2.json").read_text())
        x = float(artifact["layout"][0]["landscape_x"])
        self.assertLess(min(item["landscape_x"] for item in artifact["layout"]), 0)
        self.assertGreater(max(item["landscape_x"] for item in artifact["layout"]), 0)
        self.assertTrue(x < 0 or x > 0)

    def test_v2_overview_packs_only_the_display_cohort_before_deeper_lods(self) -> None:
        """Keep a far overview outlier from shrinking the initial visible map."""
        source = SOURCE.read_text(encoding="utf-8")
        self.assertIn("const overviewDisplayPositions = (payload) =>", source)
        self.assertIn("mapPositions(payload.nodes, nodeId, dimensions)", source)
        self.assertIn("{ width: 1500, height: 2000, aspect: 0.75 }", source)
        self.assertIn("const maximumLabelSize = mapElement.clientWidth <= 600 ? 192 : 64;", source)
        self.assertIn("if (level > 0 && cy)", source)
        self.assertIn("render(payload, preserveCamera);", source)
        self.assertIn("if (!focusedNodeId && activeLevel === 0) {", source)
        self.assertIn("let pendingOverviewResizeCamera = null;", source)
        self.assertIn("rawX: rawX(center.x)", source)
        self.assertIn("relativeZoom: cy.zoom() / Math.max(baselineZoom, 0.0001)", source)


if __name__ == "__main__":
    unittest.main()
