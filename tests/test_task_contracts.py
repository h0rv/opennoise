"""Regression tests for the public developer-command contract."""

import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class TaskContractTests(unittest.TestCase):
    """Keep Poe as the sole project task runner."""

    def test_poe_exposes_required_project_tasks_without_mise_task_aliases(self) -> None:
        mise = tomllib.loads((ROOT / "mise.toml").read_text(encoding="utf-8"))
        project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        poe_tasks = project["tool"]["poe"]["tasks"]

        self.assertNotIn("tasks", mise)
        self.assertTrue(
            {
                "sync",
                "bootstrap",
                "dev",
                "dev-legacy",
                "check",
                "release-certify",
            }.issubset(poe_tasks)
        )
        self.assertEqual(poe_tasks["sync"], "uv sync --locked")

        self.assertEqual(
            poe_tasks["release-certify"]["cmd"],
            "python scripts/release_certify.py",
        )

    def test_production_startup_error_names_the_direct_certification_command(self) -> None:
        startup_script = (ROOT / "scripts" / "run_dev.py").read_text(encoding="utf-8")

        self.assertIn("uv run poe release-certify", startup_script)

    def test_active_release_docs_use_the_verified_cache_with_poe(self) -> None:
        documentation = "\n".join(
            (ROOT / path).read_text(encoding="utf-8")
            for path in ("README.md", "docs/PUBLIC_RELEASE_PIPELINE.md")
        )

        self.assertNotIn("mise run", documentation)
        self.assertIn("uv run poe release-certify", documentation)
        self.assertIn(
            ".cache/listenbrainz-qualified-input/sha256/"
            "282bf216f0e56a44766353bf41e33d4069e162332b936ae15234ddf6f7d62866.sqlite",
            documentation,
        )


if __name__ == "__main__":
    unittest.main()
