import hashlib
import json
import unittest
from pathlib import Path


class AssetTests(unittest.TestCase):
    def test_vendored_htmx_matches_the_manifest(self) -> None:
        static = Path("src/musix/static")
        manifest = json.loads((static / "assets.json").read_text(encoding="utf-8"))
        asset = (static / manifest["htmx"]["file"]).read_bytes()
        self.assertEqual(manifest["htmx"]["version"], "4.0.0")
        self.assertEqual(len(asset), manifest["htmx"]["bytes"])
        self.assertEqual(hashlib.sha256(asset).hexdigest(), manifest["htmx"]["sha256"])

    def test_semantic_map_starts_with_bounded_overview_and_cached_positions(self) -> None:
        source = Path("src/musix/static/semantic-map.js").read_text(encoding="utf-8")
        self.assertIn("nodePositionCache", source)
        self.assertIn("edgeIndexCache", source)
        self.assertIn("initialElementCount", source)
        self.assertIn("[0, 96, 280, 720][lod]", source)
        node_element = source[
            source.index("const nodeElement") : source.index("const materializeLod")
        ]
        self.assertNotIn("mapPositions(getNodes(payload)", node_element)
        self.assertIn("materializeSelectedEdges", source)

    def test_semantic_map_uses_a_wide_world_with_bounded_detail_and_readable_overview(self) -> None:
        source = Path("src/musix/static/semantic-map.js").read_text(encoding="utf-8")
        self.assertIn("Math.max(1.6, Math.min(2.4, viewportWidth / viewportHeight))", source)
        self.assertIn("cy.fit(overview, overviewFitPadding());", source)
        self.assertNotIn("cy.zoom(1);\n    cy.pan({ x: 0, y: 0 });", source)
        self.assertIn("screenLabelSize / cameraScale", source)
        self.assertIn('overviewFontSize(Number(node.data("weight"))) / cameraScale', source)
        self.assertIn("nodeBudget: 720", source)
        self.assertIn("[0, 96, 280, 720][lod]", source)
        self.assertIn("shownLabelCount = accepted", source)
        self.assertIn("overlays.some((overlay) => intersects(bounds", source)
        self.assertIn("[16, mapElement.clientWidth <= 600 ? 18 : 14, 13, 13][lod]", source)

    def test_historical_renderer_uses_bounded_hierarchy_drills_not_global_tiles(self) -> None:
        source = Path("src/musix/static/semantic-map.js").read_text(encoding="utf-8")
        self.assertIn('mapElement.dataset.mapMode === "historical"', source)
        self.assertIn("payload.initial_edge_count !== 0", source)
        self.assertIn("const overview = payload.hierarchy ?? payload.nodes ?? [];", source)
        self.assertIn("overview.length > 24", source)
        self.assertIn("parent_id=${encodeURIComponent(hierarchyId)}", source)
        self.assertIn("const drill = (source, url, depth, property) =>", source)
        self.assertIn(
            "`/api/historical-signal-map?level=${nextLevel}&parent_id=${encodeURIComponent(hierarchyId)}`",
            source,
        )
        self.assertIn(
            "`/api/historical-signal-map?level=3&parent_id=${encodeURIComponent(hierarchyId)}`",
            source,
        )
        self.assertNotIn("&column=${column}&row=${row}", source)
        self.assertIn("/api/historical-signal-map/neighbors/${encodeURIComponent", source)
        self.assertIn("/api/historical-signal-map/members/${encodeURIComponent", source)
        self.assertNotIn("scheduleTiles", source)
        self.assertNotIn("loadedTiles", source)
        self.assertIn("memberRequest?.abort();", source)

    def test_semantic_map_script_url_is_versioned_for_deploy_cache_busting(self) -> None:
        template = Path("src/musix/templates/index.html").read_text(encoding="utf-8")
        self.assertIn('src="/static/semantic-map.js?v=20"', template)

    def test_stylesheet_url_is_versioned_for_deploy_cache_busting(self) -> None:
        template = Path("src/musix/templates/index.html").read_text(encoding="utf-8")
        self.assertIn('href="/static/app.css?v=14"', template)

    def test_mobile_small_community_drill_uses_a_deterministic_label_layout(self) -> None:
        source = Path("src/musix/static/semantic-map.js").read_text(encoding="utf-8")
        self.assertIn("members.length <= 12", source)
        self.assertIn("focusedPositionRestore", source)
        self.assertIn("horizontalSpacing = 360", source)

    def test_historical_overview_labels_are_present_in_initial_elements(self) -> None:
        source = Path("src/musix/static/semantic-map.js").read_text(encoding="utf-8")
        self.assertIn('const element = (node, position = null, displayLabel = "")', source)
        self.assertIn("}, item.representative_label ?? item.name);", source)

    def test_historical_renderer_reveals_and_measures_its_container_before_drawing(self) -> None:
        source = Path("src/musix/static/semantic-map.js").read_text(encoding="utf-8")
        reveal = source.index('root.classList.add("js-map-ready")')
        renderer = source.index("cy = window.cytoscape")
        self.assertLess(reveal, renderer)
        self.assertIn("cy.resize();\n        fitHistoricalViewport();", source)
        self.assertIn("window.requestAnimationFrame(() => {\n          cy.resize();", source)

    def test_browser_certification_uses_screen_font_size_and_rejects_runtime_errors(self) -> None:
        source = Path("scripts/capture_production_map_browser.mjs").read_text(encoding="utf-8")
        self.assertIn("Number.parseFloat(n.style('font-size')) * zoom", source)
        self.assertIn("requireNoRuntimeErrors", source)
        self.assertIn("requirePassingInteractions", source)
        self.assertIn("internal_world_aspect", source)
        self.assertIn("element_bounds_ok", source)
        self.assertIn("requireOverviewContract", source)


if __name__ == "__main__":
    unittest.main()
