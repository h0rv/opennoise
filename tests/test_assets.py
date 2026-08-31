import hashlib
import json
import unittest
from pathlib import Path


class AssetTests(unittest.TestCase):
    def test_vendored_htmx_matches_the_manifest(self) -> None:
        static = Path("src/musix/static")
        manifest = json.loads((static / "assets.json").read_text(encoding="utf-8"))
        asset = (static / manifest["htmx"]["file"]).read_bytes()
        self.assertEqual(manifest["htmx"]["version"], "4.0.0")
        self.assertEqual(len(asset), manifest["htmx"]["bytes"])
        self.assertEqual(hashlib.sha256(asset).hexdigest(), manifest["htmx"]["sha256"])


if __name__ == "__main__":
    unittest.main()
