"""A fresh namespace may reuse exact source bytes, never invented completed pages."""

from __future__ import annotations

import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any, ClassVar
from unittest.mock import patch
from uuid import UUID

from opennoise.ingest.musicbrainz import recovered_catalog_capture as worker
from opennoise.ingest.musicbrainz.compressed_catalog_custody import compress_stream
from opennoise.ingest.musicbrainz.recovered_catalog_capture import capture
from opennoise.serving.metadata import full_recording_catalog as old
from opennoise.serving.metadata import recovered_recording_catalog as new
from tests.fresh_process import FreshProcessTestCase
from tests.test_full_catalog_capture import Response

ARTIST = "11111111-1111-4111-8111-111111111111"


class RecoveryTests(FreshProcessTestCase):
    def reseal_fixture_proof(self, proof: Path, source: Path) -> None:
        """Model a self-rehashed attacker declaration, not trusted native source capture."""
        payload = json.loads(proof.read_bytes())
        payload["files"] = {
            str(p.relative_to(source)): {
                "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
                "bytes": p.stat().st_size,
            }
            for p in source.rglob("*")
            if p.is_file()
        }
        proof.write_text(json.dumps(payload))

    def fixture(self, parent: Path, *, count: int = 0) -> tuple[Path, dict[str, Any]]:
        source = parent / "old"
        source.mkdir()
        (source / "custody").mkdir()
        selection = {"artists": [{"artist_mbid": ARTIST}], "roster_sha256": "synthetic"}
        candidates = {"artists": [{"artist_mbid": ARTIST, "advertised_recording_count": count}]}
        plan = old.request_plan(selection, candidates)
        (source / "plan.json").write_text(json.dumps(plan))
        body = old.canonical_json(
            {
                "recording-count": count,
                "recording-offset": 0,
                "recordings": []
                if count == 0
                else [
                    {
                        "id": "22222222-2222-4222-8222-222222222222",
                        "title": "Original title",
                        "artist-credit": [{"artist": {"id": ARTIST, "name": "Artist"}}],
                    }
                ],
            }
        )
        custody = compress_stream(io.BytesIO(body), source / "custody/000-0000.json.zst")
        custody["path"] = "custody/000-0000.json.zst"
        scope = {
            "approved": True,
            "omitted_count": 0,
            "omitted_names": [],
            "omitted_names_truncated": False,
            "oversized_or_duplicate_names": [],
        }
        row = {
            "request": plan["requests"][0],
            "actual_request": True,
            "status_code": 200,
            "custody": custody,
            "projection": old.page_binding(old.project_page(body, plan["requests"][0])),
            "started_monotonic_seconds": 0.0,
            "fetched_at": "2026-10-03T00:00:00+00:00",
            "headers": {},
            "header_scope": scope,
            "outcome": "native_core_page",
        }
        events = [
            {
                "event": "started",
                "sequence": 0,
                **{key: row[key] for key in ["request", "started_monotonic_seconds", "fetched_at"]},
            },
            {
                "event": "response",
                "sequence": 0,
                "status_code": 200,
                "headers": {},
                "header_scope": scope,
            },
            {"event": "outcome", "sequence": 0, "capture": row},
        ]
        (source / "request-ledger.jsonl").write_bytes(
            b"".join(old.canonical_json(e) + b"\n" for e in events)
        )
        files = {
            str(p.relative_to(source)): {
                "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
                "bytes": p.stat().st_size,
            }
            for p in source.rglob("*")
            if p.is_file()
        }
        proof = parent / "proof.json"
        proof.write_text(
            json.dumps({"source_directory": str(source), "files": files, "completed_requests": 1})
        )
        output = parent / "new"
        output.mkdir()
        (output / "source-reuse.json").write_text(
            json.dumps(
                new.verify_source_prefix(
                    proof, expected_sha256=hashlib.sha256(proof.read_bytes()).hexdigest()
                )
            )
        )
        new_plan = new.request_plan(selection, candidates)
        (output / "plan.json").write_text(json.dumps(new_plan))
        return output, new_plan

    def test_reused_page_original_bytes_events_and_zero_count_closure(self) -> None:
        class Response(io.BytesIO):
            code = 200
            headers: ClassVar[dict[str, str]] = {}

        with tempfile.TemporaryDirectory() as temporary:
            output, plan = self.fixture(Path(temporary))
            response = Response(b'{"recording-count":0,"recording-offset":0,"recordings":[]}')
            with (
                patch(
                    "opennoise.ingest.musicbrainz.recovered_catalog_capture.guard",
                    return_value=None,
                ),
                patch("urllib.request.OpenerDirector.open", return_value=response) as http,
                patch("time.monotonic", return_value=2.4),
            ):
                result = capture(output)
            http.assert_called_once()
            self.assertEqual(result["new_actual_requests"], 1)
            self.assertEqual(result["reused_native_requests"], 1)
            new.verify_ledger_order(plan, new.read_ledger(output, plan))
            self.assertEqual(
                json.loads((output / "artists.json").read_bytes())[0]["status"],
                "observed_window_complete",
            )
            new.verify_inherited_sources(
                output,
                expected_sha256=hashlib.sha256(
                    (output.parent / "proof.json").read_bytes()
                ).hexdigest(),
            )
            self.assertEqual(
                (output / "custody/000-0000.json.zst").stat().st_ino,
                (output.parent / "old/custody/000-0000.json.zst").stat().st_ino,
            )

    def test_changed_prefix_file_or_unknown_event_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output, _ = self.fixture(Path(temporary))
            source = output.parent / "old"
            (source / "extra.json").write_text("{}")
            with self.assertRaises(ValueError):
                new.verify_source_prefix(output.parent / "proof.json")

    def test_v3_has_explicit_new_allocation_and_no_v2_global_mutation(self) -> None:
        self.assertEqual(old.LIMITS["metadata_reserve_bytes"], 5_000_000)
        self.assertEqual(new.LIMITS["metadata_reserve_bytes"], 8_000_000)
        for field in [
            "requests",
            "decoded_bytes",
            "logical_pack_bytes",
            "response_bytes",
            "max_process_rss_bytes",
            "spacing_seconds",
        ]:
            self.assertEqual(old.LIMITS[field], new.LIMITS[field])

    def test_trusted_origin_pin_cannot_be_self_rehashed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output, _ = self.fixture(Path(temporary))
            proof = output.parent / "proof.json"
            trusted = hashlib.sha256(proof.read_bytes()).hexdigest()
            changed = json.loads(proof.read_bytes())
            changed["scope"] = "changed declaration"
            proof.write_text(json.dumps(changed))
            with self.assertRaises(ValueError):
                new.verify_source_prefix(proof, expected_sha256=trusted)

    def test_consistent_inherited_time_rewrite_rejected_by_origin_bytes(self) -> None:
        class Response(io.BytesIO):
            code = 200
            headers: ClassVar[dict[str, str]] = {}

        with tempfile.TemporaryDirectory() as temporary:
            output, plan = self.fixture(Path(temporary))
            trusted = hashlib.sha256((output.parent / "proof.json").read_bytes()).hexdigest()
            with (
                patch(
                    "opennoise.ingest.musicbrainz.recovered_catalog_capture.guard",
                    return_value=None,
                ),
                patch(
                    "urllib.request.OpenerDirector.open",
                    return_value=Response(
                        b'{"recording-count":0,"recording-offset":0,"recordings":[]}'
                    ),
                ),
                patch("time.monotonic", return_value=2.4),
            ):
                capture(output)
            path = output / "request-ledger.jsonl"
            events = [json.loads(line) for line in path.read_bytes().splitlines()]
            for event in events:
                if event["sequence"] == 0:
                    row = event.get("capture", event)
                    if "fetched_at" in row:
                        row["fetched_at"] = "2026-10-03T01:00:00+00:00"
            path.write_bytes(b"".join(old.canonical_json(e) + b"\n" for e in events))
            # Local state consistency passes; authenticated inherited source bytes do not.
            new.verify_ledger_order(plan, new.read_ledger(output, plan))
            with self.assertRaises(ValueError):
                new.verify_inherited_sources(output, expected_sha256=trusted)

    def test_consistent_native_fact_rewrite_cannot_replace_inherited_origin(self) -> None:
        class Response(io.BytesIO):
            code = 200
            headers: ClassVar[dict[str, str]] = {}

        with tempfile.TemporaryDirectory() as temporary:
            output, plan = self.fixture(Path(temporary), count=1)
            trusted = hashlib.sha256((output.parent / "proof.json").read_bytes()).hexdigest()
            body = old.canonical_json(
                {
                    "recording-count": 1,
                    "recording-offset": 0,
                    "recordings": [
                        {
                            "id": "22222222-2222-4222-8222-222222222222",
                            "title": "Original title",
                            "artist-credit": [{"artist": {"id": ARTIST, "name": "Artist"}}],
                        }
                    ],
                }
            )
            with (
                patch(
                    "opennoise.ingest.musicbrainz.recovered_catalog_capture.guard",
                    return_value=None,
                ),
                patch("urllib.request.OpenerDirector.open", return_value=Response(body)),
                patch("time.monotonic", return_value=2.4),
            ):
                capture(output)
            path = output / "request-ledger.jsonl"
            events = [json.loads(line) for line in path.read_bytes().splitlines()]
            rewritten = body.replace(b"Original title", b"Rewritten title")
            for event in events:
                if event["event"] == "outcome":
                    row = event["capture"]
                    frame = output / row["custody"]["path"]
                    # Replace only the temporary new fixture, keeping the old hardlink unchanged.
                    frame.unlink()
                    custody = compress_stream(io.BytesIO(rewritten), frame)
                    custody["path"] = row["custody"]["path"]
                    row["custody"] = custody
                    row["projection"] = new.page_binding(
                        new.project_page(rewritten, row["request"])
                    )
            path.write_bytes(b"".join(old.canonical_json(e) + b"\n" for e in events))
            new.verify_ledger_order(plan, new.read_ledger(output, plan))
            pages = [new.project_page(rewritten, r) for r in plan["requests"]]
            self.assertEqual(
                new.artist_summary(ARTIST, plan["requests"], pages)["status"],
                "observed_window_complete",
            )
            with self.assertRaises(ValueError):
                new.verify_inherited_sources(output, expected_sha256=trusted)

    def test_extra_event_and_changed_native_offset_cannot_be_self_rehashed(self) -> None:
        for attack in ["extra_event", "offset", "unfinished"]:
            with tempfile.TemporaryDirectory() as temporary:
                output, _ = self.fixture(Path(temporary))
                source = output.parent / "old"
                if attack == "offset":
                    plan = json.loads((source / "plan.json").read_bytes())
                    plan["requests"][0]["offset"] = 100
                    (source / "plan.json").write_text(json.dumps(plan))
                else:
                    event = {
                        "event": "unknown" if attack == "extra_event" else "started",
                        "sequence": 1,
                    }
                    if attack == "unfinished":
                        plan = json.loads((source / "plan.json").read_bytes())
                        event.update(
                            request=plan["requests"][1],
                            fetched_at="2026-10-03T00:00:02+00:00",
                            started_monotonic_seconds=2.4,
                        )
                    with (source / "request-ledger.jsonl").open("ab") as stream:
                        stream.write(json.dumps(event).encode() + b"\n")
                self.reseal_fixture_proof(output.parent / "proof.json", source)
                with self.assertRaises(ValueError):
                    new.verify_source_prefix(output.parent / "proof.json")

    def test_complete_150_zero_catalogs_retains_all_denominators(self) -> None:
        artists = [{"artist_mbid": str(UUID(int=n))} for n in range(1, 151)]
        selection = {"artists": artists, "roster_sha256": "synthetic150"}
        candidates = {"artists": [{**row, "advertised_recording_count": 0} for row in artists]}
        plan = new.request_plan(selection, candidates)
        self.assertEqual(len(plan["requests"]), 300)
        summaries = []
        for index in range(0, 300, 2):
            requests = plan["requests"][index : index + 2]
            body = b'{"recording-count":0,"recording-offset":0,"recordings":[]}'
            pages = [new.project_page(body, r) for r in requests]
            summaries.append(new.artist_summary(requests[0]["artist_mbid"], requests, pages))
        self.assertEqual(len(summaries), 150)
        self.assertTrue(all(r["status"] == "observed_window_complete" for r in summaries))

    def test_over_budget_plan_rejected_before_network(self) -> None:
        with self.assertRaises(ValueError):
            new.request_plan(
                {"artists": [{"artist_mbid": ARTIST}], "roster_sha256": "synthetic"},
                {"artists": [{"artist_mbid": ARTIST, "advertised_recording_count": 200000}]},
            )

    def test_post_header_rss_stop_retains_no_body_or_projected_fact(self) -> None:
        """A real guard rejection must stay incomplete even with native-looking bytes."""
        with tempfile.TemporaryDirectory() as temporary:
            directory, plan = self.fixture(Path(temporary))
            response = Response(b'{"recording-count":0,"recording-offset":0,"recordings":[]}')
            with (
                patch.object(worker, "guard", return_value=None),
                patch.object(
                    worker,
                    "process_peak_bytes",
                    return_value=worker.LIMITS["max_process_rss_bytes"],
                ),
                patch("urllib.request.OpenerDirector.open", return_value=response) as http,
                patch.object(worker, "compress_stream") as compress,
            ):
                worker.capture(directory)
            http.assert_called_once()
            compress.assert_not_called()
            self.assertTrue(response.closed)
            ledger = new.read_ledger(directory, plan)
            new.verify_ledger_order(plan, ledger)
            rejected = [row for row in ledger if row["outcome"] == "process_rss_custody_only"]
            self.assertEqual(len(rejected), 1)
            self.assertIsNone(rejected[0]["projection"])
            self.assertIsNone(rejected[0]["custody"]["path"])
            self.assertFalse(rejected[0]["custody"]["complete_body"])
            self.assertNotEqual(
                json.loads((directory / "artists.json").read_bytes())[0]["status"],
                "observed_window_complete",
            )


if __name__ == "__main__":
    unittest.main()
