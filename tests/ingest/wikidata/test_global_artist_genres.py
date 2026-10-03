from __future__ import annotations

import hashlib
import json
import re
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
import zstandard

import opennoise.ingest.wikidata.global_artist_genres as global_genres
from opennoise.ingest.wikidata.global_artist_genres import (
    INITIAL_QUERY,
    GlobalArtistGenreError,
    _core_names_for,
    _identity_status,
    _mbid,
    _parse_scan,
    _qid,
    _replace_json,
    _scan_groups,
    _sha256_bytes,
    _verify_core_source,
    _write_receipt,
    acquire_global_artist_genres,
    verify_global_artist_genres,
)

MBID = "f22942a1-6f70-4f48-866e-238cb2308fbd"
MBID_OTHER = "00000000-0000-4000-8000-000000000001"


def binding(qid: str, artist_id: str, genre: str) -> dict[str, object]:
    return {
        "artist": {"value": f"http://www.wikidata.org/entity/{qid}"},
        "mbid": {"value": artist_id},
        "genre": {"value": f"http://www.wikidata.org/entity/{genre}"},
    }


class GlobalArtistGenresTests(unittest.TestCase):
    def test_source_query_is_the_pinned_global_artist_cohort(self) -> None:
        self.assertIn("?genre wdt:P31 wd:Q188451 .", INITIAL_QUERY)
        self.assertIn("?artist wdt:P434 ?mbid; wdt:P136 ?genre .", INITIAL_QUERY)
        self.assertIn("LIMIT 20001", INITIAL_QUERY)

    def test_scan_requires_canonical_qids_and_uuid(self) -> None:
        rows, quarantined = _parse_scan(
            json.dumps({"results": {"bindings": [binding("Q42", MBID, "Q188451")]}}).encode()
        )
        self.assertEqual(rows, [("Q42", MBID, "Q188451")])
        self.assertEqual(quarantined, [])
        rows, quarantined = _parse_scan(
            json.dumps(
                {
                    "results": {
                        "bindings": [
                            binding("Q42", MBID, "Q188451"),
                            binding("Q43", "musicbrainz.org/artist/not-a-uuid", "Q188451"),
                        ]
                    }
                }
            ).encode()
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(quarantined[0]["row_index"], 1)
        with self.assertRaises(GlobalArtistGenreError):
            _qid("https://www.wikidata.org/wiki/Q42")
        with self.assertRaises(GlobalArtistGenreError):
            _qid("ftp://www.wikidata.org/entity/Q42")
        with self.assertRaises(GlobalArtistGenreError):
            _qid("https://www.wikidata.org/entity/Q42?redirect=Q43")
        with self.assertRaises(GlobalArtistGenreError):
            _mbid(MBID.upper())

    def test_exact_p434_qid_reuse_is_quarantined(self) -> None:
        other = "00000000-0000-4000-8000-000000000001"
        _, _, mbids_by_qid = _scan_groups(
            [("Q42", MBID, "Q5"), ("Q42", other, "Q6")]
        )
        self.assertEqual(
            _identity_status(
                MBID,
                {"Q42"},
                mbids_by_qid,
                {"english_labels": {"Example"}, "types": {"Q5": "human"}},
                "Example",
            )[0],
            "p434_qid_reused_for_multiple_mbids",
        )

    def test_name_normalization_only_confirms_candidate_coherence(self) -> None:
        _, _, mbids_by_qid = _scan_groups([("Q42", MBID, "Q5")])
        status, _ = _identity_status(
            MBID,
            {"Q42"},
            mbids_by_qid,
            {"english_labels": {"Ａrtist"}, "types": {"Q5": "human"}},
            "Artist",
        )
        self.assertEqual(status, "resolved_exact_p434_core_name")
        status, _ = _identity_status(
            MBID,
            {"Q42"},
            mbids_by_qid,
            {"english_labels": {"Other"}, "types": {"Q5": "human"}},
            "Artist",
        )
        self.assertEqual(status, "core_name_mismatch")


class GlobalArtistGenrePackTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.core = self.root / "core"
        self.pack = self.root / "pack"
        self._make_core()
        self._make_pack()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _make_core(self) -> None:
        self.core.mkdir()
        rows = [
            {"artist_mbid": MBID, "name": "Twin"},
            {"artist_mbid": MBID_OTHER, "name": "Singer"},
        ]
        raw = b"".join(json.dumps(row).encode() + b"\n" for row in rows)
        compressed = zstandard.ZstdCompressor().compress(raw)
        (self.core / "artist-identities.jsonl.zst").write_bytes(compressed)
        receipt = {
            "revision": "musicbrainz-core-artist-identities-v1",
            "license": "CC0-1.0",
            "verified_complete": True,
            "fields": ["artist_mbid", "name"],
            "genre_memberships": "absent; identities are not genre evidence",
            "derived_tables_consumed": [],
            "output_file": "artist-identities.jsonl.zst",
            "source_archive_sha256_verified": False,
            "snapshot": "fixture-v1",
            "artist_count": len(rows),
            "output_bytes": len(compressed),
            "output_sha256": hashlib.sha256(compressed).hexdigest(),
        }
        (self.core / "receipt.json").write_text(json.dumps(receipt), encoding="utf-8")

    def _make_pack(self) -> None:
        scans = [
            binding("Q42", MBID, "Q188451"),
            binding("Q43", MBID, "Q188451"),
            binding("Q44", MBID_OTHER, "Q188451"),
        ]
        original_client = httpx.Client

        def respond(request: httpx.Request) -> httpx.Response:
            query = request.url.params["query"]
            if "SELECT ?artist ?mbid ?genre" in query:
                result = {"results": {"bindings": scans}}
            elif "SELECT ?artist ?mbid ?label ?type ?typeLabel" in query:
                requested = re.findall(r'\(wd:(Q[0-9]+) "([0-9a-f-]+)"\)', query)
                result = {
                    "results": {
                        "bindings": [
                            {
                                "artist": {"value": f"http://www.wikidata.org/entity/{qid}"},
                                "mbid": {"value": artist_id},
                                "label": {"xml:lang": "en", "value": "Singer"},
                                "type": {"value": "http://www.wikidata.org/entity/Q5"},
                                "typeLabel": {"xml:lang": "en", "value": "human"},
                            }
                            for qid, artist_id in requested
                        ]
                    }
                }
            elif "SELECT ?genre ?label" in query:
                result = {
                    "results": {
                        "bindings": [
                            {
                                "genre": {"value": "http://www.wikidata.org/entity/Q188451"},
                                "label": {"xml:lang": "en", "value": "musical genre"},
                            }
                        ]
                    }
                }
            else:
                raise AssertionError("unexpected Wikidata query")
            return httpx.Response(200, json=result)

        def client_factory(*args: object, **kwargs: object) -> httpx.Client:
            return original_client(*args, transport=httpx.MockTransport(respond), **kwargs)

        with (
            patch.object(global_genres.httpx, "Client", side_effect=client_factory),
            patch("time.sleep"),
        ):
            acquire_global_artist_genres(self.pack, self.core, max_artists=2)

    def _copy_pack(self, name: str) -> Path:
        target = self.root / name
        shutil.copytree(self.pack, target)
        return target

    def test_replay_quarantines_multiple_p434_qids_and_closes_denominator(self) -> None:
        manifest = verify_global_artist_genres(self.pack, self.core)
        self.assertEqual(manifest["request_count"], 3)
        self.assertEqual(sum(manifest["identity_status_counts"].values()), 2)
        projection = json.loads((self.pack / "projection.json").read_bytes())
        duplicated = next(row for row in projection["artists"] if row["artist_mbid"] == MBID)
        self.assertEqual(duplicated["identity_status"], "duplicate_p434_qids")
        self.assertEqual(duplicated["claims"], [])

    def test_replay_rejects_closed_file_set_and_rehashed_projection_tampering(self) -> None:
        closed = self._copy_pack("closed")
        (closed / "extra.json").write_text("{}", encoding="utf-8")
        with self.assertRaisesRegex(GlobalArtistGenreError, "file set differs"):
            verify_global_artist_genres(closed, self.core)

        changed = self._copy_pack("projection-tamper")
        projection = json.loads((changed / "projection.json").read_bytes())
        projection["artists"][0]["claims"] = [{"forged": True}]
        _replace_json(changed / "projection.json", projection)
        _write_receipt(changed)
        with self.assertRaisesRegex(GlobalArtistGenreError, "does not replay"):
            verify_global_artist_genres(changed, self.core)

    def test_replay_rejects_forged_foreign_qid_uuid_pair(self) -> None:
        forged = self._copy_pack("forged-pair")
        manifest = json.loads((forged / "manifest.json").read_bytes())
        capture = next(
            item for item in manifest["followup_captures"] if item["kind"] == "artist-detail"
        )
        path = forged / capture["raw_path"]
        payload = json.loads(path.read_bytes())
        payload["results"]["bindings"].append(
            {
                "artist": {"value": "http://www.wikidata.org/entity/Q999999"},
                "mbid": {"value": MBID_OTHER},
            }
        )
        body = json.dumps(payload).encode()
        path.write_bytes(body)
        capture["response_bytes"] = len(body)
        capture["response_sha256"] = _sha256_bytes(body)
        _replace_json(forged / "manifest.json", manifest)
        _write_receipt(forged)
        with self.assertRaisesRegex(GlobalArtistGenreError, "unrequested QID/MBID"):
            verify_global_artist_genres(forged, self.core)

    def test_core_replay_checks_hash_count_and_malformed_compression(self) -> None:
        compressed_path = self.core / "artist-identities.jsonl.zst"
        original = compressed_path.read_bytes()
        receipt_path = self.core / "receipt.json"
        receipt = json.loads(receipt_path.read_bytes())
        compressed_path.write_bytes(original + b"tamper")
        with self.assertRaisesRegex(GlobalArtistGenreError, "hash or byte count"):
            _verify_core_source(self.core)

        compressed_path.write_bytes(original)
        _verify_core_source(self.core)
        with self.assertRaisesRegex(GlobalArtistGenreError, "row count"):
            _core_names_for({MBID}, compressed_path, receipt["artist_count"] + 1)

        malformed = b"not a zstandard stream"
        compressed_path.write_bytes(malformed)
        receipt["output_bytes"] = len(malformed)
        receipt["output_sha256"] = hashlib.sha256(malformed).hexdigest()
        receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
        with self.assertRaisesRegex(GlobalArtistGenreError, "cannot be streamed"):
            _core_names_for({MBID}, compressed_path, receipt["artist_count"])
