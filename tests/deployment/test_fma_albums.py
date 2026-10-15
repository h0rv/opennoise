"""Native album membership, missing metadata and unchanged shard guards."""

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

from opennoise.common import sha256_file
from opennoise.deployment.fma_albums import export_albums
from opennoise.deployment.fma_static import _write


def track(
    track_id: int, artist: int | None, album: int | None, title: str | None
) -> dict[str, Any]:
    """Create one minimal native-source track fixture."""
    return {"track_id": track_id, "artist_id": artist, "album_id": album, "album_title": title}


class FMAAlbumTests(unittest.TestCase):
    def test_exact_source_compilations_and_missing_fields_without_inheritance(self) -> None:
        tracks = [
            track(5, 2, 77, "Compilation"),
            track(2, 1, 77, "Compilation"),
            track(3, None, 78, None),
            track(6, 1, None, "Unbound title"),
        ]
        with tempfile.TemporaryDirectory() as name:
            output = Path(name)
            files: dict[str, Any] = {}
            manifest, artists = export_albums(output, tracks, files, _write)
            self.assertEqual(manifest["album_count"], 2)
            self.assertEqual(manifest["missing_album_tracks"], 1)
            self.assertEqual(
                artists,
                {1: [[77, "Compilation", 1]], 2: [[77, "Compilation", 1]], None: [[78, None, 1]]},
            )
            album = json.loads((output / "albums/77.json").read_bytes())["albums"]["77"]
            self.assertEqual(
                album,
                {"album_id": 77, "title": "Compilation", "track_ids": [2, 5], "artist_ids": [1, 2]},
            )
            self.assertNotIn("genre_ids", album)
            missing = json.loads((output / "albums/78.json").read_bytes())["albums"]["78"]
            self.assertIsNone(missing["title"])
            self.assertEqual(missing["artist_ids"], [None])
            self.assertEqual(len(files), 128)
            for relative, binding in files.items():
                self.assertEqual(
                    sha256_file(output / relative), (binding["sha256"], binding["bytes"])
                )

    def test_conflicting_titles_duplicate_ids_and_invalid_native_album_fail(self) -> None:
        cases = [
            [track(2, 1, 77, "A"), track(3, 1, 77, "B")],
            [track(2, 1, 77, "A"), track(2, 1, 77, "A")],
            [track(2, 1, 0, "A")],
            [track(2, 1, album=True, title="A")],
        ]
        for rows in cases:
            with (
                self.subTest(rows=rows),
                tempfile.TemporaryDirectory() as name,
                self.assertRaises(ValueError),
            ):
                export_albums(Path(name), rows, {}, _write)

    def test_existing_shard_limit_is_enforced_and_existing_files_are_not_replaced(self) -> None:
        with tempfile.TemporaryDirectory() as name, self.assertRaisesRegex(ValueError, "200 KB"):
            export_albums(Path(name), [track(2, 1, 1, "x" * 200_000)], {}, _write)
        with tempfile.TemporaryDirectory() as name:
            output = Path(name)
            export_albums(output, [], {}, _write)
            before = (output / "albums/0.json").read_bytes()
            with self.assertRaises(FileExistsError):
                export_albums(output, [], {}, _write)
            self.assertEqual((output / "albums/0.json").read_bytes(), before)
