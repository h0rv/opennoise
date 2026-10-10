"""Synthetic metadata-only discovery fixtures; no actual audio or quality evidence."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from opennoise.deployment.fma_genre_discovery import (
    _body,
    _verified_inputs,
    build_genre_discovery,
    genre_index,
)


class GenreDiscoveryTests(unittest.TestCase):
    def test_union_unavailable_and_distinct_artist_starters(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            catalogs, audio = {}, {}
            genres = [
                {"genre_id": i, "title": f"Genre {i}", "parent_id": None, "track_count": 99}
                for i in (1, 2, 3)
            ]
            native = {
                1: {"artist_id": 1, "genre_ids": [1]},
                2: {"artist_id": 1, "genre_ids": [1]},
                3: {"artist_id": 2, "genre_ids": [1, 2]},
                4: {"artist_id": 3, "genre_ids": [1]},
                5: {"artist_id": 4, "genre_ids": [1, 2]},
            }
            for key, ids in (("original", (1, 2, 3)), ("expanded", (1, 4, 5))):
                (root / key / "audio").mkdir(parents=True)
                (root / key / "audio" / "manifest.json").write_text("{}")
                catalogs[key] = {
                    "genres": genres,
                    "playback": {"tracks": [{"track_id": i, **native[i]} for i in ids]},
                }
                audio[key] = {
                    "tracks": {
                        str(i): {"title": f"Track {i}", "artist_name": "Artist"} for i in ids
                    }
                }
            receipt = {
                "collections": [{"key": key, "catalog_sha256": "a" * 64} for key in catalogs]
            }
            (root / "collections.json").write_text(json.dumps(receipt))
            with patch(
                "opennoise.deployment.fma_genre_discovery._verified_inputs",
                return_value=(receipt, catalogs, audio),
            ):
                result = genre_index(root)
                self.assertEqual(
                    result["counts"], {"genres": 3, "playable_genres": 2, "artists": 4, "clips": 5}
                )
                self.assertEqual(result["genres"][0]["track_ids"], [1, 2, 3, 4, 5])
                self.assertEqual(result["genres"][0]["starting_ids"], [1, 4, 3])
                self.assertFalse(result["genres"][2]["available"])
                self.assertEqual(result["genres"][2]["starting_ids"], [])
                self.assertEqual(result["tracks"]["1"]["origins"], ["original", "expanded"])
                self.assertEqual(result["tracks"]["1"]["collection"], "original")
                self.assertFalse(result["musical_quality_validated"])
                audio["expanded"]["tracks"]["1"]["title"] = "different"
                with self.assertRaisesRegex(ValueError, "shared native"):
                    genre_index(root)
                audio["expanded"]["tracks"]["1"]["title"] = "Track 1"
                catalogs["expanded"]["genres"] = genres[:-1]
                with self.assertRaisesRegex(ValueError, "genre catalogs"):
                    genre_index(root)

    def test_snapshot_replays_receipt_and_rejects_drift(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            for key in ("original", "expanded"):
                for folder in ("audio", "explorer"):
                    (root / key / folder).mkdir(parents=True)
                for filename in ("catalog.json", "static-receipt.json"):
                    (root / key / "explorer" / filename).write_text("{}")
                (root / key / "audio" / "manifest.json").write_text("{}")
            (root / "collections.json").write_text('{"binding": "expected"}')
            with patch(
                "opennoise.deployment.fma_genre_discovery.build_listening_home",
                return_value={"binding": "expected"},
            ) as replay:
                _verified_inputs(root)
                self.assertEqual(replay.call_count, 1)
                replay.return_value = {"binding": "changed"}
                with self.assertRaisesRegex(ValueError, "receipt differs"):
                    _verified_inputs(root)
            (root / "original" / "audio" / "bad.mp3").symlink_to(root / "collections.json")
            with self.assertRaisesRegex(ValueError, "symlinked"):
                _verified_inputs(root)

    def test_explicit_install_preserves_chooser_and_rejects_replacement(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            (root / "index.html").write_bytes(b"original chooser")

            def body(path: Path, limit: int = 2_000_000) -> bytes:
                if path.parent.name == "static":
                    return b"fixture discovery asset"
                return _body(path, limit)

            with (
                patch(
                    "opennoise.deployment.fma_genre_discovery.genre_index",
                    return_value={"counts": {}},
                ),
                patch("opennoise.deployment.fma_genre_discovery._body", side_effect=body),
            ):
                build_genre_discovery(root)
                self.assertEqual((root / "collections.html").read_bytes(), b"original chooser")
                self.assertEqual((root / "index.html").read_bytes(), b"fixture discovery asset")
                self.assertTrue((root / "genre-discovery.json").is_file())
                self.assertTrue((root / "fma-playback.js").is_file())
                with self.assertRaisesRegex(ValueError, "outputs must be fresh"):
                    build_genre_discovery(root)
                self.assertEqual((root / "collections.html").read_bytes(), b"original chooser")
