"""Guard the single static delivery surface."""

from __future__ import annotations

import tomllib
import unittest
from pathlib import Path
from runpy import run_path

from opennoise.ml.semantic_layout.contracts import semantic_layout_settings_sha256

ROOT = Path(__file__).resolve().parents[1]


class StaticDeliveryContractTests(unittest.TestCase):
    """The product may export and serve files, but never construct an app backend."""

    def test_poe_exposes_one_static_export_and_a_file_server(self) -> None:
        project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        poe = project["tool"]["poe"]
        tasks = project["tool"]["poe"]["tasks"]
        self.assertEqual(poe["executor"], {"type": "simple"})
        self.assertEqual(set(tasks), {"sync", "bootstrap", "check", "dev", "build", "deploy"})
        self.assertEqual(
            tasks["sync"], {"cmd": "uv sync --locked", "env": {"UV_CACHE_DIR": ".cache/uv"}}
        )
        self.assertEqual(tasks["dev"], ".venv/bin/python scripts/run_dev.py")
        self.assertEqual(tasks["build"], ".venv/bin/python scripts/certify_static_pages.py")
        self.assertEqual(
            tasks["check"]["env"], {"TMPDIR": ".cache/test-tmp", "UV_CACHE_DIR": ".cache/uv"}
        )
        self.assertIn("set -e", tasks["check"]["shell"])
        self.assertIn("set -e", tasks["deploy"]["shell"])
        self.assertIn(
            ".venv/bin/python scripts/certify_static_pages.py --sealed-deploy",
            tasks["deploy"]["shell"],
        )
        self.assertIn(
            "wrangler pages deploy dist --project-name opennoise --branch main",
            tasks["deploy"]["shell"],
        )
        self.assertEqual(
            tasks["deploy"]["env"], {"WRANGLER_LOG_PATH": ".cache/wrangler-deploy.log"}
        )
        for removed in (
            "dev-research",
            "dev-legacy",
            "export-opennoise-pages",
            "ui-qa",
            "open-v2-qa",
        ):
            self.assertNotIn(removed, tasks)

    def test_dev_script_is_a_static_loopback_server(self) -> None:
        source = (ROOT / "scripts" / "run_dev.py").read_text(encoding="utf-8")
        self.assertIn("SimpleHTTPRequestHandler", source)
        self.assertIn("ThreadingHTTPServer", source)
        self.assertIn('raw_arguments[:1] == ["--"]', source)
        self.assertNotIn("opennoise.serving", source)

    def test_static_certification_documents_the_loopback_gate(self) -> None:
        documentation = (ROOT / "docs/serving/OPENNOISE_PAGES_STATIC_STAGING.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("poe build", documentation)
        self.assertIn("poe dev -- --port 3010", documentation)

    def test_selected_v3_layout_settings_have_the_certified_digest(self) -> None:
        namespace = run_path(str(ROOT / "scripts" / "rebuild_semantic_map_layout.py"))
        settings = namespace["_SETTINGS"]
        output = namespace["_OUTPUT"]
        self.assertEqual(output, Path(".cache/semantic-map-layout-v3/artifact.json"))
        self.assertEqual(settings.minimum_coordinate_separation, 0.00032)
        self.assertEqual(settings.maximum_separation_iterations, 128)
        self.assertEqual(
            semantic_layout_settings_sha256(settings),
            "17bcc83100219b10fbb41adb08847eaa1ed3dafbaa396738e2daae9e760a76a9",
        )

    def test_static_certification_requires_conditional_strict_label_exit_gate(self) -> None:
        source = (ROOT / "scripts" / "certify_static_pages.py").read_text(encoding="utf-8")
        self.assertIn('"--require-label-point-exit"', source)
        self.assertIn(".cache/semantic-map-layout-v3/artifact.json", source)

    def test_runtime_framework_dependencies_are_absent(self) -> None:
        project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        dependencies = {
            dependency.split("=", 1)[0].split(">", 1)[0]
            for dependency in project["project"]["dependencies"]
        }
        self.assertLessEqual(
            dependencies,
            {"httpx", "ijson", "pydantic", "pydantic-settings", "scipy", "zstandard"},
        )

    def test_retired_static_svg_surface_is_absent(self) -> None:
        stylesheet = (ROOT / "src/opennoise/static/app.css").read_text(encoding="utf-8")
        for selector in (
            "#static-map-viewport",
            "#open-static-map",
            "#map-view-switch",
            "#layout-lenses",
            "#historical-fallback",
        ):
            self.assertNotIn(selector, stylesheet)
        self.assertFalse((ROOT / "scripts/capture_production_map_browser.mjs").exists())
        self.assertFalse((ROOT / "docs/serving/STATIC_PUBLIC_MAP.md").exists())


if __name__ == "__main__":
    unittest.main()
