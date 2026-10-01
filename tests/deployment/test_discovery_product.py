"""Local composition custody, navigation, and immutable-parent boundaries."""

import tempfile
import unittest
from pathlib import Path
from typing import Any, override

from opennoise.catalog.musicbrainz_candidate import CandidateCatalogError
from opennoise.common import canonical_json, sha256_file, sha256_json
from opennoise.deployment.community_preview import verified_receipt
from opennoise.deployment.discovery_product import build_discovery_product

_CACHE = Path(__file__).resolve().parents[2] / ".cache"


def _seal(directory: Path, name: str, revision: str) -> dict[str, Any]:
    receipt = {
        "revision": revision,
        "scope": "local_research_only",
        "public_export_authorized": False,
        "serving_authorized": False,
        "native_genre_memberships_added": 0,
        "features_sha256": "a" * 64,
        "feature_receipt_sha256": "b" * 64,
        "source_preview_output_sha256": "c" * 64,
        "source_licenses": {"core": "CC0-1.0", "tags": "CC-BY-NC-SA-3.0"},
        "derived_output_obligations": "Local research only",
        "coverage": {"artists": 2},
        "files": {
            path.relative_to(directory).as_posix(): {
                "sha256": sha256_file(path)[0],
                "bytes": path.stat().st_size,
            }
            for path in directory.rglob("*")
            if path.is_file() and path.name != name
        },
    }
    receipt["output_sha256"] = sha256_json(receipt)
    (directory / name).write_bytes(canonical_json(receipt) + b"\n")
    return receipt


def _reseal(directory: Path, name: str, receipt: dict[str, Any]) -> None:
    receipt.pop("output_sha256")
    receipt["output_sha256"] = sha256_json(receipt)
    (directory / name).write_bytes(canonical_json(receipt) + b"\n")


