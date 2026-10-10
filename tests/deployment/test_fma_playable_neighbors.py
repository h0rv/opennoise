"""Local neighbor attachment must match verified audio and native artists."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from opennoise.deployment.fma_playable_neighbors import export_playable_neighbors


class PlayableNeighborExportTests(unittest.TestCase):
    def test_exact_audio_pool_and_cross_artist_binding(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            playback = {
                "manifest_sha256": "a" * 64,
                "tracks": [{"track_id": 1, "artist_id": 10}, {"track_id": 2, "artist_id": 20}],
            }
            manifest = {
                "rows": [
                    {"track_id": 1, "neighbor_ids": [2], "reason": None},
                    {"track_id": 2, "neighbor_ids": [1], "reason": None},
                ],
                "counts": {"queries": 2},
            }
            with patch(
                "opennoise.deployment.fma_playable_neighbors.validate_playable_neighbors",
                return_value=manifest,
            ) as validator:
                with self.assertRaisesRegex(ValueError, "require an audio"):
                    export_playable_neighbors(root, root / "none", {}, None)
                incomplete = {**playback, "tracks": playback["tracks"][:1]}
                with self.assertRaisesRegex(ValueError, "coverage differs"):
                    export_playable_neighbors(root, root / "missing", {}, incomplete)
                same_artist = {
                    **playback,
                    "tracks": [{"track_id": 1, "artist_id": 10}, {"track_id": 2, "artist_id": 10}],
                }
                with self.assertRaisesRegex(ValueError, "artist isolation"):
                    export_playable_neighbors(root, root / "same", {}, same_artist)
                files = {}
                result = export_playable_neighbors(root, root / "valid", files, playback)
                validator.assert_called_with(root, "a" * 64)
                path = root / "valid" / result["manifest_path"]
                self.assertEqual(json.loads(path.read_bytes()), manifest)
                self.assertEqual(
                    files[result["manifest_path"]]["sha256"], result["manifest_sha256"]
                )
                self.assertFalse((root / "same").exists())
