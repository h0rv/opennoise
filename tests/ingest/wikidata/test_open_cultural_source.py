from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import httpx

from opennoise.ingest.open_cultural_source import (
    ENDPOINT,
    build_query,
    fetch_artist_context,
    parse_bindings,
)
from scripts.probe_open_cultural_sources import (
    _replay_batch,
    _replay_responses,
    _safe_pack_path,
    _validate_replay_accounting,
    make_portable_manifest,
)

MBID = "f22942a1-6f70-4f48-866e-238cb2308fbd"


def uri(value: str) -> dict[str, str]:
    """Create a test Wikidata entity binding."""
    return {"type": "uri", "value": f"http://www.wikidata.org/entity/{value}"}


class OpenCulturalSourceTests(unittest.TestCase):
    def test_query_is_exact_bounded_and_deterministic(self) -> None:
        query = build_query((MBID,))
        self.assertIn(f'VALUES ?mbid {{ "{MBID}" }}', query)
        self.assertIn("LIMIT 1000", query)
        self.assertIn("wdt:P740", query)
        self.assertEqual(query, build_query((MBID,)))

    def test_rejects_invalid_or_oversized_input(self) -> None:
        with self.assertRaises(ValueError):
            build_query(("Aphex Twin",))
        with self.assertRaises(ValueError):
            build_query(tuple(f"00000000-0000-4000-8000-{number:012d}" for number in range(51)))

    def test_claims_keep_context_properties_separate_and_deduplicate(self) -> None:
        binding = {
            "mbid": {"type": "literal", "value": MBID},
            "artist": uri("Q9043"),
            "label": {"type": "literal", "xml:lang": "en", "value": "Aphex Twin"},
            "property": {"type": "uri", "value": "http://www.wikidata.org/prop/direct/P495"},
            "value": uri("Q145"),
            "valueLabel": {"type": "literal", "xml:lang": "en", "value": "United Kingdom"},
        }
        result = parse_bindings({"results": {"bindings": [binding, binding]}}, {MBID})
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].label, "Aphex Twin")
        self.assertEqual(len(result[0].claims), 1)
        self.assertEqual(result[0].claims[0].property_id, "P495")
        self.assertEqual(result[0].claims[0].value_qid, "Q145")
        self.assertEqual(result[0].claims[0].value_label, "United Kingdom")
        self.assertEqual(result[0].claims[0].license, "CC0")

    def test_fetch_uses_one_get_and_accepts_small_sparql_response(self) -> None:
        calls = []
        body = b'{"results":{"bindings":[]}}'

        def respond(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            return httpx.Response(200, content=body)

        with httpx.Client(transport=httpx.MockTransport(respond)) as client:
            result = fetch_artist_context((MBID,), client=client)
        self.assertEqual(result, ())
        self.assertEqual(len(calls), 1)
        self.assertEqual(str(calls[0].url.copy_with(query=None)), ENDPOINT)
        self.assertEqual(calls[0].method, "GET")
        self.assertIn(MBID, calls[0].url.params["query"])

    def test_fetch_stops_at_two_megabyte_response_limit(self) -> None:
        def respond(_: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=b" " * 2_000_001)

        with (
            httpx.Client(transport=httpx.MockTransport(respond)) as client,
            self.assertRaisesRegex(ValueError, "2 MB cap"),
        ):
            fetch_artist_context((MBID,), client=client)

    def test_portable_manifest_removes_noncommercial_cohort_claim_values(self) -> None:
        source = {
            "revision": "local-v2",
            "cohort": [
                {
                    "artist_mbid": MBID,
                    "name": "Aphex Twin",
                    "role": "stratified_source_artist",
                    "selection_stratum": "ambient",
                    "source_genres": ["ambient", "electronic music"],
                }
            ],
            "selection": {
                "artist_features_sha256": "features-hash",
                "selection": "stable exact-MBID genre-stratified sample",
                "selection_strata": ["ambient", "house"],
            },
            "batches": [{"requested_mbids": [MBID]}],
        }
        portable = make_portable_manifest(source, "source-manifest-hash", [])
        self.assertEqual(
            portable["cohort"],
            [{"artist_mbid": MBID, "name": "Aphex Twin", "role": "stratified_source_artist"}],
        )
        self.assertNotIn("selection_strata", portable["selection"])
        self.assertEqual(portable["selection"]["selection_strata_count"], 2)
        self.assertEqual(portable["selection"]["artist_features_sha256"], "features-hash")
        self.assertEqual(
            portable["portable_derivation"]["source_manifest_sha256"], "source-manifest-hash"
        )
        serialized = json.dumps(portable)
        self.assertNotIn("ambient", serialized)
        self.assertNotIn("electronic music", serialized)
        self.assertEqual(source["cohort"][0]["source_genres"], ["ambient", "electronic music"])

    def test_checked_in_portable_manifest_has_identity_only_cohort(self) -> None:
        path = Path("data/examples/cultural-context/manifest.json")
        manifest = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(len(manifest["cohort"]), 110)
        self.assertTrue(
            all(set(item) == {"artist_mbid", "name", "role"} for item in manifest["cohort"])
        )
        self.assertNotIn("selection_strata", manifest["selection"])
        self.assertEqual(manifest["selection"]["selection_strata_count"], 18)
        self.assertIn("artist_features_sha256", manifest["selection"])
        self.assertEqual(
            manifest["portable_derivation"]["source_manifest_sha256"],
            "0ceb4458cad7eda0b6111ce9cad9825f294af1273b63ea9221025553d56b53eb",
        )

    def test_pack_verifier_rejects_unsafe_raw_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            outside = root.parent / "outside-culture.json"
            outside.write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "safe relative"):
                _safe_pack_path(root, "../outside-culture.json")
            absolute_path = str(root.parent / "outside-culture.json")
            with self.assertRaisesRegex(ValueError, "safe relative"):
                _safe_pack_path(root, absolute_path)
            (root / "alias.json").symlink_to(outside)
            with self.assertRaisesRegex(ValueError, "symlink"):
                _safe_pack_path(root, "alias.json")

    def test_pack_verifier_rejects_duplicate_and_incomplete_ids(self) -> None:
        duplicate_batch = {"requested_mbids": [MBID, MBID]}
        with self.assertRaisesRegex(ValueError, "duplicate requested"):
            _replay_batch(Path(), duplicate_batch)
        with self.assertRaisesRegex(ValueError, "duplicate MusicBrainz"):
            _validate_replay_accounting(
                {"requested_artist_count": 2, "response_bytes_total": 0},
                [MBID, MBID],
                [MBID],
                [],
                0,
            )
        with self.assertRaisesRegex(ValueError, "unmatched artist IDs are incomplete"):
            _validate_replay_accounting(
                {
                    "requested_artist_count": 1,
                    "response_bytes_total": 0,
                    "matched_artist_count": 0,
                    "unmatched_artist_mbids": [],
                },
                [MBID],
                [MBID],
                [],
                0,
            )
        with self.assertRaisesRegex(ValueError, "exact cohort"):
            _validate_replay_accounting(
                {"requested_artist_count": 2, "response_bytes_total": 0},
                [MBID, "00000000-0000-4000-8000-000000000001"],
                [MBID],
                [],
                0,
            )

    def test_replay_requires_raw_batch_to_be_receipt_bound(self) -> None:
        manifest = {
            "cohort": [{"artist_mbid": MBID, "name": "Aphex Twin", "role": "benchmark"}],
            "requested_artist_count": 1,
            "batch_count": 1,
            "request_count": 1,
            "batches": [{"raw_path": "raw/batch-00.json"}],
        }
        with self.assertRaisesRegex(ValueError, "missing from receipt"):
            _replay_responses(Path(), manifest, set())

    def test_rejects_unrequested_ids_and_external_entity_uris(self) -> None:
        base = {
            "mbid": {"type": "literal", "value": MBID},
            "artist": uri("Q9043"),
            "property": {"type": "uri", "value": "http://www.wikidata.org/prop/direct/P136"},
            "value": {"type": "uri", "value": "https://evil.example/entity/Q42"},
        }
        with self.assertRaises(ValueError):
            parse_bindings({"results": {"bindings": [base]}}, set())
        with self.assertRaises(ValueError):
            parse_bindings({"results": {"bindings": [base]}}, {MBID})