class DiscoveryProductTests(unittest.TestCase):
    @override
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(dir=_CACHE)
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.atlas = self.root / "atlas"
        self.communities = self.root / "community"
        self.output = self.root / "product"
        for directory in (self.atlas, self.communities):
            directory.mkdir()
            (directory / "app.js").write_text("// unchanged\n", encoding="utf-8")
            (directory / "data.json").write_text('{"artists":["one","two"]}\n', encoding="utf-8")
        self.atlas_html = (
            '<html><head></head><header>Atlas</header><script src="app.js"></script>'
            '<footer><a href="receipt.json">Receipt</a></footer></html>'
        )
        (self.atlas / "index.html").write_text(self.atlas_html, encoding="utf-8")
        (self.communities / "index.html").write_text(
            "<html><head></head><header>Communities"
            '<a href="source-explorer.html">Source</a></header>'
            '<script src="app.js"></script><a href="community-preview-receipt.json">Receipt</a>'
            "</html>",
            encoding="utf-8",
        )
        (self.communities / "source-explorer.html").write_text(
            "<html><head></head><header>Source</header>"
            '<a href="preview-receipt.json">Receipt</a></html>',
            encoding="utf-8",
        )
        self.atlas_receipt = _seal(self.atlas, "receipt.json", "named-source-style-atlas-v1")
        self.community_receipt = _seal(
            self.communities,
            "community-preview-receipt.json",
            "emergent-community-local-preview-v1",
        )

    def _build(self) -> dict[str, Any]:
        return build_discovery_product(
            atlas=self.atlas, communities=self.communities, output=self.output
        )

    def test_navigation_is_bound_and_parent_data_and_inodes_are_preserved(self) -> None:
        receipt = self._build()
        self.assertEqual(verified_receipt(self.output, "receipt.json"), receipt)
        self.assertEqual(verified_receipt(self.atlas, "receipt.json"), self.atlas_receipt)
        self.assertEqual(
            verified_receipt(self.communities, "community-preview-receipt.json"),
            self.community_receipt,
        )
        self.assertEqual((self.atlas / "index.html").read_text(), self.atlas_html)
        self.assertNotEqual(
            (self.atlas / "index.html").stat().st_ino,
            (self.output / "index.html").stat().st_ino,
        )
        for original, destination in (
            (self.atlas / "data.json", self.output / "data.json"),
            (self.communities / "data.json", self.output / "communities/data.json"),
        ):
            self.assertEqual(original.stat().st_ino, destination.stat().st_ino)
            self.assertEqual(original.read_bytes(), destination.read_bytes())
        self.assertEqual(len(receipt["navigation_changed_files"]), 3)
        self.assertEqual(receipt["unchanged_parent_artifact_count"], 4)
        root_html = (self.output / "index.html").read_text()
        self.assertIn('<link rel="icon" href="data:,">', root_html)
        self.assertIn('href="communities/index.html"', root_html)
        self.assertIn('href="communities/source-explorer.html"', root_html)
        for name in ("index.html", "source-explorer.html"):
            html = (self.output / "communities" / name).read_text()
            self.assertIn('<link rel="icon" href="data:,">', html)
            self.assertIn('href="../index.html"', html)
            self.assertIn('href="../receipt.json"', html)
        self.assertEqual(
            receipt["parents"]["atlas"]["output_sha256"], self.atlas_receipt["output_sha256"]
        )
        self.assertFalse(receipt["public_export_authorized"])
        self.assertFalse(receipt["serving_authorized"])
        self.assertEqual(receipt["native_genre_memberships_added"], 0)

    def test_artifact_tampering_is_rejected_before_output_creation(self) -> None:
        (self.communities / "data.json").write_text("tampered", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "byte binding mismatch"):
            self._build()
        self.assertFalse(self.output.exists())

    def test_receipt_self_identity_tampering_is_rejected(self) -> None:
        self.atlas_receipt["scope"] = "public"
        (self.atlas / "receipt.json").write_bytes(canonical_json(self.atlas_receipt))
        with self.assertRaisesRegex(ValueError, "identity mismatch"):
            self._build()
        self.assertFalse(self.output.exists())

    def test_lineage_mismatches_are_rejected(self) -> None:
        for key in ("features_sha256", "feature_receipt_sha256", "source_preview_output_sha256"):
            with self.subTest(key=key):
                original = self.community_receipt[key]
                self.community_receipt[key] = "d" * 64
                _reseal(self.communities, "community-preview-receipt.json", self.community_receipt)
                with self.assertRaisesRegex(ValueError, key):
                    self._build()
                self.assertFalse(self.output.exists())
                self.community_receipt[key] = original
                _reseal(self.communities, "community-preview-receipt.json", self.community_receipt)

    def test_unsafe_parent_boundaries_are_rejected(self) -> None:
        for key, value in (
            ("scope", "public"),
            ("public_export_authorized", True),
            ("serving_authorized", True),
            ("native_genre_memberships_added", 1),
        ):
            with self.subTest(key=key):
                original = self.community_receipt[key]
                self.community_receipt[key] = value
                _reseal(self.communities, "community-preview-receipt.json", self.community_receipt)
                with self.assertRaisesRegex(ValueError, "boundary"):
                    self._build()
                self.assertFalse(self.output.exists())
                self.community_receipt[key] = original
                _reseal(self.communities, "community-preview-receipt.json", self.community_receipt)

    def test_conflicting_enrichment_identities_are_rejected(self) -> None:
        self.atlas_receipt["prediction_output_sha256"] = "d" * 64
        self.community_receipt["enrichment_prediction_output_sha256"] = "e" * 64
        _reseal(self.atlas, "receipt.json", self.atlas_receipt)
        _reseal(self.communities, "community-preview-receipt.json", self.community_receipt)
        with self.assertRaisesRegex(ValueError, "enrichment prediction identities differ"):
            self._build()
        self.assertFalse(self.output.exists())

    def test_bound_path_escape_is_rejected(self) -> None:
        self.atlas_receipt["files"]["../outside"] = {"sha256": "d" * 64, "bytes": 0}
        _reseal(self.atlas, "receipt.json", self.atlas_receipt)
        with self.assertRaisesRegex(ValueError, "escapes"):
            self._build()
        self.assertFalse(self.output.exists())

    def test_dead_html_reference_is_rejected(self) -> None:
        (self.atlas / "index.html").write_text(
            self.atlas_html.replace("</footer>", '<a href="missing.html">Missing</a></footer>'),
            encoding="utf-8",
        )
        _seal(self.atlas, "receipt.json", "named-source-style-atlas-v1")
        with self.assertRaisesRegex(ValueError, "no bound product target"):
            self._build()

    def test_existing_output_is_refused_before_reading_missing_inputs(self) -> None:
        self.output.mkdir()
        with self.assertRaises(FileExistsError):
            build_discovery_product(
                atlas=self.root / "missing", communities=self.root / "missing", output=self.output
            )

    def test_output_outside_cache_is_rejected(self) -> None:
        with self.assertRaises(CandidateCatalogError):
            build_discovery_product(
                atlas=self.atlas,
                communities=self.communities,
                output=_CACHE.parent / "dist-discovery-test",
            )
