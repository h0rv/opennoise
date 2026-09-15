"""Integration contract for the static semantic-atlas publication path."""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from opennoise.deployment import semantic_pages
from opennoise.deployment.semantic_pages import SemanticPagesExportInputs, export_semantic_pages

LAYOUT = Path(".cache/semantic-map-layout-v1/artifact.json")
STATIC_ROOT = Path(__file__).resolve().parents[2] / "src" / "opennoise" / "static"


@unittest.skipUnless(LAYOUT.is_file(), "semantic-layout integration artifact is not provisioned")
class SemanticPagesExportTests(unittest.TestCase):
    """The release exporter must retain the canonical renderer payload, not the SVG fallback."""

    def test_exports_full_semantic_atlas_and_static_edge_index(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "dist"
            manifest = export_semantic_pages(SemanticPagesExportInputs(LAYOUT, output))
            binding = manifest["semantic_layout"]
            assert isinstance(binding, dict)
            self.assertEqual(binding["total_seed_count"], 6291)
            self.assertEqual(binding["placed_node_count"], 2945)
            self.assertEqual(binding["unplaced_node_count"], 3346)
            self.assertEqual(binding["overview_region_count"], 24)
            self.assertEqual(binding["structural_edge_count"], 34937)
            release_assets = manifest["assets"]
            assert isinstance(release_assets, dict)
            atlas_entry = release_assets["semantic_atlas"]
            assert isinstance(atlas_entry, dict)
            atlas_path = output / str(atlas_entry["path"])
            payload = json.loads(atlas_path.read_text())
            self.assertEqual(len(payload["nodes"]), 2945)
            self.assertEqual(len(payload["edges"]), 34937)
            index = (output / "index.html").read_text()
            self.assertIn('id="semantic-map"', index)
            self.assertFalse((output / "assets" / "production-map-v1.json").exists())
            self.assertFalse((output / "assets" / "app.css").exists())
            self.assertFalse((output / "assets" / "map-atlas.mjs").exists())
            self.assertFalse((output / "assets" / "map-renderer.js").exists())
            self.assertFalse((output / "assets" / "semantic-atlas.json").exists())
            for stale_path in (
                "assets/app.css",
                "assets/map-atlas.mjs",
                "assets/map-renderer.js",
                "assets/semantic-atlas.json",
            ):
                self.assertNotIn(stale_path, index)
            for entry in release_assets.values():
                assert isinstance(entry, dict)
                path = output / str(entry["path"])
                self.assertTrue(path.is_file())
                self.assertEqual(
                    entry["sha256"], semantic_pages.sha256(path.read_bytes()).hexdigest()
                )
            app_entry = release_assets["app_css"]
            renderer_entry = release_assets["map_renderer_module"]
            atlas_module_entry = release_assets["map_atlas_module"]
            assert isinstance(app_entry, dict)
            assert isinstance(renderer_entry, dict)
            assert isinstance(atlas_module_entry, dict)
            self.assertIn(str(app_entry["path"]), index)
            self.assertIn(str(renderer_entry["path"]), index)
            self.assertIn(str(atlas_entry["path"]), index)
            renderer_text = (output / str(renderer_entry["path"])).read_text()
            self.assertIn(Path(str(atlas_module_entry["path"])).name, renderer_text)
            self.assertNotIn("./map-atlas.mjs", renderer_text)

    def test_changed_static_bytes_get_a_new_immutable_url(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            static = root / "static"
            shutil.copytree(STATIC_ROOT, static)
            with patch.object(semantic_pages, "_STATIC_ROOT", static):
                first = export_semantic_pages(SemanticPagesExportInputs(LAYOUT, root / "first"))
                (static / "app.css").write_text("/* changed */\n", encoding="utf-8")
                second = export_semantic_pages(SemanticPagesExportInputs(LAYOUT, root / "second"))
            first_assets = first["assets"]
            second_assets = second["assets"]
            assert isinstance(first_assets, dict)
            assert isinstance(second_assets, dict)
            first_css = first_assets["app_css"]
            second_css = second_assets["app_css"]
            assert isinstance(first_css, dict)
            assert isinstance(second_css, dict)
            self.assertNotEqual(first_css["path"], second_css["path"])


if __name__ == "__main__":
    unittest.main()
