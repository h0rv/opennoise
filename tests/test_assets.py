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

    def test_browser_certification_uses_screen_font_size_and_rejects_runtime_errors(self) -> None:
        source = Path("scripts/capture_production_map_browser.mjs").read_text(encoding="utf-8")
        self.assertIn("Number.parseFloat(n.style('font-size')) * zoom", source)
        self.assertIn("requireNoRuntimeErrors", source)
        self.assertIn("requirePassingInteractions", source)


if __name__ == "__main__":
    unittest.main()
