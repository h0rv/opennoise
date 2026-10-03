"""Independent taxonomy capture stays bounded, typed and reproducible from raw bytes."""

from __future__ import annotations

import hashlib
import json
import re
import tempfile
import unittest
from pathlib import Path
from typing import Any

import httpx

from opennoise.ingest.wikidata.open_genre_taxonomy import (
    CLASS_QID,
    CLASS_URL,
    ROW_LIMIT,
    SELECTION_LIMIT,
    SELECTION_QUERY,
    capture_pack,
    parse_selection,
    parse_taxonomy,
    project_pack,
    taxonomy_query,
    verify_pack,
)


def _uri(qid: str) -> dict[str, str]:
    return {"type": "uri", "value": f"http://www.wikidata.org/entity/{qid}"}


def _selection(qids: list[str]) -> dict[str, Any]:
    return {
        "results": {"bindings": [{"genre": _uri(qid), "anchor": _uri(CLASS_QID)} for qid in qids]}
    }


def _row(qid: str, prop: str = "P31", target: str = CLASS_QID) -> dict[str, Any]:
    return {
        "genre": _uri(qid),
        "property": {"type": "uri", "value": f"http://www.wikidata.org/prop/direct/{prop}"},
        "value": _uri(target),
    }


def _respond(request: httpx.Request) -> httpx.Response:
    if str(request.url) == CLASS_URL:
        return httpx.Response(
            200,
            json={
                "entities": {
                    CLASS_QID: {
                        "id": CLASS_QID,
                        "labels": {"en": {"language": "en", "value": "music genre"}},
                    }
                }
            },
        )
    if request.url.params["query"] == SELECTION_QUERY:
        return httpx.Response(200, json=_selection(["Q111", "Q112"]))
    first = _row("Q111")
    first["genreLabel"] = {"type": "literal", "xml:lang": "en", "value": "example genre"}
    return httpx.Response(
        200, json={"results": {"bindings": [first, _row("Q111", "P279", "Q112"), _row("Q112")]}}
    )


def _rebind(root: Path, name: str) -> None:
    receipt = json.loads((root / "receipt.json").read_text())
    body = (root / name).read_bytes()
    receipt["files"][name] = {"size_bytes": len(body), "sha256": hashlib.sha256(body).hexdigest()}
    (root / "receipt.json").write_text(json.dumps(receipt), encoding="utf-8")


