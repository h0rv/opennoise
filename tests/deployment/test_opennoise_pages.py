"""Boundary tests for staging the approved semantic map for static Pages."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from musix.deployment.opennoise_pages import (
    OpenNoisePagesExportError,
    OpenNoisePagesExportInputs,
    export_opennoise_pages,
)
from musix.ml.production_map import build_production_map
from musix.ml.public_graph import build_public_model
from musix.models.modeling import PublicModelSettings
from tests.serving.map.test_production_map import _inputs, _settings


class OpenNoisePagesTests(unittest.TestCase):
    """Keep the static staging boundary independent from application templates."""

    def test_stages_only_a_verified_export_allowed_production_map_deterministically(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = build_public_model(_inputs(), PublicModelSettings())
            artifact = build_production_map(_inputs(), source, _settings())
            source_path = root / "production-map-v1.json"
            source_path.write_text(artifact.model_dump_json(), encoding="utf-8")

            first = export_opennoise_pages(OpenNoisePagesExportInputs(source_path, root / "first"))
            second = export_opennoise_pages(
                OpenNoisePagesExportInputs(source_path, root / "second")
            )

            self.assertEqual(first, second)
            self.assertFalse(first.explicit_backend_api_available)
            self.assertEqual(first.artifact.logical_sha256, artifact.output_sha256)
            self.assertEqual(first.artifact.mapped_node_count, len(artifact.nodes))
            self.assertEqual(
                (root / "first" / "assets" / "production-map-v1.json").read_bytes(),
                source_path.read_bytes(),
            )
            self.assertTrue((root / "first" / "opennoise-static-staging-manifest.json").is_file())
            self.assertFalse((root / "first" / "index.html").exists())

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
                    OpenNoisePagesExportInputs(root / "not-read.json", destination)
                )

    def test_rejects_a_verified_but_nonexportable_production_map(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = build_public_model(_inputs(), PublicModelSettings())
            artifact = build_production_map(_inputs(), source, _settings()).model_copy(
                update={"export_allowed": False}
            )
            source_path = root / "not-exportable.json"
            source_path.write_text(artifact.model_dump_json(), encoding="utf-8")

            with self.assertRaisesRegex(OpenNoisePagesExportError, "not export allowed"):
                export_opennoise_pages(OpenNoisePagesExportInputs(source_path, root / "output"))


if __name__ == "__main__":
    unittest.main()
