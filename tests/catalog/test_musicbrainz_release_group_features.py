"""Native release style replay and group-level evidence independence."""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from typing import override

from opennoise.catalog.musicbrainz_candidate import CandidateCatalogError
from opennoise.catalog.musicbrainz_open_features import _SENTINELS
from opennoise.catalog.musicbrainz_release_group_features import (
    _POLICY,
    _url,
    build_native_release_group_feature_projection,
    iter_native_release_group_feature_rows,
    verify_native_release_group_features,
)
from opennoise.common import canonical_json, sha256_json
from tests.catalog.test_musicbrainz_candidate import _uuid

_ROOT = Path(__file__).resolve().parents[2]


class NativeReleaseGroupFeaturesTests(unittest.TestCase):
    @override
    def setUp(self) -> None:
        cache = _ROOT / ".cache" / "test-tmp"
        cache.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=cache)
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        (self.directory / "pages").mkdir()
        self.group = {
            "id": _uuid(10),
            "title": "Native Group",
            "first-release-date": "1995",
            "primary-type": "Album",
            "secondary-types": [],
            "artist-credit": [
                {
                    "artist": {"id": identity, "name": f"Artist {index}"},
                    "name": f"Artist {index}",
                    "joinphrase": " & ",
                }
                for index, identity in enumerate(_SENTINELS)
            ],
            "genres": [{"id": _uuid(20), "name": "native microstyle", "count": 5}],
            "tags": [{"name": "space age pop", "count": 3}],
        }
        documents: list[dict[str, object]] = []
        for artist in _SENTINELS:
            raw = canonical_json(
                {
                    "release-group-count": 1,
                    "release-group-offset": 0,
                    "release-groups": [self.group],
                }
            )
            path = self.directory / "pages" / f"{artist}-000.json"
            binding: dict[str, object] = {
                "artist_mbid": artist,
                "offset": 0,
                "request_url": _url(artist, 0),
                "path": f"pages/{path.name}",
                "http_status": 200,
                "response_sha256": hashlib.sha256(raw).hexdigest(),
                "byte_size": len(raw),
                "observed_at": "2026-09-30T00:00:00+00:00",
            }
            path.write_bytes(raw)
            path.with_suffix(".receipt.json").write_bytes(canonical_json(binding))
            documents.append(binding)
        license_raw = b"CC0 Attribution-NonCommercial-ShareAlike 3.0"
        (self.directory / "source-license.html").write_bytes(license_raw)
        self.source: dict[str, object] = {
            **_POLICY,
            "documents": documents,
            "license_page_sha256": hashlib.sha256(license_raw).hexdigest(),
        }
        self._source()

    def _source(self) -> None:
        (self.directory / "source.json").write_bytes(canonical_json(self.source))

    def test_one_group_is_not_multiplied_across_credits_or_source_queries(self) -> None:
        receipt = build_native_release_group_feature_projection(directory=self.directory)
        self.assertEqual(receipt["release_group_count"], 1)
        self.assertEqual(receipt["positive_genre_observation_count"], 1)
        self.assertEqual(receipt["positive_tag_observation_count"], 1)
        row = next(iter_native_release_group_feature_rows(directory=self.directory))
        self.assertEqual(row["artist_mbids"], list(_SENTINELS))
        self.assertEqual(row["evidence_group_ids"], [f"release_group:{_uuid(10)}"])
        refs = row["evidence_refs"]
        assert isinstance(refs, list)
        self.assertIn(f"release-group/{_uuid(10)}", refs)
        sources = row["sources"]
        assert isinstance(sources, list)
        self.assertEqual(len(sources), 10)
        self.assertEqual(
            row["genres"],
            [{"id": _uuid(20), "name": "native microstyle", "count": 5, "disambiguation": ""}],
        )
        self.assertFalse(receipt["artist_membership_inferred_from_context"])
        self.assertFalse(receipt["fixed_seed_vocabulary_used"])
        self.assertEqual(receipt, verify_native_release_group_features(directory=self.directory))

    def test_absent_queried_native_credit_is_rejected(self) -> None:
        documents = self.source["documents"]
        assert isinstance(documents, list)
        binding = documents[0]
        path = self.directory / binding["path"]
        raw = json.loads(path.read_bytes())
        raw["release-groups"][0]["artist-credit"] = raw["release-groups"][0]["artist-credit"][1:]
        data = canonical_json(raw)
        path.write_bytes(data)
        binding.update(
            {"response_sha256": hashlib.sha256(data).hexdigest(), "byte_size": len(data)}
        )
        path.with_suffix(".receipt.json").write_bytes(canonical_json(binding))
        self._source()
        with self.assertRaisesRegex(CandidateCatalogError, "exact queried artist"):
            list(iter_native_release_group_feature_rows(directory=self.directory))

    def test_complete_sentinel_source_and_page_count_are_required(self) -> None:
        documents = self.source["documents"]
        assert isinstance(documents, list)
        documents.pop()
        self._source()
        with self.assertRaisesRegex(CandidateCatalogError, "omits a sentinel"):
            list(iter_native_release_group_feature_rows(directory=self.directory))

    def test_group_fact_conflicts_across_native_queries_abstain(self) -> None:
        documents = self.source["documents"]
        assert isinstance(documents, list)
        binding = documents[0]
        path = self.directory / binding["path"]
        raw = json.loads(path.read_bytes())
        raw["release-groups"][0]["genres"][0]["count"] = 99
        data = canonical_json(raw)
        path.write_bytes(data)
        binding.update(
            {"response_sha256": hashlib.sha256(data).hexdigest(), "byte_size": len(data)}
        )
        path.with_suffix(".receipt.json").write_bytes(canonical_json(binding))
        self._source()
        with self.assertRaisesRegex(CandidateCatalogError, "conflicting source facts"):
            list(iter_native_release_group_feature_rows(directory=self.directory))

    def test_fabricated_release_evidence_group_or_policy_cannot_pass_replay(self) -> None:
        build_native_release_group_feature_projection(directory=self.directory)
        rows_path = self.directory / "release-features.jsonl"
        original = rows_path.read_bytes()
        row = json.loads(original)
        row["evidence_group_ids"] = [f"artist:{_SENTINELS[0]}"]
        rows_path.write_bytes(canonical_json(row) + b"\n")
        with self.assertRaisesRegex(CandidateCatalogError, "exact source bytes"):
            verify_native_release_group_features(directory=self.directory)
        rows_path.write_bytes(original)
        receipt_path = self.directory / "receipt.json"
        receipt = json.loads(receipt_path.read_bytes())
        receipt["artist_membership_inferred_from_context"] = True
        receipt["output_sha256"] = sha256_json(
            {key: value for key, value in receipt.items() if key != "output_sha256"}
        )
        receipt_path.write_bytes(canonical_json(receipt))
        with self.assertRaisesRegex(CandidateCatalogError, "source-role declarations"):
            verify_native_release_group_features(directory=self.directory)

    def test_incomplete_native_page_and_mutated_source_bytes_are_rejected(self) -> None:
        documents = self.source["documents"]
        assert isinstance(documents, list)
        binding = documents[0]
        path = self.directory / binding["path"]
        path.write_bytes(path.read_bytes() + b" ")
        with self.assertRaisesRegex(CandidateCatalogError, "bytes differ"):
            list(iter_native_release_group_feature_rows(directory=self.directory))
        raw = json.loads(path.read_bytes())
        raw["release-group-count"] = 2
        data = canonical_json(raw)
        path.write_bytes(data)
        binding.update(
            {"response_sha256": hashlib.sha256(data).hexdigest(), "byte_size": len(data)}
        )
        path.with_suffix(".receipt.json").write_bytes(canonical_json(binding))
        self._source()
        with self.assertRaisesRegex(CandidateCatalogError, "incomplete"):
            list(iter_native_release_group_feature_rows(directory=self.directory))
