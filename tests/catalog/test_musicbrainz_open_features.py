"""Native tag preservation, exact source bindings and feature-role replay."""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from typing import override

from opennoise.catalog.musicbrainz_artist_names import _request_url
from opennoise.catalog.musicbrainz_candidate import CandidateCatalogError
from opennoise.catalog.musicbrainz_open_features import (
    _POLICY,
    build_open_artist_feature_projection,
    iter_open_artist_feature_rows,
    verify_open_artist_features,
)
from opennoise.common import canonical_json, sha256_json
from tests.catalog.test_musicbrainz_candidate import _uuid

_ROOT = Path(__file__).resolve().parents[2]


class OpenArtistFeaturesTests(unittest.TestCase):
    @override
    def setUp(self) -> None:
        cache = _ROOT / ".cache" / "test-tmp"
        cache.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=cache)
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        pages = self.directory / "new-pages"
        pages.mkdir()
        raw = canonical_json(
            {
                "count": 1,
                "offset": 0,
                "artists": [
                    {
                        "id": _uuid(1),
                        "name": "Native Artist",
                        "sort-name": "Artist, Native",
                        "tags": [
                            {"name": "lo-fi", "count": 3},
                            {"name": "lo fi", "count": 7},
                            {"name": "not a positive", "count": 0},
                        ],
                        "country": "GB",
                        "area": {"id": _uuid(20), "name": "Cornwall"},
                        "life-span": {"begin": "1971-08-18"},
                    }
                ],
            }
        )
        self.binding = {
            "batch_index": 0,
            "artist_mbids": [_uuid(1)],
            "request_url": _request_url([_uuid(1)]),
            "response_sha256": hashlib.sha256(raw).hexdigest(),
            "byte_size": len(raw),
            "http_status": 200,
            "observed_at": "2026-09-30T00:00:00+00:00",
        }
        (pages / "batch-0000.json").write_bytes(raw)
        (pages / "batch-0000-receipt.json").write_bytes(canonical_json(self.binding))
        license_raw = b"CC0 Attribution-NonCommercial-ShareAlike 3.0"
        (self.directory / "source-license.html").write_bytes(license_raw)
        self.source: dict[str, object] = {
            **_POLICY,
            "catalog_output_sha256": "a" * 64,
            "documents": [{**self.binding, "path": "new-pages/batch-0000.json"}],
            "license_url": "https://musicbrainz.org/doc/About/Data_License",
            "license_page_sha256": hashlib.sha256(license_raw).hexdigest(),
            "new_artist_ids": [_uuid(1)],
        }
        self._source()

    def _source(self) -> None:
        (self.directory / "source.json").write_bytes(canonical_json(self.source))

    def test_native_tag_labels_and_votes_preserve_distinct_observations(self) -> None:
        receipt = build_open_artist_feature_projection(directory=self.directory)
        self.assertEqual(receipt["artist_count"], 1)
        self.assertEqual(receipt["positive_tag_observation_count"], 2)
        self.assertEqual(receipt["distinct_positive_raw_tag_count"], 2)
        self.assertEqual(receipt["artist_life_span_count"], 1)
        rows = list(iter_open_artist_feature_rows(directory=self.directory))
        self.assertEqual(
            rows[0]["tags"],
            [
                {"name": "lo-fi", "count": 3},
                {"name": "lo fi", "count": 7},
                {"name": "not a positive", "count": 0},
            ],
        )
        self.assertEqual(rows[0]["genres"], [])
        self.assertEqual(rows[0]["area"], {"id": _uuid(20), "name": "Cornwall", "type": None})
        self.assertFalse(receipt["fixed_seed_vocabulary_used_for_tag_projection"])
        self.assertEqual(receipt["membership_claims_added"], 0)
        self.assertEqual(receipt, verify_open_artist_features(directory=self.directory))

    def test_different_document_path_cannot_project_an_unqueried_identity(self) -> None:
        foreign = self.directory / "new-pages" / "foreign.json"
        foreign.write_bytes(
            canonical_json(
                {
                    "count": 1,
                    "offset": 0,
                    "artists": [
                        {
                            "id": _uuid(2),
                            "name": "Foreign Artist",
                            "sort-name": "Foreign Artist",
                        }
                    ],
                }
            )
        )
        documents = self.source["documents"]
        assert isinstance(documents, list)
        documents[0].update(
            {
                "path": "new-pages/foreign.json",
                "response_sha256": hashlib.sha256(foreign.read_bytes()).hexdigest(),
                "byte_size": foreign.stat().st_size,
            }
        )
        self._source()
        with self.assertRaisesRegex(CandidateCatalogError, "exact batch"):
            list(iter_open_artist_feature_rows(directory=self.directory))

    def test_document_and_complete_companion_receipt_must_match(self) -> None:
        companion = self.directory / "new-pages" / "batch-0000-receipt.json"
        companion.write_bytes(canonical_json({**self.binding, "observed_at": "different"}))
        with self.assertRaisesRegex(CandidateCatalogError, "complete page receipt"):
            list(iter_open_artist_feature_rows(directory=self.directory))

    def test_raw_page_and_license_mutations_fail_replay(self) -> None:
        build_open_artist_feature_projection(directory=self.directory)
        page = self.directory / "new-pages" / "batch-0000.json"
        original = page.read_bytes()
        page.write_bytes(original + b" ")
        with self.assertRaisesRegex(CandidateCatalogError, "do not replay"):
            verify_open_artist_features(directory=self.directory)
        page.write_bytes(original)
        (self.directory / "source-license.html").write_bytes(b"changed terms")
        with self.assertRaisesRegex(CandidateCatalogError, "license bytes"):
            verify_open_artist_features(directory=self.directory)

    def test_rehashed_fabricated_feature_or_policy_cannot_pass(self) -> None:
        build_open_artist_feature_projection(directory=self.directory)
        rows_path = self.directory / "artist-features.jsonl"
        original = rows_path.read_bytes()
        row = json.loads(original)
        row["tags"].append({"name": "invented microgenre", "count": 100})
        rows_path.write_bytes(canonical_json(row) + b"\n")
        with self.assertRaisesRegex(CandidateCatalogError, "native source bytes"):
            verify_open_artist_features(directory=self.directory)
        rows_path.write_bytes(original)
        receipt_path = self.directory / "receipt.json"
        receipt = json.loads(receipt_path.read_bytes())
        receipt["public_export_authorized"] = True
        receipt["output_sha256"] = sha256_json(
            {k: v for k, v in receipt.items() if k != "output_sha256"}
        )
        receipt_path.write_bytes(canonical_json(receipt))
        with self.assertRaisesRegex(CandidateCatalogError, "source-role declarations"):
            verify_open_artist_features(directory=self.directory)

    def test_native_source_document_symlinks_are_rejected(self) -> None:
        page = self.directory / "new-pages" / "batch-0000.json"
        retained = self.directory / "retained.json"
        page.rename(retained)
        page.symlink_to(retained)
        with self.assertRaisesRegex(CandidateCatalogError, "symlinks"):
            list(iter_open_artist_feature_rows(directory=self.directory))
