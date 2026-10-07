"""Native FMA search export contracts."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from opennoise.common import sha256_file
from opennoise.deployment.fma_track_search import export_track_search


class FMATrackSearchTests(unittest.TestCase):
    def test_native_rows_sorted_preserve_missing_values_and_bind_bytes(self) -> None:
        tracks = [
            {"track_id": 9, "title": None, "artist_id": None},
            {"track_id": 2, "title": "日本語 <script> & café", "artist_id": 999},
        ]
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            files = {}
            manifest = export_track_search(output, tracks, files)
            self.assertEqual(manifest["columns"], ["track_id", "title", "artist_id"])
            self.assertEqual(manifest["row_count"], len(tracks))
            self.assertEqual(manifest["shards"], ["track-search/0.json"])
            path = output / manifest["shards"][0]
            self.assertEqual(
                json.loads(path.read_bytes()),
                [[2, "日本語 <script> & café", 999], [9, None, None]],
            )
            digest, length = sha256_file(path)
            self.assertEqual(
                files[path.relative_to(output).as_posix()], {"sha256": digest, "bytes": length}
            )
            self.assertEqual(manifest["bytes"], length)
            self.assertEqual(tracks[0]["track_id"], 9)

    def test_dynamic_sharding_exact_byte_bound_and_determinism(self) -> None:
        tracks = [{"track_id": i, "title": "é" * 8, "artist_id": i} for i in range(12)]
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            with patch("opennoise.deployment.fma_track_search.MAX_SHARD_BYTES", 70):
                manifest = export_track_search(Path(first), tracks, {})
                repeated = export_track_search(Path(second), list(reversed(tracks)), {})
            self.assertEqual(manifest, repeated)
            self.assertGreater(len(manifest["shards"]), 1)
            rows = []
            for relative in manifest["shards"]:
                payload = (Path(first) / relative).read_bytes()
                self.assertLessEqual(len(payload), 70)
                self.assertEqual(payload, (Path(second) / relative).read_bytes())
                rows.extend(json.loads(payload))
            self.assertEqual([row[0] for row in rows], list(range(12)))

    def test_empty_index(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            files = {}
            manifest = export_track_search(Path(directory), [], files)
            self.assertEqual(manifest["shards"], [])
            self.assertEqual(manifest["row_count"], 0)
            self.assertEqual(files, {})

    def test_oversize_row_and_total_and_duplicate_ids_rejected(self) -> None:
        track = {"track_id": 1, "title": "a" * 100, "artist_id": 2}
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            with (
                patch("opennoise.deployment.fma_track_search.MAX_SHARD_BYTES", 50),
                self.assertRaisesRegex(ValueError, "row exceeds"),
            ):
                export_track_search(output, [track], {})
            with (
                patch("opennoise.deployment.fma_track_search.MAX_SEARCH_BYTES", 50),
                self.assertRaisesRegex(ValueError, "index exceeds"),
            ):
                export_track_search(output, [track], {})
            with self.assertRaisesRegex(ValueError, "duplicate"):
                export_track_search(output, [track, track], {})

    def test_existing_export_is_not_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            tracks = [{"track_id": 1, "title": "One", "artist_id": 1}]
            export_track_search(output, tracks, {})
            original = (output / "track-search/0.json").read_bytes()
            with self.assertRaises(FileExistsError):
                export_track_search(output, tracks, {})
            self.assertEqual((output / "track-search/0.json").read_bytes(), original)
