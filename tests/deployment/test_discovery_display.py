"""Display refresh retains source data bytes and never edits linked UI in place."""

import tempfile
import unittest
from pathlib import Path

from opennoise.common import canonical_json, sha256_file, sha256_json
from opennoise.deployment.community_preview import verified_receipt
from opennoise.deployment.discovery_display import refresh_discovery_display

_CACHE = Path(__file__).resolve().parents[2] / ".cache"


class DiscoveryDisplayTests(unittest.TestCase):
    def test_refresh_preserves_data_inode_and_source_ui_and_binds_optional_examples(self) -> None:
        with tempfile.TemporaryDirectory(dir=_CACHE) as temporary:
            root = Path(temporary)
            source, output = root / "source", root / "output"
            source.mkdir()
            assets = (
                "index.html",
                "style-atlas.css",
                "style-atlas.js",
                "data.json",
                "communities/index.html",
                "communities/community-preview.css",
                "communities/community-preview.js",
                "communities/source-explorer.html",
            )
            for relative in assets:
                path = source / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("original source bytes", encoding="utf-8")
            receipt = {
                "revision": "local-discovery-product-v1",
                "scope": "local_research_only",
                "public_export_authorized": False,
                "serving_authorized": False,
                "native_genre_memberships_added": 0,
                "builder_sha256": "a" * 64,
                "files": {
                    relative: {
                        "sha256": sha256_file(source / relative)[0],
                        "bytes": (source / relative).stat().st_size,
                    }
                    for relative in assets
                },
            }
            receipt["output_sha256"] = sha256_json(receipt)
            (source / "receipt.json").write_bytes(canonical_json(receipt) + b"\n")
            link_pack = Path(__file__).resolve().parents[2] / "data/examples/artist-links"
            result = refresh_discovery_display(
                source=source,
                output=output,
                artist_links=link_pack,
                representative_music=Path(__file__).resolve().parents[2]
                / "data/examples/representative-music",
            )
            self.assertEqual(verified_receipt(output, "receipt.json"), result)
            self.assertEqual(verified_receipt(source, "receipt.json"), receipt)
            self.assertEqual(
                (source / "data.json").stat().st_ino, (output / "data.json").stat().st_ino
            )
            self.assertNotEqual(
                (source / "index.html").stat().st_ino, (output / "index.html").stat().st_ino
            )
            self.assertIn(
                'data-artist-examples="representative-music.json"',
                (output / "index.html").read_text(),
            )
            self.assertIn("representative-music.json", result["files"])
            self.assertIn("artist-links.json", result["files"])
            self.assertEqual(
                (output / "artist-links.json").read_bytes(),
                (link_pack / "artist-links.json").read_bytes(),
            )
            self.assertIn(
                'data-artist-links="../artist-links.json"',
                (output / "communities/index.html").read_text(),
            )
            self.assertFalse((output / "provenance/raw").exists())
            with self.assertRaises(FileExistsError):
                refresh_discovery_display(source=source, output=output)
            (source / "data.json").write_text("tampered", encoding="utf-8")
            rejected = root / "rejected"
            with self.assertRaisesRegex(ValueError, "binding mismatch"):
                refresh_discovery_display(source=source, output=rejected)
            self.assertFalse(rejected.exists())
