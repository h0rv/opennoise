"""Tests for the portable foundation inventory."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

from opennoise.pipeline.foundation import inspect, validate_manifest
from scripts.foundation_manifest import main


class FoundationManifestTests(unittest.TestCase):
    def test_hashes_files_and_reports_missing_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "present.json").write_text("{}", encoding="utf-8")
            manifest: dict[str, object] = {
                "version": 1,
                "scope": "test",
                "inputs": [
                    {"id": "file", "path": "present.json", "required": True, "license": "CC0-1.0"},
                    {"id": "missing", "path": "absent", "required": True, "license": "CC0-1.0"},
                ],
                "stages": [
                    {
                        "id": "build",
                        "needs": ["file", "missing"],
                        "command": "run",
                        "purpose": "test",
                    }
                ],
            }
            report = cast("dict[str, Any]", inspect(root, manifest))
            self.assertTrue(report["inputs"][0]["sha256"])
            self.assertIsNone(report["inputs"][1]["sha256"])
            self.assertEqual(report["stages"][0]["missing_inputs"], ["missing"])
            self.assertEqual(len(report["stages"][0]["stage_sha256"]), 64)

    def test_rejects_unknown_fields_and_symlinks(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            outside = root.parent / "outside-foundation-input"
            outside.write_text("secret", encoding="utf-8")
            try:
                (root / "alias").symlink_to(outside)
                manifest: dict[str, object] = {
                    "version": 1,
                    "scope": "test",
                    "inputs": [
                        {"id": "alias", "path": "alias", "required": True, "license": "CC0"}
                    ],
                    "stages": [],
                }
                validate_manifest(manifest)
                with self.assertRaises(ValueError):
                    inspect(root, manifest)
                with self.assertRaises(ValueError):
                    validate_manifest({**manifest, "unexpected": True})
            finally:
                outside.unlink(missing_ok=True)

    def test_directory_cannot_substitute_for_input_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "input.json").mkdir()
            manifest: dict[str, object] = {
                "version": 1,
                "scope": "test",
                "inputs": [
                    {"id": "file", "path": "input.json", "required": True, "license": "CC0"}
                ],
                "stages": [{"id": "demo", "needs": ["file"], "command": "run", "purpose": "test"}],
            }
            report = cast("dict[str, Any]", inspect(root, manifest))
            self.assertFalse(report["inputs"][0]["exists"])
            self.assertEqual(report["stages"][0]["missing_inputs"], ["file"])

    def test_stage_validation_does_not_require_other_stage_inputs(self) -> None:
        with (
            tempfile.TemporaryDirectory() as temporary,
            patch("sys.stdout"),
            patch("sys.stderr"),
        ):
            root = Path(temporary)
            with patch(
                "sys.argv", ["foundation", "validate", "--root", str(root), "--stage", "checkout"]
            ):
                self.assertEqual(main(), 0)
            with patch("sys.argv", ["foundation", "validate", "--root", str(root)]):
                self.assertEqual(main(), 1)
            with patch(
                "sys.argv", ["foundation", "validate", "--root", str(root), "--stage", "missing"]
            ):
                self.assertEqual(main(), 2)


if __name__ == "__main__":
    unittest.main()
