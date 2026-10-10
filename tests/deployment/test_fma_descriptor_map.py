"""Static map views preserve exact source domains and bounded coordinate shards."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from opennoise.deployment.fma_descriptor_map import export_descriptor_map


class DescriptorMapExportTests(unittest.TestCase):
    def test_complete_native_identity_and_missing_positions_are_retained(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            source = root / "source"
            output = root / "output"
            source.mkdir()
            output.mkdir()
            (source / "receipt.json").write_text("{}")
            coordinates = {
                "source": {"metadata/corpus-receipt.json": "a" * 64},
                "genres": [{"genre_id": 1, "position": None}],
                "artists": [{"artist_id": 2, "position": [1.0, -2.0]}],
                "axes": [],
                "denominators": {"native_genres": 1, "native_artists": 1},
            }
            tables = {"genres": [{"genre_id": 1}], "artists": [{"artist_id": 2}]}
            with patch(
                "opennoise.deployment.fma_descriptor_map.validate_fresh_map",
                return_value=coordinates,
            ):
                with self.assertRaisesRegex(ValueError, "capture differs"):
                    export_descriptor_map(source, output, {}, tables, "b" * 64)
                files = {}
                result = export_descriptor_map(source, output, files, tables, "a" * 64)
                self.assertLess(result["bytes"], 200_000)
                manifest = json.loads((output / result["manifest"]).read_bytes())
                self.assertEqual(manifest["genres"], [{"id": 1, "position": None}])
                artists = json.loads((output / manifest["artist_shards"][0]).read_bytes())
                self.assertEqual(artists, [{"id": 2, "position": [1.0, -2.0]}])
                self.assertFalse(manifest["musical_validation_established"])
                coordinates["artists"].append(coordinates["artists"][0])
                with self.assertRaisesRegex(ValueError, "identity coverage differs"):
                    export_descriptor_map(source, output, {}, tables, "a" * 64)
                coordinates["artists"].pop()
                coordinates["artists"][0]["position"] = [float("nan"), 0]
                with self.assertRaisesRegex(ValueError, "coordinate is invalid"):
                    export_descriptor_map(source, output, {}, tables, "a" * 64)
