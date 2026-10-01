"""Native artist facts remain independent from release genres and identity redirects."""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from typing import override

from opennoise.catalog.musicbrainz_candidate import CandidateCatalogError
from opennoise.catalog.musicbrainz_native_artist_features import (
    _POLICY,
    _url,
    build_native_artist_feature_projection,
    iter_native_artist_feature_rows,
    verify_native_artist_features,
)
from opennoise.common import canonical_json, sha256_json
from tests.catalog.test_musicbrainz_candidate import _uuid

_ROOT = Path(__file__).resolve().parents[2]


class NativeArtistFeaturesTests(unittest.TestCase):
    @override
    def setUp(self) -> None:
        cache = _ROOT / ".cache" / "test-tmp"
        cache.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=cache)
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        (self.directory / "pages").mkdir()
        self.raw: dict[str, object] = {
            "id": _uuid(1),
            "name": "Native Artist",
            "sort-name": "Artist, Native",
            "genres": [{"id": _uuid(20), "name": "native artist style", "count": 2}],
            "tags": [{"name": "lo-fi", "count": 3}, {"name": "lo fi", "count": 7}],
        }
        self.binding: dict[str, object] = {
            "artist_mbid": _uuid(1),
            "path": f"pages/{_uuid(1)}.json",
            "request_url": _url(_uuid(1)),
            "http_status": 200,
            "redirect_location": None,
            "observed_at": "2026-09-30T00:00:00+00:00",
        }
        license_raw = b"CC0 Attribution-NonCommercial-ShareAlike 3.0"
        (self.directory / "source-license.html").write_bytes(license_raw)
        self.source = {
            **_POLICY,
            "artist_ids": [_uuid(1)],
            "documents": [self.binding],
            "license_page_sha256": hashlib.sha256(license_raw).hexdigest(),
        }
        self._write()

    def _write(self) -> None:
        raw = canonical_json(self.raw)
        self.binding.update(
            {"response_sha256": hashlib.sha256(raw).hexdigest(), "byte_size": len(raw)}
        )
        path = self.directory / "pages" / f"{_uuid(1)}.json"
        path.write_bytes(raw)
        path.with_suffix(".receipt.json").write_bytes(canonical_json(self.binding))
        (self.directory / "source.json").write_bytes(canonical_json(self.source))

    def test_native_genres_and_vote_labels_are_independently_preserved(self) -> None:
        receipt = build_native_artist_feature_projection(directory=self.directory)
        self.assertEqual(receipt["artist_count"], 1)
        self.assertEqual(receipt["positive_artist_genre_observation_count"], 1)
        self.assertEqual(receipt["positive_artist_tag_observation_count"], 2)
        self.assertFalse(receipt["artist_genres_inferred_from_release_genres"])
        row = next(iter_native_artist_feature_rows(directory=self.directory))
        self.assertEqual(
            row["genres"],
            [{"id": _uuid(20), "name": "native artist style", "count": 2, "disambiguation": ""}],
        )
        self.assertEqual(
            row["tags"], [{"name": "lo-fi", "count": 3}, {"name": "lo fi", "count": 7}]
        )
        self.assertEqual(row["native_artist_genres_status"], "observed_native_artist_record")
        self.assertEqual(receipt, verify_native_artist_features(directory=self.directory))

    def test_foreign_canonical_identity_is_never_substituted(self) -> None:
        self.raw["id"] = _uuid(2)
        self._write()
        with self.assertRaisesRegex(CandidateCatalogError, "different UUID"):
            list(iter_native_artist_feature_rows(directory=self.directory))

    def test_redirect_and_not_found_remain_explicit_abstentions(self) -> None:
        self.raw["id"] = _uuid(2)
        self.binding["http_status"] = 301
        self.binding["redirect_location"] = _url(_uuid(2))
        self._write()
        receipt = build_native_artist_feature_projection(directory=self.directory)
        self.assertEqual(receipt["artist_count"], 0)
        self.assertEqual(receipt["missing_or_redirected_artist_count"], 1)
        self.assertEqual(receipt["resolved_artist_names"], {})

    def test_complete_receipt_and_exact_request_are_replayed(self) -> None:
        self.binding["request_url"] = "https://other.example/artist"
        self._write()
        with self.assertRaisesRegex(CandidateCatalogError, "exact request"):
            list(iter_native_artist_feature_rows(directory=self.directory))

    def test_rehashed_native_genre_or_policy_fabrication_fails(self) -> None:
        build_native_artist_feature_projection(directory=self.directory)
        rows = self.directory / "artist-features.jsonl"
        original = rows.read_bytes()
        row = json.loads(original)
        row["genres"].append({"id": _uuid(30), "name": "borrowed release genre", "count": 1})
        rows.write_bytes(canonical_json(row) + b"\n")
        with self.assertRaisesRegex(CandidateCatalogError, "independent source bytes"):
            verify_native_artist_features(directory=self.directory)
        rows.write_bytes(original)
        path = self.directory / "receipt.json"
        receipt = json.loads(path.read_bytes())
        receipt["artist_genres_inferred_from_release_genres"] = True
        receipt["output_sha256"] = sha256_json(
            {k: v for k, v in receipt.items() if k != "output_sha256"}
        )
        path.write_bytes(canonical_json(receipt))
        with self.assertRaisesRegex(CandidateCatalogError, "source role differs"):
            verify_native_artist_features(directory=self.directory)

    def test_source_byte_mutation_and_invalid_native_vote_are_rejected(self) -> None:
        path = self.directory / "pages" / f"{_uuid(1)}.json"
        path.write_bytes(path.read_bytes() + b" ")
        with self.assertRaisesRegex(CandidateCatalogError, "source bytes differ"):
            list(iter_native_artist_feature_rows(directory=self.directory))
        self.raw["tags"] = [{"name": "wrong vote", "count": True}]
        self._write()
        with self.assertRaisesRegex(CandidateCatalogError, "integer vote"):
            list(iter_native_artist_feature_rows(directory=self.directory))
