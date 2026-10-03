"""HTTP-free worker checks: source failures and caps retain the frozen denominator."""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from email.message import Message
from pathlib import Path
from unittest.mock import patch

from opennoise.ingest.musicbrainz.full_catalog_capture import capture, selected_headers
from opennoise.serving.metadata.full_recording_catalog import (
    read_ledger,
    request_plan,
    verify_ledger_order,
)
from tests.fresh_process import FreshProcessTestCase

ARTIST = "11111111-1111-4111-8111-111111111111"


class Response(io.BytesIO):
    """A literal native response stream; never accesses a network."""

    code = 200

    def __init__(self, body: bytes) -> None:
        """Wrap bytes with actual-source-style length headers."""
        super().__init__(body)
        self.headers = Message()
        self.headers["Content-Length"] = str(len(body))


class WorkerTests(FreshProcessTestCase):
    def test_selected_header_scope_excludes_secret_values_and_caps_metadata(self) -> None:
        headers = Message()
        headers["Content-Type"] = "application/json"
        headers["Set-Cookie"] = "secret-cookie-value"
        headers["Authorization"] = "secret-token-value"
        selected, scope = selected_headers(headers)
        self.assertEqual(selected, {"content-type": "application/json"})
        self.assertEqual(scope["omitted_count"], 2)
        self.assertNotIn("secret", json.dumps([selected, scope]))
        headers["Content-Encoding"] = "x" * 1025
        selected, scope = selected_headers(headers)
        self.assertFalse(scope["approved"])
        self.assertNotIn("content-encoding", selected)
        headers["Content-Length"] = "1"
        headers["Content-Length"] = "2"
        _, scope = selected_headers(headers)
        self.assertIn("content-length", scope["oversized_or_duplicate_names"])

    def test_oversized_encoding_cannot_default_into_core_projection(self) -> None:
        plan = request_plan(
            {"artists": [{"artist_mbid": ARTIST}], "roster_sha256": "test"},
            {"artists": [{"artist_mbid": ARTIST, "advertised_recording_count": 0}]},
        )
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / "plan.json").write_text(json.dumps(plan))
            body = b'{"recording-count":0,"recording-offset":0,"recordings":[]}'
            responses = [Response(body), Response(body)]
            for response in responses:
                response.headers["Content-Encoding"] = "x" * 1025
            with (
                patch("opennoise.ingest.musicbrainz.full_catalog_capture.guard", return_value=None),
                patch("urllib.request.OpenerDirector.open", side_effect=responses),
                patch("time.monotonic", side_effect=[0.0, 1.2, 1.2]),
            ):
                capture(directory)
            ledger = read_ledger(directory, plan)
            verify_ledger_order(plan, ledger)
            self.assertTrue(
                all(
                    row["projection"] is None and row["outcome"] == "header_scope_custody_only"
                    for row in ledger
                )
            )

    def test_interrupted_request_start_is_durable_and_never_complete(self) -> None:
        plan = request_plan(
            {"artists": [{"artist_mbid": ARTIST}], "roster_sha256": "test"},
            {"artists": [{"artist_mbid": ARTIST, "advertised_recording_count": 0}]},
        )
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / "plan.json").write_text(json.dumps(plan))
            with (
                patch("opennoise.ingest.musicbrainz.full_catalog_capture.guard", return_value=None),
                patch("urllib.request.OpenerDirector.open", side_effect=KeyboardInterrupt),
                self.assertRaises(KeyboardInterrupt),
            ):
                capture(directory)
            event = json.loads((directory / "request-ledger.jsonl").read_bytes())
            self.assertEqual(event["event"], "started")
            self.assertEqual(event["request"], plan["requests"][0])
            self.assertEqual(read_ledger(directory, plan, allow_partial=True), [])
            with self.assertRaises(ValueError):
                read_ledger(directory, plan)

    def test_unsupported_encoding_has_no_projected_fact(self) -> None:
        plan = request_plan(
            {"artists": [{"artist_mbid": ARTIST}], "roster_sha256": "test"},
            {"artists": [{"artist_mbid": ARTIST, "advertised_recording_count": 0}]},
        )
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / "plan.json").write_text(json.dumps(plan))
            body = b'{"recording-count":0,"recording-offset":0,"recordings":[]}'
            responses = [Response(body), Response(body)]
            for response in responses:
                response.headers["Content-Encoding"] = "gzip"
            with (
                patch("opennoise.ingest.musicbrainz.full_catalog_capture.guard", return_value=None),
                patch("urllib.request.OpenerDirector.open", side_effect=responses),
                patch("time.monotonic", side_effect=[0.0, 1.2, 1.2]),
            ):
                capture(directory)
            ledger = read_ledger(directory, plan)
            verify_ledger_order(plan, ledger)
            self.assertTrue(all(row["projection"] is None for row in ledger))
            self.assertEqual(
                json.loads((directory / "artists.json").read_bytes())[0]["status"], "unknown"
            )

    def test_zero_count_two_actual_probes(self) -> None:
        plan = request_plan(
            {"artists": [{"artist_mbid": ARTIST}], "roster_sha256": "test"},
            {"artists": [{"artist_mbid": ARTIST, "advertised_recording_count": 0}]},
        )
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / "plan.json").write_text(json.dumps(plan))
            body = b'{"recording-count":0,"recording-offset":0,"recordings":[]}'
            with (
                patch("opennoise.ingest.musicbrainz.full_catalog_capture.guard", return_value=None),
                patch(
                    "urllib.request.OpenerDirector.open",
                    side_effect=[Response(body), Response(body)],
                ),
                patch("time.monotonic", side_effect=[0.0, 1.2, 1.2]),
            ):
                result = capture(directory)
            self.assertEqual(result["actual_requests"], 2)
            self.assertEqual(
                json.loads((directory / "artists.json").read_bytes())[0]["status"],
                "observed_window_complete",
            )
            verify_ledger_order(plan, read_ledger(directory, plan))

    def test_resource_stop_makes_no_request_and_preserves_outcomes(self) -> None:
        plan = request_plan(
            {"artists": [{"artist_mbid": ARTIST}], "roster_sha256": "test"},
            {"artists": [{"artist_mbid": ARTIST, "advertised_recording_count": 201}]},
        )
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / "plan.json").write_text(json.dumps(plan))
            with (
                patch(
                    "opennoise.ingest.musicbrainz.full_catalog_capture.guard",
                    return_value="cgroup_capacity_unknown",
                ),
                patch("urllib.request.OpenerDirector.open") as http,
            ):
                result = capture(directory)
            http.assert_not_called()
            ledger = read_ledger(directory, plan)
            self.assertEqual(len(ledger), len(plan["requests"]))
            self.assertEqual(result["actual_requests"], 0)
            verify_ledger_order(plan, ledger)
            summary = json.loads((directory / "artists.json").read_bytes())[0]
            self.assertEqual(summary["status"], "unknown")
            self.assertEqual(summary["unfetched_baseline_count"], 201)


if __name__ == "__main__":
    unittest.main()
