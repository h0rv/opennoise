"""Synthetic metadata-only discovery fixtures; no actual audio or quality evidence."""

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

import zstandard

from opennoise.common import canonical_json
from opennoise.deployment.fma_genre_discovery import (
    _body,
    _neighbor_binding,
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

    def test_optional_neighbors_are_byte_bound_and_isolated(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            explorer = root / "original" / "explorer"
            (explorer / "playable-neighbors").mkdir(parents=True)
            relative = "playable-neighbors/manifest.json"
            manifest: dict[str, Any] = {
                "revision": "fma-playable-descriptor-neighbors-v1",
                "audio_manifest_sha256": "a" * 64,
                "fitted": False,
                "labels_used": False,
                "musical_relevance_established": False,
                "components": {"1": 10, "2": 20},
                "rows": [
                    {"track_id": 1, "neighbor_ids": [2], "reason": None},
                    {"track_id": 2, "neighbor_ids": [1], "reason": None},
                ],
                "counts": {
                    "queries": 2,
                    "supported_queries": 2,
                    "directed_edges": 2,
                    "abstentions": {},
                },
            }
            catalog: dict[str, Any] = {
                "playback": {
                    "tracks": [{"track_id": 1, "artist_id": 1}, {"track_id": 2, "artist_id": 2}]
                }
            }
            self.assertIsNone(_neighbor_binding(root, "original", catalog, "a" * 64))

            def save(value: dict[str, Any]) -> None:
                body = canonical_json(value)
                digest = hashlib.sha256(body).hexdigest()
                (explorer / relative).write_bytes(body)
                inventory = zstandard.ZstdCompressor().compress(
                    canonical_json({relative: {"sha256": digest, "bytes": len(body)}})
                )
                (explorer / "files-manifest.json.zst").write_bytes(inventory)
                (explorer / "static-receipt.json").write_text(
                    json.dumps(
                        {
                            "files_manifest": {
                                "path": "files-manifest.json.zst",
                                "sha256": hashlib.sha256(inventory).hexdigest(),
                                "bytes": len(inventory),
                            }
                        }
                    )
                )
                catalog["playable_neighbors"] = {
                    "manifest_path": relative,
                    "manifest_sha256": digest,
                    "counts": value["counts"],
                }

            save(manifest)
            binding = _neighbor_binding(root, "original", catalog, "a" * 64)
            assert binding is not None
            self.assertEqual(
                binding["manifest_path"], "original/explorer/playable-neighbors/manifest.json"
            )
            for mutation in ("audio", "claims", "duplicate", "component", "unsupported", "outside"):
                changed = copy.deepcopy(manifest)
                if mutation == "audio":
                    changed["audio_manifest_sha256"] = "b" * 64
                elif mutation == "claims":
                    changed["fitted"] = True
                elif mutation == "duplicate":
                    changed["rows"][1]["track_id"] = 1
                elif mutation == "component":
                    changed["components"]["2"] = 10
                elif mutation == "unsupported":
                    changed["rows"][1]["reason"] = "outside_training_support"
                    changed["rows"][1]["neighbor_ids"] = []
                else:
                    changed["rows"][0]["neighbor_ids"] = [3]
                save(changed)
                with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                    _neighbor_binding(root, "original", catalog, "a" * 64)
            save(manifest)
            catalog["playback"]["tracks"][1]["artist_id"] = 1
            with self.assertRaisesRegex(ValueError, "isolation"):
                _neighbor_binding(root, "original", catalog, "a" * 64)
            catalog["playback"]["tracks"][1]["artist_id"] = 2
            (explorer / relative).write_bytes(b"{}")
            with self.assertRaisesRegex(ValueError, "bytes differ"):
                _neighbor_binding(root, "original", catalog, "a" * 64)
