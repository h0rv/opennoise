import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


class OpenConstructionGraphV2DocumentationTests(unittest.TestCase):
    def test_docs_make_build_input_and_v1_to_v2_migration_explicit(self) -> None:
        document = (ROOT / "docs" / "serving" / "OPEN_CONSTRUCTION_GRAPH_V2.md").read_text(
            encoding="utf-8"
        )

        self.assertIn("public-taxonomy-expansion-v1", document)
        self.assertIn("MUSIX_OPEN_CONSTRUCTION_GRAPH_V2_PATH", document)
        self.assertIn("/api/open-construction-map/v2", document)
        self.assertIn("remain v1", document)
        self.assertIn("never scans `.cache`", document)
        self.assertIn("link is promoted to taxonomy fact", document)


if __name__ == "__main__":
    unittest.main()
