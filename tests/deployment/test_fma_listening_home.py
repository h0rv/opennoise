"""Collection landing counts native overlap without claiming representative coverage."""

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from opennoise.common import canonical_json, sha256_file
from opennoise.deployment.fma_listening_home import build_listening_home
from opennoise.deployment.fma_playback import COLLECTION_REVISION, REVISION


class ListeningHomeTests(unittest.TestCase):
    def test_union_and_added_genres_keep_overlap_and_same_source_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            for key, identities in (("original", [1, 2]), ("expanded", [2, 3])):
                base = root / key
                (base / "audio").mkdir(parents=True)
                (base / "explorer").mkdir()
                (base / "audio" / "manifest.json").write_text(json.dumps(identities))
                catalog = {
                    "collection": {"label": key},
                    "genres": [{"genre_id": i, "title": f"Genre {i}"} for i in (1, 2, 3)],
                    "playback": {
                        "manifest_sha256": sha256_file(base / "audio" / "manifest.json")[0],
                        "tracks": [
                            {"track_id": i, "artist_id": i, "genre_ids": [i]} for i in identities
                        ],
                    },
                }
                (base / "explorer" / "catalog.json").write_text(json.dumps(catalog))
                (base / "explorer" / "static-receipt.json").write_text(
                    json.dumps({"source_receipt_sha256": "a" * 64})
                )

            native = {str(i): {"artist_id": i} for i in (1, 2, 3)}
            inventory = {
                key: {
                    "artist_id": row["artist_id"],
                    "genre_ids": [int(key)],
                    "record_sha256": hashlib.sha256(canonical_json(row)).hexdigest(),
                }
                for key, row in native.items()
            }
            original = {
                "revision": REVISION,
                "source_pack_sha256": "b" * 64,
                "tracks": {key: native[key] for key in ("1", "2")},
            }
            expanded = {
                "revision": COLLECTION_REVISION,
                "tracks": {key: native[key] for key in ("2", "3")},
                "sources": {
                    "original": {
                        "manifest_sha256": sha256_file(root / "original/audio/manifest.json")[0],
                        "capture_sha256": "b" * 64,
                        "metadata_source_receipt_sha256": "a" * 64,
                        "tracks": {key: inventory[key] for key in ("1", "2")},
                    },
                    "expanded": {"tracks": {"3": inventory["3"]}},
                },
            }

            def audio(path: Path) -> dict[str, Any]:
                return original if path.parent.name == "original" else expanded

            # Reject broken sibling association before writing a landing.
            for field in ("manifest_sha256", "capture_sha256"):
                saved = expanded["sources"]["original"][field]
                expanded["sources"]["original"][field] = "c" * 64
                with (
                    patch(
                        "opennoise.deployment.fma_listening_home.validate_playback_export",
                        side_effect=audio,
                    ),
                    self.assertRaisesRegex(ValueError, "association"),
                ):
                    build_listening_home(root)
                expanded["sources"]["original"][field] = saved
            catalog_path = root / "expanded/explorer/catalog.json"
            saved_catalog = catalog_path.read_bytes()
            for mutation in ("duplicate", "artist", "genre"):
                changed = json.loads(saved_catalog)
                rows = changed["playback"]["tracks"]
                if mutation == "duplicate":
                    rows.append(rows[0])
                elif mutation == "artist":
                    rows[0]["artist_id"] = 999
                else:
                    rows[0]["genre_ids"] = [999]
                catalog_path.write_text(json.dumps(changed))
                with (
                    patch(
                        "opennoise.deployment.fma_listening_home.validate_playback_export",
                        side_effect=audio,
                    ),
                    self.assertRaises(ValueError),
                ):
                    build_listening_home(root)
                self.assertFalse((root / "index.html").exists())
            catalog_path.write_bytes(saved_catalog)

            with patch(
                "opennoise.deployment.fma_listening_home.validate_playback_export",
                side_effect=audio,
            ):
                result = build_listening_home(root)
            self.assertEqual(result["distinct_clips"], 3)
            self.assertEqual(result["shared_clips"], 1)
            self.assertEqual(result["new_clips"], 1)
            self.assertEqual(result["new_direct_genre_ids"], [3])
            self.assertEqual(result["musical_representativeness"], "not_judged")
            page = (root / "index.html").read_text()
            self.assertIn("expanded/explorer/index.html#listen&amp;genre=3", page)
            self.assertNotIn("#listen&amp;genre=2", page)
            with self.assertRaisesRegex(ValueError, "must be new"):
                build_listening_home(root)
