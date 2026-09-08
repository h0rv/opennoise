import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")


@unittest.skipUnless(NODE, "Node is required for the renderer transform contract")
class OpenConstructionDisplayTransformTests(unittest.TestCase):
    def test_reversible_display_transform_contract(self) -> None:
        result = subprocess.run(  # noqa: S603
            [str(NODE), "scripts/test_open_construction_display_transform.mjs"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertIn('"passed":true', result.stdout)


if __name__ == "__main__":
    unittest.main()
