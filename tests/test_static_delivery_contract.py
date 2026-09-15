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
        for removed in (
            "dev-research",
            "dev-legacy",
            "export-opennoise-pages",
            "release-certify",
            "ui-qa",
            "open-v2-qa",
        ):
            self.assertNotIn(removed, tasks)

    def test_dev_script_is_a_static_loopback_server(self) -> None:
        source = (ROOT / "scripts" / "run_dev.py").read_text(encoding="utf-8")
        self.assertIn("SimpleHTTPRequestHandler", source)
        self.assertIn("ThreadingHTTPServer", source)
        self.assertNotIn("opennoise.serving", source)
        self.assertNotIn("uvicorn", source)

    def test_runtime_framework_dependencies_are_absent(self) -> None:
        project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        dependencies = set(project["project"]["dependencies"])
        self.assertFalse(
            {dependency.split("=", 1)[0].split(">", 1)[0] for dependency in dependencies}
            & {"jinja2", "litestar", "uvicorn"}
        )


if __name__ == "__main__":
    unittest.main()
