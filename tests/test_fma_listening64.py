# ruff: noqa: SLF001 -- exercise defensive internal wire-format boundaries.
# ruff: noqa: B023 -- mocked callbacks execute synchronously within each loop iteration.
import hashlib
import io
import json
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

from opennoise.serving.metadata import fma_listening64 as m


class Listening64Tests(unittest.TestCase):
    @override
    def setUp(self) -> None:
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for identity in range(1, 5):
                archive.writestr(f"fma_small/000/{identity:06}.mp3", bytes([identity]) * 200)
        self.archive = buffer.getvalue()
        self.stack.enter_context(patch.object(m, "ARCHIVE_BYTES", len(self.archive)))
        self.stack.enter_context(patch.object(m, "TAIL_BYTES", len(self.archive)))
        self.calls = []
        self.stack.enter_context(patch.object(m, "_client", self.client))
        self.source = self.root / "source"
        self.source.mkdir()
        (self.source / "source-receipt.json").write_text("{}")
        self.rows = [
            dict(  # noqa: C408 -- fixture source-field construction.
                track_id=str(i),
                artist_id=str(1 if i == 2 else i),  # noqa: PLR2004 -- duplicate-artist fixture.
                track_genres=str([{"genre_id": str(i)}]),
                license_url="https://creativecommons.org/licenses/by/4.0/",
                track_title=f"Track {i}",
            )
            for i in range(1, 5)
        ]
        self.rows[-1]["license_url"] = "https://example.org/not-approved"
        self.stack.enter_context(
            patch.object(
                m,
                "verify_sources",
                return_value={
                    "members": {
                        "fma_metadata/raw_artists.csv": "artists",
                        "fma_metadata/raw_tracks.csv": "tracks",
                    }
                },
            )
        )
        self.stack.enter_context(patch.object(m, "source_rows", self.source_rows))

    def source_rows(
        self, _source: Path, member: str
    ) -> tuple[Iterator[dict[str, str]], SimpleNamespace, list[Any]]:
        rows = self.rows if member == "tracks" else [{"artist_id": str(i)} for i in range(1, 5)]
        return iter(rows), SimpleNamespace(complete=True, sha256=hashlib.sha256(b"fixture")), []

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self.respond), follow_redirects=False)

    def respond(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        self.assertEqual(str(request.url), m.URL)
        start, end = map(int, request.headers["range"][6:].split("-"))
        return httpx.Response(
            206,
            headers={
                "content-range": f"bytes {start}-{end}/{len(self.archive)}",
                "content-length": str(end - start + 1),
                "etag": '"fixture"',
            },
            stream=httpx.ByteStream(self.archive[start : end + 1]),
        )

    def prepared(self) -> tuple[Path, dict[str, Any]]:
        directory = self.root / "probe"
        m.probe(directory)
        frozen = m.freeze(self.source, directory)
        self.assertEqual(len(self.calls), 2)  # Freeze is offline.
        return directory, frozen

    def test_roundtrip_frozen_unique_artist_and_license(self) -> None:
        directory, frozen = self.prepared()
        self.assertEqual(len(frozen["tracks"]), 2)
        self.assertEqual(len({r["artist_id"] for r in frozen["tracks"]}), 2)
        self.assertNotIn(4, [r["track_id"] for r in frozen["tracks"]])
        output = self.root / "pack"
        result = m.capture(self.source, directory, output)
        self.assertEqual(len(self.calls), 6)
        self.assertEqual(m.verify(output, self.source), result)
        self.assertLessEqual(result["response_bytes"], frozen["planned_response_bytes_upper_bound"])
        self.assertEqual(result["audio_bytes"], 400)
        self.assertTrue(all(r.headers.get("if-match") == '"fixture"' for r in self.calls[1:]))
        (output / "unexpected.mp3").write_bytes(b"bad")
        with self.assertRaises(ValueError):
            m.verify(output, self.source)

    def test_frozen_selection_mutation_rejected_before_request(self) -> None:
        directory, _ = self.prepared()
        self.rows[0]["license_url"] = ""
        with self.assertRaises(ValueError):
            m.capture(self.source, directory, self.root / "pack")
        self.assertEqual(len(self.calls), 2)

    def test_rejects_status_redirect_etag_range_without_retry(self) -> None:
        for status, changes in [
            (403, {}),
            (302, {"location": "https://example.org"}),
            (206, {"etag": '"changed"'}),
            (206, {"content-range": "bytes 1-2/3"}),
        ]:
            with self.subTest(status=status, changes=changes):
                calls = []

                def respond(request: httpx.Request) -> httpx.Response:
                    calls.append(request)
                    headers = {
                        "content-length": "2",
                        "content-range": f"bytes 0-1/{m.ARCHIVE_BYTES}",
                        "etag": '"fixture"',
                        **changes,
                    }
                    return httpx.Response(status, headers=headers, stream=httpx.ByteStream(b"ab"))

                with (
                    httpx.Client(transport=httpx.MockTransport(respond)) as client,
                    self.assertRaises(ValueError),
                ):
                    m._get(client, self.root, "bad.range", 0, 1, [], '"fixture"')
                self.assertEqual(len(calls), 1)
                self.assertFalse((self.root / "bad.range").exists())

    def test_stream_size_and_budget_guards(self) -> None:
        for body in (b"a", b"abc"):
            with self.subTest(body=body):

                def respond(_request: httpx.Request) -> httpx.Response:
                    return httpx.Response(
                        206,
                        headers={
                            "content-length": "2",
                            "content-range": f"bytes 0-1/{m.ARCHIVE_BYTES}",
                            "etag": '"fixture"',
                        },
                        stream=httpx.ByteStream(body),
                    )

                with (
                    httpx.Client(transport=httpx.MockTransport(respond)) as client,
                    self.assertRaises(ValueError),
                ):
                    m._get(client, self.root, f"{len(body)}.range", 0, 1, [])
        with self.client() as client:
            with patch.object(m, "MAX_RESPONSE_BYTES", 1), self.assertRaises(ValueError):
                m._get(client, self.root, "budget.range", 0, 1, [])
            with self.assertRaises(ValueError):
                m._get(client, self.root, "count.range", 0, 1, [{"bytes": 0}] * 130)
        self.assertEqual(self.calls, [])

    def test_corruption_and_symlink_rejected(self) -> None:
        directory, _ = self.prepared()
        output = self.root / "pack"
        result = m.capture(self.source, directory, output)
        audio = output / result["tracks"][0]["audio_path"]
        audio.write_bytes(b"x" * audio.stat().st_size)
        with self.assertRaises(ValueError):
            m.verify(output, self.source)
        link = self.root / "linked"
        link.symlink_to(directory, target_is_directory=True)
        with self.assertRaises(ValueError):
            m.verify_probe(link)

    def test_unsafe_zip_member_and_symlink(self) -> None:
        for name, mode in [("unsafe/000001.mp3", 0o100644), ("fma_small/000/000001.mp3", 0o120777)]:
            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer, "w") as archive:
                info = zipfile.ZipInfo(name)
                info.external_attr = mode << 16
                archive.writestr(info, b"a")
            raw = buffer.getvalue()
            central = raw[raw.index(b"PK\x01\x02") : raw.index(b"PK\x05\x06")]
            with self.assertRaises(ValueError):
                m._members(central, raw.index(b"PK\x01\x02"))

    def test_crc_and_decompression_trailer(self) -> None:
        directory, frozen = self.prepared()
        member = frozen["tracks"][0]["member"]
        header = self.archive[member["offset"] : member["offset"] + 30]
        probed = json.loads((directory / "probe.json").read_text())
        start, end, prefix = m._payload_bounds(
            header, {"member": member}, probed["captures"][1]["start"]
        )
        payload = self.archive[start : end + 1]
        with self.assertRaises(ValueError):
            m._audio(payload, prefix, {**member, "crc32": 0})
        with self.assertRaises(ValueError):
            m._audio(
                payload + b"trailer", prefix, {**member, "compressed": member["compressed"] + 7}
            )

    def test_receipt_claim_tampering_rejected(self) -> None:
        directory, _ = self.prepared()
        output = self.root / "pack"
        result = m.capture(self.source, directory, output)
        mutations = {
            "audio_scope": "full archive",
            "metadata_license": "CC0",
            "musical_representativeness": "confirmed",
            "full_archive_hash_verified": True,
            "public_deployment_authorized": True,
        }
        for key, value in mutations.items():
            for changed in ({**result, key: value}, {k: v for k, v in result.items() if k != key}):
                with self.subTest(key=key, missing=key not in changed):
                    (output / "listening.json").write_text(json.dumps(changed))
                    with self.assertRaisesRegex(ValueError, "receipt claims"):
                        m.verify(output, self.source)
        for key in ("full_archive_hash_verified", "public_deployment_authorized"):
            (output / "listening.json").write_text(json.dumps({**result, key: 0}))
            with self.assertRaisesRegex(ValueError, "receipt claims"):
                m.verify(output, self.source)
        (output / "listening.json").write_text(json.dumps(result))
        self.assertEqual(m.verify(output, self.source), result)
