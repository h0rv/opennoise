"""Offline synthetic ZIP/HTTP fixtures; no real source acquisition or audio evidence."""

# ruff: noqa: SLF001 -- defensive request boundary testing.
# ruff: noqa: TC003 -- fixture annotations colocated with imports.
# ruff: noqa: SIM117 -- distinct mock and rejection scopes.
from __future__ import annotations

import hashlib
import io
import json
import struct
import tempfile
import unittest
import zipfile
from collections.abc import Iterator
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from typing import Any, override
from unittest.mock import patch

import httpx

from opennoise.serving.metadata import fma_large32 as m


class Large32Tests(unittest.TestCase):
    @override
    def setUp(self) -> None:
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_STORED) as archive:
            for i in (1, 2, 3):
                archive.writestr(f"fma_large/000/{i:06}.mp3", bytes([i]) * 100_000)
        self.archive = buffer.getvalue()
        self.calls: list[httpx.Request] = []
        self.stack.enter_context(patch.object(m, "_client", self.client))

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self.respond), follow_redirects=False)

    def respond(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        self.assertEqual(str(request.url), m.URL)
        value = request.headers["range"][6:]
        start, end = (
            (len(self.archive) - int(value[1:]), len(self.archive) - 1)
            if value.startswith("-")
            else map(int, value.split("-"))
        )
        return httpx.Response(
            206,
            headers={
                "content-range": f"bytes {start}-{end}/{len(self.archive)}",
                "content-length": str(end - start + 1),
                "etag": '"fixture"',
            },
            stream=httpx.ByteStream(self.archive[start : end + 1]),
        )

    def test_probe_suffix_and_directory_replay_and_attempt_claim_tamper(self) -> None:
        output = self.root / "probe"
        result = m.probe(output)
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(self.calls[0].headers["range"], "bytes=-65557")
        self.assertEqual(self.calls[1].headers["if-match"], '"fixture"')
        self.assertEqual(set(m.verify_probe(output)[1]), {1, 2, 3})
        self.assertEqual(result["directory"]["entries"], 3)
        path = output / "attempt-001.json"
        record = json.loads(path.read_bytes())
        record["range"] = "bytes=0-65556"
        path.write_text(json.dumps(record))
        with self.assertRaises(ValueError):
            m.verify_probe(output)

    def test_failure_status_and_transport_evidence_stop_without_retry(self) -> None:
        for status in (403, 302, 200):
            calls = []

            def respond(request: httpx.Request, status: int = status) -> httpx.Response:
                calls.append(request)  # noqa: B023 -- synchronous fixture callback.
                return httpx.Response(
                    status,
                    headers={"location": "https://example.invalid"},
                    stream=httpx.ByteStream(b"forbidden"),
                )

            directory = self.root / str(status)
            with (
                patch.object(
                    m, "_client", lambda: httpx.Client(transport=httpx.MockTransport(respond))
                ),
                self.assertRaises(ValueError),
            ):
                m.probe(directory)
            self.assertEqual(len(calls), 1)
            attempt = json.loads((directory / "attempt-001.json").read_bytes())
            self.assertEqual(attempt["status"], status)
            self.assertEqual(attempt["state"], "failed")
            self.assertEqual(attempt["received_bytes"], 0)

        def fail(_request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("fixture failure")

        directory = self.root / "network"
        with patch.object(m, "_client", lambda: httpx.Client(transport=httpx.MockTransport(fail))):
            with self.assertRaises(httpx.ConnectError):
                m.probe(directory)
        attempt = json.loads((directory / "attempt-001.json").read_bytes())
        self.assertEqual(attempt["error_type"], "ConnectError")
        self.assertIsNone(attempt["status"])

    def test_entire_directory_budget_preflight(self) -> None:
        self.assertEqual(len(m.directory_plan(100, 14_000_000)), 7)
        for length in (14_000_001, 16_000_000):
            with self.assertRaises(ValueError):
                m.directory_plan(100, length)
        self.assertEqual(self.calls, [])

    def test_zip64_conditional_fields_and_unsafe_attributes(self) -> None:
        start = self.archive.index(b"PK\x01\x02")
        fields = list(struct.unpack_from("<4s6H3L5H2L", self.archive, start))
        name = self.archive[start + 46 : start + 46 + fields[10]]
        fields[8], fields[9], fields[16] = 0xFFFFFFFF, 0xFFFFFFFF, 0xFFFFFFFF
        extra = struct.pack("<HHQQQ", 1, 24, 100_000, 100_000, 123)
        fields[11] = len(extra)
        raw = struct.pack("<4s6H3L5H2L", *fields) + name + extra
        member = m.directory_members(raw, 300_000, 1)[1]
        self.assertEqual(
            (member["uncompressed"], member["compressed"], member["offset"]),
            (100_000, 100_000, 123),
        )
        for attributes in ((0o040755 << 16), (0o120777 << 16), 0x10):
            changed = fields.copy()
            changed[15] = attributes
            with self.assertRaises(ValueError):
                m.directory_members(struct.pack("<4s6H3L5H2L", *changed) + name + extra, 300_000, 1)
        with self.assertRaises(ValueError):
            m.directory_members(raw.replace(name, b"\0" + name[1:]), 300_000, 1)
        changed = fields.copy()
        changed[13] = 1
        with self.assertRaises(ValueError):
            m.directory_members(struct.pack("<4s6H3L5H2L", *changed) + name + extra, 300_000, 1)
        with self.assertRaises(ValueError):
            m.directory_members(raw + raw, 300_000, 2)

    def test_zip64_end_locator_and_multidisk(self) -> None:
        extended = struct.pack("<4sQ2H2L4Q", b"PK\x06\x06", 44, 45, 45, 0, 0, 3, 3, 300, 100)
        locator = struct.pack("<4sLQL", b"PK\x06\x07", 0, 400, 1)
        end = struct.pack("<4s4H2LH", b"PK\x05\x06", 0, 0, 65535, 65535, 0xFFFFFFFF, 0xFFFFFFFF, 0)
        tail = extended + locator + end
        self.assertEqual(m.directory_location(tail, 400 + len(tail)), (100, 300, 3))
        bad = extended + struct.pack("<4sLQL", b"PK\x06\x07", 0, 400, 2) + end
        with self.assertRaises(ValueError):
            m.directory_location(bad, 400 + len(bad))

    def test_frozen_selection_capture_crc_and_old_artist_genre_priority(self) -> None:
        source, baseline, probe = self.root / "source", self.root / "baseline", self.root / "probe"
        source.mkdir()
        baseline.mkdir()
        (source / "source-receipt.json").write_text("{}")
        (baseline / "listening.json").write_text("{}")
        previous = {"tracks": [{"track_id": 100, "artist_id": 1, "genre_ids": [1]}]}
        rows = [
            dict(  # noqa: C408 -- explicit source field fixture.
                track_id=str(i),
                artist_id=str(i),
                track_genres=str([{"genre_id": str(i + 1)}]),
                license_url="https://creativecommons.org/licenses/by/4.0/",
            )
            for i in (1, 2, 3)
        ]

        def sources(_source: Path, member: str) -> tuple[Iterator[dict[str, str]], Any, list[Any]]:
            values = rows if member == "tracks" else [{"artist_id": str(i)} for i in (1, 2, 3)]
            return (
                iter(values),
                SimpleNamespace(complete=True, sha256=hashlib.sha256(b"fixture")),
                [],
            )

        with (
            patch.object(m.fma_listening64, "verify", return_value=previous),
            patch.object(
                m,
                "verify_sources",
                return_value={
                    "members": {
                        "fma_metadata/raw_tracks.csv": "tracks",
                        "fma_metadata/raw_artists.csv": "artists",
                    }
                },
            ),
            patch.object(m, "source_rows", sources),
        ):
            m.probe(probe)
            frozen = m.freeze(source, baseline, probe)
            self.assertEqual(len(self.calls), 2)
            self.assertIn(1, [row["track_id"] for row in frozen["tracks"]])
            self.assertEqual(frozen["new_genres"], [2, 3, 4])
            output = self.root / "pack"
            result = m.capture(source, baseline, probe, output)
            self.assertEqual(len(self.calls), 8)
            self.assertEqual(m.verify(output, source, baseline), result)
            audio = output / result["tracks"][0]["audio_path"]
            audio.write_bytes(b"x" * audio.stat().st_size)
            with self.assertRaises(ValueError):
                m.verify(output, source, baseline)

    def test_stream_limits_changed_etag_and_suffix_headers_fail_closed(self) -> None:
        for number, (body, changes) in enumerate(
            (
                (b"x", {}),
                (b"x" * (m.TAIL_BYTES + 1), {}),
                (b"", {"etag": 'W/"weak"'}),
                (b"", {"content-range": "bytes 0-65556/300000"}),
            )
        ):

            def response(
                _request: httpx.Request, body: bytes = body, changes: dict[str, str] = changes
            ) -> httpx.Response:
                return httpx.Response(
                    206,
                    headers={
                        "content-range": f"bytes {300000 - m.TAIL_BYTES}-299999/300000",
                        "content-length": str(m.TAIL_BYTES),
                        "etag": '"fixture"',
                        **changes,
                    },
                    stream=httpx.ByteStream(body),
                )

            directory = self.root / f"invalid-{number}"
            with (
                patch.object(
                    m, "_client", lambda: httpx.Client(transport=httpx.MockTransport(response))
                ),
                self.assertRaises(ValueError),
            ):
                m.probe(directory)
            attempt = json.loads((directory / "attempt-001.json").read_bytes())
            self.assertEqual(attempt["state"], "failed")
            self.assertFalse((directory / "attempt-002.json").exists())
        directory = self.root / "etag"
        directory.mkdir()
        with self.client() as client, self.assertRaises(ValueError):
            m._request(
                client,
                directory,
                "changed.range",
                0,
                1,
                [],
                phase="audio",
                total=len(self.archive),
                etag='"other"',
            )
        self.assertEqual(
            json.loads((directory / "attempt-001.json").read_bytes())["state"], "failed"
        )

    def test_phase_budget_preflight_never_sends_a_request(self) -> None:
        output = self.root / "budget"
        output.mkdir()
        with self.client() as client:
            for captures in (
                [{"phase": "audio", "bytes": 0}] * 64,
                [{"phase": "audio", "bytes": 31_999_999}],
            ):
                with self.assertRaises(ValueError):
                    m._request(
                        client,
                        output,
                        "no.range",
                        0,
                        1,
                        captures,
                        phase="audio",
                        total=len(self.archive),
                        etag='"fixture"',
                    )
            with self.assertRaises(ValueError):
                m._request(
                    client,
                    output,
                    "large.range",
                    0,
                    2_000_000,
                    [],
                    phase="audio",
                    total=3_000_000,
                    etag='"fixture"',
                )
        self.assertEqual(self.calls, [])
        self.assertEqual(list(output.iterdir()), [])
