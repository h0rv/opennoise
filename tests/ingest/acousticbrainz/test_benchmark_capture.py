"""Bounded exact-recording identity, missingness, provenance and offline replay."""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from uuid import UUID

import httpx

from opennoise.common import canonical_json, sha256_file, sha256_hex, sha256_json
from opennoise.ingest.acousticbrainz.capture import (
    BoundedCapture,
    _outcome,
    capture_benchmarks,
    reproject_benchmarks,
    verify_benchmarks,
    verify_reprojection,
)
from opennoise.ingest.acousticbrainz.models import (
    MAX_API_REQUESTS,
    MAX_ARTISTS,
    MAX_RESPONSE_BYTES,
    MAX_TOTAL_BYTES,
    RIGHTS_URL,
    USER_AGENT,
    SourceCapture,
)
from opennoise.ingest.acousticbrainz.projection import (
    AcousticIdentityError,
    json_document,
    project_high_level,
    project_low_level,
    select_recordings,
    verify_embedded_recording,
)

ARTIST = UUID(int=100)
OTHER_ARTIST = UUID(int=999)
RECORDING = UUID(int=1001)
RATE_INTERVAL = 1.1
CACHE = Path(__file__).resolve().parents[3] / ".cache"
CLOCK_TOLERANCE = 1e-9


def _source(payload: bytes, *, status: int = 200, kind: str = "search") -> SourceCapture:
    return SourceCapture.model_validate(
        {
            "request_index": 1,
            "kind": kind,
            "requested_url": RIGHTS_URL,
            "fetched_at": "2026-09-30T00:00:00+00:00",
            "artist_mbid": ARTIST,
            "recording_mbid": RECORDING if kind != "search" else None,
            "status_code": status,
            "response_headers": {},
            "payload_path": "raw/001.bin",
            "payload_sha256": sha256_hex(payload),
            "payload_bytes": len(payload),
            "payload_complete": True,
        }
    )


def _recording(identifier: int, artist: UUID) -> dict[str, object]:
    return {
        "id": str(UUID(int=identifier)),
        "title": "same displayed recording title",
        "artist-credit": [{"artist": {"id": str(artist), "name": "same display name"}}],
    }


class ProjectionTests(unittest.TestCase):
    def test_exact_credits_ignore_homonyms_and_accept_multicredit_joinphrases(self) -> None:
        rows = [_recording(i, ARTIST) for i in (1004, 1002, 1003, 1001)]
        rows.append(_recording(1000, OTHER_ARTIST))
        rows[0]["artist-credit"] = [
            {"artist": {"id": str(ARTIST)}},
            " & ",
            {"artist": {"id": str(OTHER_ARTIST)}},
        ]
        payload = canonical_json({"recordings": rows})
        selection, chosen = select_recordings(_source(payload), payload)
        self.assertEqual(
            tuple(row.recording_mbid for row in chosen),
            tuple(UUID(int=i) for i in (1001, 1002, 1003)),
        )
        self.assertEqual(selection.exact_credit_recording_count, 4)
        self.assertEqual(selection.rejected_credit_recording_mbids, (UUID(int=1000),))
        self.assertTrue(all(ARTIST in row.credited_artist_mbids for row in chosen))

    def test_embedded_alias_mismatch_is_rejected_without_alias_merging(self) -> None:
        for identifiers in ([str(RECORDING), str(UUID(int=42))], ["malformed-uuid"]):
            with self.subTest(identifiers=identifiers), self.assertRaises(AcousticIdentityError):
                verify_embedded_recording(
                    {"metadata": {"tags": {"musicbrainz_trackid": identifiers}}}, RECORDING
                )
        self.assertEqual(verify_embedded_recording({}, RECORDING), "not_present")
        self.assertEqual(verify_embedded_recording({"mbid": str(RECORDING)}, RECORDING), "matched")

    def test_numeric_zero_remains_zero_and_absent_descriptor_remains_none(self) -> None:
        descriptors = project_low_level({"rhythm": {"bpm": 0}, "lowlevel": {"rms": {"mean": 0.0}}})
        values = {item.path: item.value for item in descriptors}
        self.assertEqual(values["rhythm.bpm"], 0)
        self.assertEqual(values["lowlevel.rms.mean"], 0)
        self.assertIsNone(values["rhythm.onset_rate"])
        with self.assertRaises(ValueError):
            project_low_level({"rhythm": {"bpm": "120"}, "lowlevel": {}})

    def test_histogram_statistics_use_explicit_mean_paths_and_preserve_v1_replay(self) -> None:
        document: dict[str, object] = {
            "rhythm": {
                "bpm": 123.0,
                "bpm_histogram_first_peak_bpm": {"mean": 130.0, "max": 140.0},
                "bpm_histogram_second_peak_bpm": {"mean": 80.0},
                "danceability": 3.5,
            },
            "lowlevel": {},
        }
        descriptors = {row.path: row.value for row in project_low_level(document, revision="v2")}
        self.assertEqual(descriptors["rhythm.bpm_histogram_first_peak_bpm.mean"], 130)
        self.assertEqual(descriptors["rhythm.bpm_histogram_second_peak_bpm.mean"], 80)
        self.assertEqual(descriptors["rhythm.danceability"], 3.5)
        self.assertIsNone(descriptors["lowlevel.rms.mean"])
        with self.assertRaisesRegex(ValueError, "unexpected source type"):
            project_low_level(document, revision="v1")

    def test_invalid_json_numeric_schema_and_duplicate_keys_are_not_projected(self) -> None:
        for payload in (
            b'{"x":NaN}',
            b'{"x":Infinity}',
            b'{"x":1e400}',
            b'{"x":1,"x":2}',
            b"[]",
        ):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                json_document(payload)
        with self.assertRaises(ValueError):
            project_low_level({"rhythm": {"bpm": True}, "lowlevel": {}})

    def test_high_level_families_preserve_raw_scores_without_native_genre_claims(self) -> None:
        document: dict[str, object] = {
            "highlevel": {
                "genre_one": {"value": "ambient", "probability": 0.2, "all": {"ambient": 2.0}},
                "genre_two": {"value": "rock", "probability": 0.8, "all": {"rock": -1.0}},
            }
        }
        models = project_high_level(document)
        self.assertEqual(tuple(item.predicted_label for item in models), ("ambient", "rock"))
        self.assertEqual(models[0].label_scores[0].raw_reported_score, 2)
        self.assertFalse(any(item.native_genre_fact or item.calibrated for item in models))

    def test_http_missing_failure_and_identity_review_are_distinct(self) -> None:
        for status, expected in ((404, "missing_http_404"), (500, "http_error")):
            row = _outcome(
                _source(b"{}", status=status, kind="low-level"),
                b"{}",
                artist=ARTIST,
                recording=RECORDING,
                level="low-level",
            )
            self.assertEqual(row.state, expected)
            self.assertFalse(row.numeric_descriptors)
        payload = canonical_json({"mbid": str(UUID(int=42)), "lowlevel": {}, "rhythm": {}})
        row = _outcome(
            _source(payload, kind="low-level"),
            payload,
            artist=ARTIST,
            recording=RECORDING,
            level="low-level",
        )
        self.assertEqual(row.state, "review_identity_mismatch")
        self.assertFalse(row.numeric_descriptors)


