import json
import shutil
import tempfile
import unittest
from pathlib import Path

from scripts.materialize_fma_membership_example import RECIPE, materialize, validate_recipe


class MaterializeFmaMembershipTests(unittest.TestCase):
    def test_recipe_has_exact_known_inventory_and_verified_payloads(self) -> None:
        files = validate_recipe(RECIPE)
        self.assertEqual(9, len(files))
        self.assertIn("fma_memberships.py", files)
        self.assertIn("calibration-memberships.jsonl.zst", files)

    def test_manifest_inventory_tampering_is_rejected_before_output_creation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            recipe = tmp_path / "recipe"
            shutil.copytree(RECIPE, recipe)
            manifest_path = recipe / "recipe-manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["sources"].pop("thresholds.json")
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            output = tmp_path / "new-output"
            with self.assertRaisesRegex(ValueError, "inventory"):
                materialize(recipe, output)
            self.assertFalse(output.exists())

    def test_strict_base64_tampering_is_rejected_before_output_creation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            recipe = tmp_path / "recipe"
            shutil.copytree(RECIPE, recipe)
            payload = recipe / "calibration-memberships.jsonl.zst.base64.txt"
            payload.write_bytes(b"!" + payload.read_bytes())
            output = tmp_path / "new-output"
            with self.assertRaisesRegex(ValueError, "strict base64"):
                materialize(recipe, output)
            self.assertFalse(output.exists())

    def test_existing_output_is_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "existing"
            output.mkdir()
            marker = output / "keep.txt"
            marker.write_text("keep", encoding="utf-8")
            with self.assertRaises(FileExistsError):
                materialize(RECIPE, output)
            self.assertEqual("keep", marker.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
