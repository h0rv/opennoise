"""Guard the single static delivery surface."""

from __future__ import annotations

import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class StaticDeliveryContractTests(unittest.TestCase):
    """The product may export and serve files, but never construct an app backend."""

    def test_poe_exposes_one_static_export_and_a_file_server(self) -> None:
        project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        tasks = project["tool"]["poe"]["tasks"]
        self.assertEqual(tasks["dev"], "python scripts/run_dev.py")
        self.assertIn("export-semantic-pages", tasks)
        self.assertIn("certify-static-pages", tasks)
        self.assertEqual(tasks["certify-static-pages"], "python scripts/certify_static_pages.py")
        self.assertEqual(
            tasks["rebuild-certify-semantic-pages"],
            {"sequence": ["rebuild-semantic-map-layout", "certify-static-pages"]},
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
        self.assertIn("uv run poe certify-static-pages", documentation)
        self.assertIn("uv run poe dev -- --port 3010", documentation)

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


if __name__ == "__main__":
    unittest.main()