class _FakeTime:
    def __init__(self) -> None:
        self.now = 0.0
        self.waits: list[float] = []

    def clock(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.waits.append(seconds)
        self.now += seconds


class CaptureTests(unittest.IsolatedAsyncioTestCase):
    async def test_complete_capture_freezes_before_features_and_replays_without_network(  # noqa: PLR0915 - one complete capture and tamper replay fixture.
        self,
    ) -> None:
        with TemporaryDirectory(dir=CACHE) as temporary:
            directory = Path(temporary) / "pilot"
            benchmark = Path(temporary) / "benchmark.json"
            benchmark.write_bytes(
                canonical_json(
                    {
                        "benchmark_artists": [
                            {"artist_mbid": str(UUID(int=100 + i)), "name": f"benchmark-{i}"}
                            for i in range(MAX_ARTISTS)
                        ]
                    }
                )
            )
            requested: list[str] = []

            def respond(request: httpx.Request) -> httpx.Response:
                requested.append(str(request.url))
                self.assertEqual(request.headers["user-agent"], USER_AGENT)
                if str(request.url) == RIGHTS_URL:
                    return httpx.Response(
                        200,
                        content=b"AcousticBrainz data CC0",
                        headers={"Content-Type": "text/html"},
                    )
                if request.url.host == "musicbrainz.org":
                    artist = UUID(request.url.params["query"].removeprefix("arid:"))
                    self.assertEqual(request.url.params["limit"], "25")
                    rows = [_recording(artist.int * 10 + i, artist) for i in (4, 3, 2, 1)]
                    return httpx.Response(200, json={"recordings": rows})
                self.assertTrue((directory / "query-manifest.json").is_file())
                manifest = json.loads((directory / "query-manifest.json").read_bytes())
                self.assertEqual(len(manifest["recordings"]), 30)
                parts = request.url.path.split("/")
                recording, level = UUID(parts[-2]), parts[-1]
                missing = recording.int % 10 == (1 if level == "high-level" else 2)
                if missing:
                    return httpx.Response(404, json={"error": "Not found"})
                metadata = {"tags": {"musicbrainz_trackid": [str(recording)]}}
                if level == "high-level":
                    return httpx.Response(
                        200,
                        json={
                            "metadata": metadata,
                            "highlevel": {
                                "mood": {
                                    "value": "neutral",
                                    "probability": 0.5,
                                    "all": {"neutral": 0.5},
                                    "version": {"model": "fixture"},
                                }
                            },
                        },
                    )
                return httpx.Response(
                    200,
                    json={
                        "metadata": metadata,
                        "rhythm": {"bpm": 0},
                        "lowlevel": {"rms": {"mean": 0.0}},
                    },
                )

            clock = _FakeTime()
            original = BoundedCapture

            def factory(client: httpx.AsyncClient, path: Path) -> BoundedCapture:
                return original(client, path, clock=clock.clock, sleep=clock.sleep)

            async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
                with patch(
                    "opennoise.ingest.acousticbrainz.capture.BoundedCapture", side_effect=factory
                ):
                    result = await capture_benchmarks(
                        benchmark_source=benchmark, directory=directory, client=client
                    )
                self.assertEqual(len(requested), 71)
                self.assertEqual(result["api_request_count"], MAX_API_REQUESTS)
                self.assertEqual(result["rights_request_count"], 1)
                retained_bytes = result["retained_response_bytes"]
                assert isinstance(retained_bytes, int)
                self.assertLessEqual(retained_bytes, MAX_TOTAL_BYTES)
                self.assertEqual(
                    result["state_counts"],
                    {
                        "high-level": {"missing_http_404": 10, "available": 20},
                        "low-level": {"available": 20, "missing_http_404": 10},
                    },
                )
                self.assertTrue(
                    all(abs(wait - RATE_INTERVAL) < CLOCK_TOLERANCE for wait in clock.waits[1:])
                )
                replay = verify_benchmarks(directory=directory)
                self.assertEqual(result, replay)
                self.assertEqual(len(requested), 71)
                projection_directory = Path(temporary) / "projection-v2"
                projection = reproject_benchmarks(
                    source_directory=directory, directory=projection_directory
                )
                self.assertEqual(projection["new_upstream_requests"], 0)
                self.assertEqual(projection["state_counts"], result["state_counts"])
                self.assertEqual(verify_reprojection(directory=projection_directory), projection)
                self.assertEqual(len(requested), 71)
                raw = directory / "raw/001.bin"
                original_payload = raw.read_bytes()
                raw.write_bytes(original_payload + b"tampered")
                with self.assertRaisesRegex(ValueError, "file hash"):
                    verify_benchmarks(directory=directory)
                raw.write_bytes(original_payload)
                with self.assertRaises(FileExistsError):
                    await capture_benchmarks(
                        benchmark_source=benchmark, directory=directory, client=client
                    )
            # Bindings alone are insufficient: the exact-credit selection must replay too.
            manifest_path = directory / "query-manifest.json"
            manifest = json.loads(manifest_path.read_bytes())
            manifest["recordings"][0]["credited_artist_mbids"] = [str(OTHER_ARTIST)]
            manifest_path.write_bytes(canonical_json(manifest) + b"\n")
            receipt_path = directory / "receipt.json"
            receipt = json.loads(receipt_path.read_bytes())
            receipt["files"]["query-manifest.json"] = sha256_file(manifest_path)[0]
            receipt["manifest_sha256"] = sha256_file(manifest_path)[0]
            receipt["output_sha256"] = sha256_json(
                {key: value for key, value in receipt.items() if key != "output_sha256"}
            )
            receipt_path.write_bytes(canonical_json(receipt) + b"\n")
            with self.assertRaisesRegex(ValueError, "exact artist-credit"):
                verify_benchmarks(directory=directory)

    async def test_response_stream_and_api_request_bounds_are_enforced(self) -> None:
        with TemporaryDirectory(dir=CACHE) as temporary:
            directory = Path(temporary)
            (directory / "raw").mkdir()
            clock = _FakeTime()
            oversized = b"x" * (MAX_RESPONSE_BYTES + 1)
            async with httpx.AsyncClient(
                transport=httpx.MockTransport(
                    lambda _request: httpx.Response(200, content=oversized)
                )
            ) as client:
                fetcher = BoundedCapture(client, directory, clock=clock.clock, sleep=clock.sleep)
                source = await fetcher.fetch(kind="search", artist=ARTIST)
                self.assertEqual(source.payload_bytes, MAX_RESPONSE_BYTES)
                self.assertFalse(source.payload_complete)
                self.assertEqual(source.error_kind, "response_byte_bound")
                self.assertEqual(
                    (directory / source.payload_path).read_bytes(), oversized[:MAX_RESPONSE_BYTES]
                )
                fetcher.api_request_count = MAX_API_REQUESTS
                with self.assertRaisesRegex(ValueError, "API request budget"):
                    await fetcher.fetch(kind="high-level", artist=ARTIST, recording=RECORDING)

    async def test_audio_media_type_is_rejected_without_reading_body(self) -> None:
        with TemporaryDirectory(dir=CACHE) as temporary:
            directory = Path(temporary)
            (directory / "raw").mkdir()
            async with httpx.AsyncClient(
                transport=httpx.MockTransport(
                    lambda _request: httpx.Response(
                        200, content=b"forbidden audio", headers={"Content-Type": "audio/mpeg"}
                    )
                )
            ) as client:
                clock = _FakeTime()
                source = await BoundedCapture(
                    client, directory, clock=clock.clock, sleep=clock.sleep
                ).fetch(kind="low-level", artist=ARTIST, recording=RECORDING)
                self.assertEqual(source.payload_bytes, 0)
                self.assertEqual(source.error_kind, "unexpected_media_type")


if __name__ == "__main__":
    unittest.main()
