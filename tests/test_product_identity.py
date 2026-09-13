"""Guard the complete OpenNoise product and module rename."""

from __future__ import annotations

import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GIT = "/usr/bin/git"
_LEGACY_LOWER = "musi" + "x"
_LEGACY_TITLE = "Musi" + "x"
_LEGACY_ENV = _LEGACY_LOWER.upper() + "_"


class ProductIdentityTests(unittest.TestCase):
    """Ensure tracked names and text carry only the OpenNoise identity."""

    def test_no_legacy_product_identity_remains_in_tracked_files(self) -> None:
        result = subprocess.run(  # noqa: S603 -- fixed Git binary and arguments inspect this repository.
            [GIT, "ls-files", "-z"],
            cwd=ROOT,
            check=True,
            capture_output=True,
        )
        relative_paths = tuple(
            entry.decode("utf-8") for entry in result.stdout.split(b"\0") if entry
        )
        self.assertTrue(relative_paths)
        self.assertTrue(all(_LEGACY_LOWER not in path.casefold() for path in relative_paths))
        for relative_path in relative_paths:
            path = ROOT / relative_path
            try:
                content = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            self.assertNotIn(_LEGACY_LOWER, content.casefold(), path.as_posix())
            self.assertNotIn(_LEGACY_TITLE, content, path.as_posix())
            self.assertNotIn(_LEGACY_ENV, content, path.as_posix())


if __name__ == "__main__":
    unittest.main()
