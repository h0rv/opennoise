"""Tests for the fully static, source-neutral OpenNoise Pages export."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import TYPE_CHECKING

from opennoise.deployment.opennoise_pages import (
    OpenNoisePagesExportError,
    OpenNoisePagesExportInputs,
    export_opennoise_pages,
)
from opennoise.ml.production_map import build_production_map
from opennoise.ml.public_graph import build_public_model
from opennoise.models.modeling import PublicModelSettings
from opennoise.serving.open.construction_graph_v2 import (
    OpenConstructionGraphV2Config,
    build_open_construction_graph_v2,
    write_open_construction_graph_v2,
)
from tests.serving.map.test_production_map import _inputs, _settings
from tests.serving.open.test_construction_graph_v2 import build_expansion

if TYPE_CHECKING:
    from opennoise.models.production import ProductionMapArtifact


class OpenNoisePagesTests(unittest.TestCase):
    """The mapped SVG and searchable vocabulary have distinct contracts."""

    def test_exports_deterministic_static_map_and_full_vocabulary_search(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            production_path, search_path, production = self._inputs(root)

            first = export_opennoise_pages(
                OpenNoisePagesExportInputs(production_path, search_path, root / "first")
            )
            second = export_opennoise_pages(
                OpenNoisePagesExportInputs(production_path, search_path, root / "second")
            )

            self.assertEqual(first, second)
            self.assertFalse(first.explicit_backend_api_available)
            self.assertEqual(first.artifact.logical_sha256, production.output_sha256)
            self.assertEqual(first.artifact.mapped_node_count, len(production.nodes))
            self.assertEqual(first.search.searchable_name_count, 5)
            self.assertEqual(
                first.search.direct_mapped_search_name_count
                + first.search.searchable_only_name_count,
                first.search.searchable_name_count,
            )
            self.assertTrue((root / "first" / "index.html").is_file())
            self.assertTrue((root / "first" / "opennoise-static-manifest.json").is_file())
            self.assertFalse((root / "first" / "assets" / "production-map-v1.json").exists())

            index = (root / "first" / "index.html").read_text(encoding="utf-8")
            self.assertIn('data-mapped-node-count="8"', index)
            self.assertIn('data-searchable-name-count="5"', index)
            self.assertIn('preserveAspectRatio="xMidYMid meet"', index)
            self.assertIn('data-map-url="assets/map-data.json"', index)
            self.assertIn('src="assets/map.js"', index)
            self.assertNotIn("cytoscape", index.casefold())
            self.assertNotIn("semantic-map", index)
            self.assertNotIn("<h1", index)
            self.assertFalse((root / "first" / "levels").exists())

            map_data = json.loads((root / "first" / "assets" / "map-data.json").read_text())
            self.assertEqual(map_data["revision"], "opennoise-map-v1")
            self.assertEqual(len(map_data["nodes"]), 5)
            self.assertEqual(set(map_data["lod"]), {"0", "1", "2", "3"})
            self.assertTrue(
                all(0 <= node["x"] <= 1 and 0 <= node["y"] <= 1 for node in map_data["nodes"])
            )
            self.assertLessEqual(len(map_data["lod"]["0"]), len(map_data["nodes"]))

            search_entries = json.loads(
                (root / "first" / "assets" / "search-index.json").read_text(encoding="utf-8")
            )
            self.assertEqual(len(search_entries), 5)
            self.assertEqual(
                sum(item["status"] == "mapped" for item in search_entries),
                first.search.direct_mapped_search_name_count,
            )
            self.assertTrue(
                all(
                    "href" not in item
                    for item in search_entries
                    if item["status"] == "searchable_only"
                )
            )

    def test_rejects_any_historical_construction_channel_in_search_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            production_path, search_path, _ = self._inputs(root)
            payload = json.loads(search_path.read_text(encoding="utf-8"))
            payload["input_audit"]["historical_memberships_read"] = True
            search_path.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaisesRegex(OpenNoisePagesExportError, "full-vocabulary search"):
                export_opennoise_pages(
                    OpenNoisePagesExportInputs(production_path, search_path, root / "output")
                )
            self.assertFalse((root / "output").exists())

    def test_fails_closed_for_a_nonempty_output_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            destination = root / "staging"
            destination.mkdir()
            (destination / "existing.txt").write_text("keep", encoding="utf-8")

            with self.assertRaisesRegex(
                OpenNoisePagesExportError, "output directory must be empty"
            ):
                export_opennoise_pages(
                    OpenNoisePagesExportInputs(
                        root / "not-read.json", root / "not-read-v2.json", destination
                    )
                )

    def test_rejects_a_verified_but_nonexportable_production_map(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            production_path, search_path, production = self._inputs(root)
            production_path.write_text(
                production.model_copy(update={"export_allowed": False}).model_dump_json(),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(OpenNoisePagesExportError, "not export allowed"):
                export_opennoise_pages(
                    OpenNoisePagesExportInputs(production_path, search_path, root / "output")
                )

    @staticmethod
    def _inputs(root: Path) -> tuple[Path, Path, ProductionMapArtifact]:
        source = build_public_model(_inputs(), PublicModelSettings())
        production = build_production_map(_inputs(), source, _settings())
        production_path = root / "production-map-v1.json"
        production_path.write_text(production.model_dump_json(), encoding="utf-8")
        search = build_open_construction_graph_v2(
            build_expansion(root / "expansion"),
            config=OpenConstructionGraphV2Config(expected_legacy_seed_count=5),
        )
        search_path = root / "open-construction-v2.json"
        write_open_construction_graph_v2(search, search_path)
        return production_path, search_path, production


if __name__ == "__main__":
    unittest.main()