class OpenGenreTaxonomyTests(unittest.TestCase):
    def test_selection_has_no_names_artist_ids_or_historical_inputs(self) -> None:
        self.assertIn("?genre wdt:P31 ?anchor", SELECTION_QUERY)
        self.assertIn("LIMIT 1000", SELECTION_QUERY)
        self.assertNotIn("ORDER BY", SELECTION_QUERY)
        self.assertNotIn("P434", SELECTION_QUERY)
        query = taxonomy_query(["Q112", "Q111"])
        self.assertIn("VALUES ?genre { wd:Q111 wd:Q112 }", query)
        self.assertIn("LIMIT 2000", query)
        with self.assertRaises(ValueError):
            taxonomy_query(["Aphex Twin"])
        with self.assertRaises(ValueError):
            taxonomy_query(["Q111", "Q111"])

    def test_live_shape_capture_replays_exact_typed_source_and_missing_labels(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "pack"
            calls = []

            def respond(request: httpx.Request) -> httpx.Response:
                calls.append(request)
                return _respond(request)

            with httpx.Client(transport=httpx.MockTransport(respond)) as client:
                projection = capture_pack(root, client=client)
            self.assertEqual(projection, verify_pack(root))
            self.assertEqual(len(calls), 3)
            self.assertEqual(projection["selected_qids"], ["Q111", "Q112"])
            self.assertEqual(projection["missing_english_labels"], ["Q112"])
            self.assertEqual(projection["artist_memberships"], [])
            self.assertEqual(projection["historical_inputs"], [])
            self.assertFalse(projection["full_corpus_claim"])
            self.assertTrue(projection["taxonomy_complete_for_selected_cohort"])
            self.assertEqual(
                {row["property_role"] for row in projection["claims"]},
                {"instance_of", "subclass_of"},
            )
            self.assertTrue(all(row["license"] == "CC0-1.0" for row in projection["claims"]))
            self.assertTrue(
                all(entity["broad_sub_micro_level"] is None for entity in projection["entities"])
            )
            self.assertEqual(projection["entities"][0]["english_label"], "example genre")

    def test_endpoint_failure_is_preserved_without_taxonomy_or_memberships(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "pack"
            with httpx.Client(
                transport=httpx.MockTransport(
                    lambda _: httpx.Response(503, content=b"source unavailable")
                )
            ) as client:
                projection = capture_pack(root, client=client)
            self.assertFalse(projection["class_verified"])
            self.assertEqual(projection["request_count"], 1)
            self.assertEqual(projection["failed_request_count"], 1)
            self.assertEqual(projection["entities"], [])
            self.assertEqual(projection["claims"], [])
            self.assertEqual((root / "raw/request-00.body").read_bytes(), b"source unavailable")
            self.assertEqual(projection, verify_pack(root))

    def test_cap_hits_are_retained_and_explicitly_truncated(self) -> None:
        cohort = [f"Q{index + 1}" for index in range(SELECTION_LIMIT)]
        self.assertEqual(len(parse_selection(_selection(cohort))), SELECTION_LIMIT)
        with self.assertRaises(ValueError):
            parse_selection(_selection([*cohort, "Q99999"]))
        with self.assertRaises(ValueError):
            parse_selection(_selection(["Q111", "Q111"]))

        def respond(request: httpx.Request) -> httpx.Response:
            if str(request.url) == CLASS_URL:
                return _respond(request)
            if request.url.params["query"] == SELECTION_QUERY:
                return httpx.Response(200, json=_selection(cohort))
            requested = re.search(r"VALUES \?genre \{ ([^}]+) \}", request.url.params["query"])
            self.assertIsNotNone(requested)
            assert requested is not None
            first = requested[1].split()[0].removeprefix("wd:")
            return httpx.Response(200, json={"results": {"bindings": [_row(first)] * ROW_LIMIT}})

        with tempfile.TemporaryDirectory() as temporary:
            with httpx.Client(transport=httpx.MockTransport(respond)) as client:
                projection = capture_pack(Path(temporary) / "pack", client=client)
            self.assertTrue(projection["selection_possibly_truncated"])
            self.assertFalse(projection["taxonomy_complete_for_selected_cohort"])
            self.assertTrue(
                all(batch["possibly_truncated"] for batch in projection["taxonomy_batches"])
            )
            self.assertEqual(len(projection["missing_taxonomy_qids"]), SELECTION_LIMIT - 5)
            self.assertEqual(projection["request_count"], 7)

    def test_context_properties_unrequested_entities_and_fake_uris_rejected(self) -> None:
        for prop in ("P136", "P135", "P495", "P740", "P434"):
            with self.subTest(prop=prop), self.assertRaises(ValueError):
                parse_taxonomy({"results": {"bindings": [_row("Q111", prop)]}}, ["Q111"])
        with self.assertRaises(ValueError):
            parse_taxonomy({"results": {"bindings": [_row("Q112")]}}, ["Q111"])
        row = _row("Q111")
        row["genre"]["value"] = "https://other.example/entity/Q111"
        with self.assertRaises(ValueError):
            parse_taxonomy({"results": {"bindings": [row]}}, ["Q111"])
        with self.assertRaises(ValueError):
            parse_selection(
                {"results": {"bindings": [{"genre": _uri("Q111"), "anchor": _uri("Q5")}]}}
            )

    def test_byte_cap_preserves_prefix_and_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "pack"
            with httpx.Client(
                transport=httpx.MockTransport(
                    lambda _: httpx.Response(200, content=b"x" * 2_000_001)
                )
            ) as client:
                projection = capture_pack(root, client=client)
            self.assertLessEqual(projection["response_bytes"], 2_000_000)
            self.assertEqual(projection["failed_request_count"], 1)
            self.assertFalse(projection["class_verified"])

    def test_offline_replay_rejects_mutated_projection_even_with_new_hash(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "pack"
            with httpx.Client(transport=httpx.MockTransport(_respond)) as client:
                capture_pack(root, client=client)
            projection = json.loads((root / "projection.json").read_text())
            projection["artist_memberships"] = [{"invented": True}]
            (root / "projection.json").write_text(json.dumps(projection), encoding="utf-8")
            _rebind(root, "projection.json")
            with self.assertRaisesRegex(ValueError, "independent raw replay"):
                verify_pack(root)

    def test_offline_replay_rejects_query_cohort_and_path_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "pack"
            with httpx.Client(transport=httpx.MockTransport(_respond)) as client:
                capture_pack(root, client=client)
            manifest = json.loads((root / "manifest.json").read_text())
            wrong_query = json.loads(json.dumps(manifest))
            wrong_query["requests"][1]["query"] = (
                'SELECT ?genre WHERE { ?genre rdfs:label "historical seed" }'
            )
            with self.assertRaisesRegex(ValueError, "frozen source-only query"):
                project_pack(root, wrong_query)
            wrong_cohort = json.loads(json.dumps(manifest))
            wrong_cohort["requests"][2]["requested_qids"] = ["Q99999"]
            with self.assertRaises(ValueError):
                project_pack(root, wrong_cohort)
            raw = root / "raw/request-00.body"
            original = root / "retained-class-body"
            raw.rename(original)
            raw.symlink_to(original)
            with self.assertRaisesRegex(ValueError, "symlink"):
                verify_pack(root)

    def test_checked_in_source_pack_replays_without_network(self) -> None:
        projection = verify_pack(Path("data/examples/open-genre-taxonomy"))
        self.assertTrue(projection["class_verified"])
        self.assertEqual(len(projection["entities"]), 1000)
        self.assertTrue(projection["selection_possibly_truncated"])
        self.assertTrue(projection["taxonomy_complete_for_selected_cohort"])
        self.assertEqual(projection["artist_memberships"], [])


if __name__ == "__main__":
    unittest.main()
