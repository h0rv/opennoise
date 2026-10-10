"""Fresh protocol custody fixtures; shared PCA math has separate held-out isolation tests."""

from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from opennoise.ml import fma_fresh_map as m


class FreshMapTests(unittest.TestCase):
    def test_freeze_is_exclusive_and_input_mutation_rejects_before_math(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            for path in m.INPUTS:
                target = root / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b"fixture")
            declaration = root / "declaration.json"
            frozen = m.freeze_fresh_map(root, declaration)
            self.assertEqual(frozen["protocol"], m.PROTOCOL)
            with self.assertRaises(FileExistsError):
                m.freeze_fresh_map(root, declaration)
            (root / m.INPUTS[0]).write_bytes(b"tampered")
            with self.assertRaisesRegex(ValueError, "frozen input"):
                m.derive_fresh_map(root, declaration)

    def test_fresh_receipt_rejects_scope_hash_and_inventory_changes(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            for path in m.INPUTS:
                target = root / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b"fixture")
            declaration = root / "declaration.json"
            frozen = m.freeze_fresh_map(root, declaration)
            coordinates = {
                "revision": m.REVISION,
                "namespace": "native-fma-fresh-descriptor-pca-v1",
                "source": {key: value["sha256"] for key, value in frozen["inputs"].items()},
                "metadata_license": "CC-BY-4.0",
                "audio_used": False,
                "musical_axis_semantics": None,
                "artist_genres_inferred": False,
                "musical_validation_established": False,
                "public_product_promotion_authorized": False,
                "pca_training": {"fit_heldout_tracks": 0},
                "denominators": {},
            }
            output = root / "map"
            with patch.object(m, "derive_fresh_map", return_value=coordinates):
                m.build_fresh_map(root, declaration, output)
                self.assertTrue(m.replay_fresh_map(root, output)["all_source_coordinates_replayed"])
            self.assertEqual(m.validate_fresh_map(output), coordinates)
            receipt_path = output / "receipt.json"
            original = receipt_path.read_bytes()
            receipt = json.loads(original)
            changed = copy.deepcopy(receipt)
            changed["protocol"]["audio_used"] = True
            receipt_path.write_text(json.dumps(changed))
            with self.assertRaises(ValueError):
                m.validate_fresh_map(output)
            receipt_path.write_bytes(original)
            (output / "unexpected").write_bytes(b"x")
            with self.assertRaises(ValueError):
                m.validate_fresh_map(output)
            (output / "unexpected").unlink()
            (output / "coordinates.json").write_text("{}")
            with self.assertRaises(ValueError):
                m.validate_fresh_map(output)
