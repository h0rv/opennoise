"""Bounded native album-title search preserves identities and missing metadata."""

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from opennoise.common import sha256_file
from opennoise.deployment.fma_album_search import MAX_SHARD_BYTES, export_album_search
from opennoise.deployment.fma_albums import export_albums
from opennoise.deployment.fma_static import _write


class FMAAlbumSearchTests(unittest.TestCase):
    def test_existing_groups_keep_colliding_titles_compilations_and_missing_fields(self) -> None:
        tracks = [
            {"track_id": 1, "artist_id": 1, "album_id": 9, "album_title": "Same"},
            {"track_id": 2, "artist_id": 2, "album_id": 9, "album_title": "Same"},
            {"track_id": 3, "artist_id": 1, "album_id": 8, "album_title": "Same"},
            {"track_id": 4, "artist_id": None, "album_id": 7, "album_title": None},
            {"track_id": 5, "artist_id": 1, "album_id": None, "album_title": "Unbound"},
        ]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            files: dict[str, Any] = {}
            manifest, _ = export_albums(root, tracks, files, _write)
            self.assertEqual(manifest["missing_album_tracks"], 1)
            search = manifest["search"]
            self.assertEqual(search["row_count"], 3)
            self.assertEqual(
                json.loads((root / search["shards"][0]).read_bytes()),
                [[7, None, 1, 0], [8, "Same", 1, 1], [9, "Same", 2, 2]],
            )
            self.assertEqual(
                search["bytes"], sum(files[path]["bytes"] for path in search["shards"])
            )
            for path in search["shards"]:
                self.assertEqual(
                    sha256_file(root / path), (files[path]["sha256"], files[path]["bytes"])
                )

    def test_chunks_bounded_and_complete(self) -> None:
        rows = [[i, "é" * 100, 1, 1] for i in range(2000, 0, -1)]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            files: dict[str, Any] = {}
            manifest = export_album_search(root, rows, files, _write)
            self.assertGreater(len(manifest["shards"]), 1)
            self.assertEqual(
                [
                    row
                    for path in manifest["shards"]
                    for row in json.loads((root / path).read_bytes())
                ],
                sorted(rows),
            )
            self.assertTrue(all(binding["bytes"] <= MAX_SHARD_BYTES for binding in files.values()))
            self.assertEqual(manifest["bytes"], sum(binding["bytes"] for binding in files.values()))

    def test_duplicate_overlong_and_total_bound_fail_before_writes(self) -> None:
        for rows in [[[1, "A", 1, 1], [1, "B", 1, 1]], [[1, "x" * 200_000, 1, 1]]]:
            with tempfile.TemporaryDirectory() as directory, self.assertRaises(ValueError):
                export_album_search(Path(directory), rows, {}, _write)
        with tempfile.TemporaryDirectory() as directory:
            with (
                patch("opennoise.deployment.fma_album_search.MAX_SEARCH_BYTES", 10),
                self.assertRaisesRegex(ValueError, "2 MB"),
            ):
                export_album_search(Path(directory), [[1, "Long title", 1, 1]], {}, _write)
            self.assertEqual(list(Path(directory).iterdir()), [])
