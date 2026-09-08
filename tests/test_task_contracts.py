"""Regression tests for the public developer-command contract."""

import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class TaskContractTests(unittest.TestCase):
    """Keep documented production commands reachable through both task runners."""

    def test_mise_exposes_the_poe_release_certification_boundary(self) -> None:
        mise = tomllib.loads((ROOT / "mise.toml").read_text(encoding="utf-8"))
        project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

        release_task = mise["tasks"]["release-certify"]

        self.assertEqual(release_task["depends"], ["sync"])
        self.assertEqual(release_task["run"], "uv run poe release-certify")
        self.assertEqual(
            project["tool"]["poe"]["tasks"]["release-certify"]["cmd"],
            "python scripts/release_certify.py",
        )

    def test_production_startup_error_names_the_direct_certification_command(self) -> None:
        startup_script = (ROOT / "scripts" / "run_dev.py").read_text(encoding="utf-8")

        self.assertIn("uv run poe release-certify", startup_script)


if __name__ == "__main__":
    unittest.main()
