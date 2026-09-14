"""Integration contract for the static semantic-atlas publication path."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from opennoise.deployment.semantic_pages import SemanticPagesExportInputs, export_semantic_pages

LAYOUT = Path(".cache/semantic-map-layout-v1/artifact.json")


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
            payload = json.loads((output / "assets" / "semantic-atlas.json").read_text())
            self.assertEqual(len(payload["nodes"]), 2945)
            self.assertEqual(len(payload["edges"]), 34937)
            self.assertIn('id="semantic-map"', (output / "index.html").read_text())
            self.assertFalse((output / "assets" / "production-map-v1.json").exists())


if __name__ == "__main__":
    unittest.main()
