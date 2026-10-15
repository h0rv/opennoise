"""Synthetic map navigation custody; no musical or real-audio judgments."""

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

import zstandard

from opennoise.common import canonical_json
from opennoise.deployment.fma_genre_discovery import _descriptor_binding


class DescriptorNavigationTests(unittest.TestCase):
    def test_only_complete_source_bound_map_exposes_a_fixed_local_route(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            explorer = root / "expanded" / "explorer"
            (explorer / "descriptor-map").mkdir(parents=True)
            metadata = b"{}"
            (explorer / "corpus-receipt.json").write_bytes(metadata)
            relative = "descriptor-map/manifest.json"
            shard = "descriptor-map/artists-0.json"
            content = canonical_json([{"id": 7, "position": None}])
            binding = {"sha256": hashlib.sha256(content).hexdigest(), "bytes": len(content)}
            manifest: dict[str, Any] = {
                "revision": "fma-descriptor-map-view-v1",
                "musical_validation_established": False,
                "metadata_receipt_sha256": hashlib.sha256(metadata).hexdigest(),
                "artist_shards": [shard],
                "files": {shard: binding},
                "genres": [{"id": 1, "position": None}],
                "counts": {"native_artists": 1},
            }
            catalog: dict[str, Any] = {
                "genres": [{"genre_id": 1}],
                "counts": {"source_artists": 1},
            }
            self.assertIsNone(_descriptor_binding(root, "expanded", catalog))

            def save() -> None:
                body = canonical_json(manifest)
                (explorer / shard).write_bytes(content)
                (explorer / relative).write_bytes(body)
                inventory = {
                    relative: {"sha256": hashlib.sha256(body).hexdigest(), "bytes": len(body)},
                    shard: binding,
                }
                compressed = zstandard.ZstdCompressor().compress(canonical_json(inventory))
                (explorer / "files-manifest.json.zst").write_bytes(compressed)
                (explorer / "static-receipt.json").write_text(
                    json.dumps(
                        {
                            "corpus_receipt_sha256": hashlib.sha256(metadata).hexdigest(),
                            "files_manifest": {
                                "path": "files-manifest.json.zst",
                                "sha256": hashlib.sha256(compressed).hexdigest(),
                                "bytes": len(compressed),
                            },
                        }
                    )
                )
                catalog["descriptor_map"] = {
                    "manifest": relative,
                    "bytes": len(body) + len(content),
                }

            save()
            result = _descriptor_binding(root, "expanded", catalog)
            assert result is not None
            self.assertEqual(result["href"], "expanded/explorer/index.html#descriptor-map")
            (explorer / shard).write_bytes(b"[]")
            with self.assertRaisesRegex(ValueError, "exported bytes"):
                _descriptor_binding(root, "expanded", catalog)
            save()
            (explorer / "corpus-receipt.json").write_bytes(b'{"tampered":true}')
            manifest["metadata_receipt_sha256"] = hashlib.sha256(
                (explorer / "corpus-receipt.json").read_bytes()
            ).hexdigest()
            save()
            with self.assertRaisesRegex(ValueError, "native scope"):
                _descriptor_binding(root, "expanded", catalog)
            (explorer / "corpus-receipt.json").write_bytes(metadata)
            manifest["metadata_receipt_sha256"] = "a" * 64
            save()
            with self.assertRaisesRegex(ValueError, "native scope"):
                _descriptor_binding(root, "expanded", catalog)
            manifest["metadata_receipt_sha256"] = hashlib.sha256(metadata).hexdigest()
            manifest["genres"] = [{"id": 2, "position": None}]
            save()
            with self.assertRaisesRegex(ValueError, "native scope"):
                _descriptor_binding(root, "expanded", catalog)
            catalog["descriptor_map"]["manifest"] = "../manifest.json"
            with self.assertRaisesRegex(ValueError, "navigation path"):
                _descriptor_binding(root, "expanded", catalog)
