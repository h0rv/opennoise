"""Native sonic source custody cannot manufacture credits or artist-level evidence."""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from typing import TYPE_CHECKING, Any, override

import httpx

from opennoise.ingest.acousticbrainz.native_sonic import (
    LICENSE_AUDIT,
    REVISION,
    project_native_sonic,
    sonic_source_url,
    verify_native_sonic,
)
from opennoise.serving.metadata.recording_facts import recording_source_url
from scripts.build_native_sonic_pack import _fetch_core

if TYPE_CHECKING:
    from collections.abc import Iterator

ARTIST = "11111111-1111-4111-8111-111111111111"
RECORDING = "22222222-2222-4222-8222-222222222222"
MISSING = "33333333-3333-4333-8333-333333333333"
OTHER = "44444444-4444-4444-8444-444444444444"
OBSERVED = "2026-10-03T01:02:03+00:00"


def _write(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def _binding(path: Path) -> dict[str, Any]:
    body = path.read_bytes()
    return {"size_bytes": len(body), "sha256": hashlib.sha256(body).hexdigest()}


def _pack(root: Path, sonic: bytes | None = None) -> dict[str, Any]:
    (root / "raw/sonic").mkdir(parents=True)
    (root / "raw/credits").mkdir()
    sonic_path = f"raw/sonic/{RECORDING}.json"
    missing_path = f"raw/sonic/{MISSING}.json"
    core_path = f"raw/credits/{RECORDING}.json"
    if sonic is None:
        sonic = json.dumps(
            {
                "lowlevel": {"average_loudness": 0.0},
                "rhythm": {"bpm": 120.0},
                "tonal": {},
                "metadata": {
                    "tags": {
                        "musicbrainz_recordingid": [RECORDING],
                        "musicbrainz_artistid": [OTHER],
                        "artist": ["unverified uploader name"],
                        "genre": ["unverified uploader genre"],
                    }
                },
            }
        ).encode()
    (root / sonic_path).write_bytes(sonic)
    (root / missing_path).write_bytes(b'{"message":"Not found"}')
    _write(
        root / core_path,
        {
            "id": RECORDING,
            "title": "exact core recording",
            "artist-credit": [{"artist": {"id": ARTIST, "name": "core credited artist"}}],
        },
    )
    roster = [
        {"cohort_artist_mbid": ARTIST, "recording_mbid": recording}
        for recording in (RECORDING, MISSING)
    ]
    manifest = {
        "revision": REVISION,
        "imported_at": OBSERVED,
        "selection_method": "bounded test roster",
        "source_receipt_sha256": "a" * 64,
        "source_declaration_sha256": "b" * 64,
        "original_wrapper_product_promotion_allowed": False,
        "original_wrapper_scope": "authorized_local_research",
        "selected_recordings": roster,
        "sonic_captures": [
            {
                **row,
                "url": sonic_source_url(row["recording_mbid"]),
                "status_code": 200 if index == 0 else 404,
                "source_observed_at": None,
                "observation_time_status": "not_retained",
                "payload_complete": None,
                "raw_path": path,
                **_binding(root / path),
            }
            for index, (row, path) in enumerate(
                zip(roster, [sonic_path, missing_path], strict=True)
            )
        ],
        "credit_request_roster": roster[:1],
        "credit_captures": [
            {
                **roster[0],
                "origin": "fresh-lookup",
                "origin_receipt_sha256": None,
                "request_made": True,
                "url": recording_source_url(RECORDING),
                "source_observed_at": OBSERVED,
                "status_code": 200,
                "outcome": "accepted_core",
                "response_bytes": (root / core_path).stat().st_size,
                "response_complete": True,
                "raw_path": core_path,
                "sha256": _binding(root / core_path)["sha256"],
            }
        ],
    }
    _write(root / "manifest.json", manifest)
    _write(root / "license-audit.json", LICENSE_AUDIT)
    _write(root / "projection.json", project_native_sonic(root, manifest))
    names = [
        "manifest.json",
        "license-audit.json",
        "projection.json",
        sonic_path,
        missing_path,
        core_path,
    ]
    _write(
        root / "receipt.json",
        {"revision": REVISION, "files": {name: _binding(root / name) for name in names}},
    )
    return manifest


class NativeSonicTests(unittest.TestCase):
    def test_fresh_lookup_rejects_audio_before_body_read_and_never_retains_mixed_source(
        self,
    ) -> None:
        reads = []

        class AudioBody(httpx.SyncByteStream):
            @override
            def __iter__(self) -> Iterator[bytes]:
                reads.append(True)
                yield b"audio response must not be read"

        def audio_response(_: httpx.Request) -> httpx.Response:
            return httpx.Response(200, headers={"Content-Type": "audio/mpeg"}, stream=AudioBody())

        row = {"recording_mbid": RECORDING, "cohort_artist_mbid": ARTIST}
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with httpx.Client(transport=httpx.MockTransport(audio_response)) as client:
                capture = _fetch_core(root, row, 1000, client)
            self.assertEqual(capture.outcome, "unapproved_payload")
            self.assertEqual(capture.response_bytes, 0)
            self.assertEqual(reads, [])
            self.assertIsNone(capture.raw_path)
            mixed = {"id": RECORDING, "title": "mixed response", "genres": [{"name": "NC"}]}
            with httpx.Client(
                transport=httpx.MockTransport(lambda _: httpx.Response(200, json=mixed))
            ) as client:
                capture = _fetch_core(root, row, 1000, client)
            self.assertEqual(capture.outcome, "unapproved_payload")
            self.assertIsNone(capture.raw_path)
            self.assertEqual(list(root.iterdir()), [])

    def test_fresh_lookup_byte_budget_preserves_complete_failure_accounting(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with httpx.Client(
                transport=httpx.MockTransport(
                    lambda _: httpx.Response(
                        200, headers={"Content-Type": "application/json"}, content=b"x" * 100
                    )
                )
            ) as client:
                capture = _fetch_core(
                    root, {"recording_mbid": RECORDING, "cohort_artist_mbid": ARTIST}, 12, client
                )
            self.assertEqual(capture.outcome, "byte_budget")
            self.assertEqual(capture.response_bytes, 12)
            self.assertFalse(capture.response_complete)
            self.assertIsNone(capture.raw_path)
            self.assertIsNone(capture.sha256)

    def test_replay_retains_missingness_and_only_independent_exact_credits(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _pack(root)
            projected = verify_native_sonic(root)
            self.assertEqual(projected["state_counts"], {"available": 1, "missing_http_404": 1})
            self.assertEqual(projected["exact_credit_count"], 1)
            self.assertEqual(projected["missing_source_date_count"], 2)
            record = projected["records"][0]
            self.assertTrue(record["artist_join_allowed"])
            self.assertEqual(record["exact_credit"]["fact"]["credited_artist_mbids"], [ARTIST])
            self.assertNotIn("unverified uploader genre", json.dumps(projected))
            self.assertNotIn("unverified uploader name", json.dumps(projected))
            self.assertIn(
                {"path": "lowlevel.average_loudness", "value": 0.0}, record["descriptors"]
            )
            self.assertFalse(projected["old_research_wrappers_promoted"])
            self.assertEqual(projected["artist_medians"], [])
            self.assertEqual(projected["artist_genre_memberships"], [])

    def test_identity_mismatch_or_absence_never_assigns_vectors_or_artist_join(self) -> None:
        for tags, state in [
            ({"musicbrainz_recordingid": [OTHER]}, "identity_mismatch"),
            ({}, "identity_unverified"),
        ]:
            with self.subTest(state=state), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                _pack(
                    root,
                    json.dumps(
                        {"lowlevel": {}, "rhythm": {"bpm": 120}, "metadata": {"tags": tags}}
                    ).encode(),
                )
                row = verify_native_sonic(root)["records"][0]
                self.assertEqual(row["state"], state)
                self.assertEqual(row["descriptors"], [])
                self.assertFalse(row["artist_join_allowed"])

    def test_nonfinite_ambiguous_and_nonscalar_inputs_fail_closed(self) -> None:
        bodies = [
            f'{{"metadata":{{"tags":{{"musicbrainz_recordingid":["{RECORDING}"]}}}},"lowlevel":{{}},"rhythm":{{"bpm":NaN}}}}',
            f'{{"metadata":{{"tags":{{"musicbrainz_recordingid":["{RECORDING}"]}}}},"lowlevel":{{}},"rhythm":{{"bpm":120,"bpm":121}}}}',
            json.dumps(
                {
                    "metadata": {"tags": {"musicbrainz_recordingid": [RECORDING]}},
                    "lowlevel": {},
                    "rhythm": {"bpm": True},
                }
            ),
            json.dumps(
                {
                    "metadata": {"tags": {"musicbrainz_recordingid": [RECORDING]}},
                    "lowlevel": {},
                    "rhythm": {"bpm": {"mean": 120}},
                }
            ),
        ]
        for body in bodies:
            with self.subTest(body=body), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                _pack(root, body.encode())
                row = verify_native_sonic(root)["records"][0]
                self.assertEqual(row["state"], "invalid_scalar_schema")
                self.assertEqual(row["descriptors"], [])
                self.assertFalse(row["artist_join_allowed"])

    def test_missing_exact_credits_do_not_use_uploader_artist_tags(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = _pack(root)
            credit = manifest["credit_captures"][0]
            credit.update(outcome="unapproved_payload", raw_path=None, sha256=None)
            result = project_native_sonic(root, manifest)
            self.assertEqual(result["missing_credit_count"], 1)
            self.assertFalse(result["records"][0]["artist_join_allowed"])
            self.assertIsNone(result["records"][0]["exact_credit"]["fact"])

    def test_drop_missing_outcome_bad_dates_mixed_raw_and_native_credit_mismatch_rejected(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = _pack(root)
            with self.assertRaises(ValueError):
                project_native_sonic(
                    root, {**manifest, "sonic_captures": manifest["sonic_captures"][:1]}
                )
            manifest["sonic_captures"][0]["source_observed_at"] = "fabricated date"
            with self.assertRaises(ValueError):
                project_native_sonic(root, manifest)
            manifest["sonic_captures"][0]["source_observed_at"] = None
            path = root / f"raw/credits/{RECORDING}.json"
            payload = json.loads(path.read_text())
            payload["tags"] = [{"name": "NC association"}]
            _write(path, payload)
            manifest["credit_captures"][0].update(
                sha256=_binding(path)["sha256"], response_bytes=path.stat().st_size
            )
            with self.assertRaises(ValueError):
                project_native_sonic(root, manifest)
            del payload["tags"]
            payload["artist-credit"][0]["artist"]["id"] = OTHER
            _write(path, payload)
            manifest["credit_captures"][0].update(
                sha256=_binding(path)["sha256"], response_bytes=path.stat().st_size
            )
            with self.assertRaises(ValueError):
                project_native_sonic(root, manifest)

    def test_receipt_rehash_cannot_introduce_artist_summaries_or_hide_extra_raw(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _pack(root)
            projection = json.loads((root / "projection.json").read_text())
            projection["artist_medians"] = [{"artist": ARTIST, "invented": True}]
            _write(root / "projection.json", projection)
            receipt = json.loads((root / "receipt.json").read_text())
            receipt["files"]["projection.json"] = _binding(root / "projection.json")
            _write(root / "receipt.json", receipt)
            with self.assertRaisesRegex(ValueError, "raw source replay"):
                verify_native_sonic(root)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _pack(root)
            (root / "raw/credits/undeclared-mixed-source.json").write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "raw file set"):
                verify_native_sonic(root)

    def test_symlinked_raw_source_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _pack(root)
            path = root / f"raw/sonic/{RECORDING}.json"
            original = root / "outside-native-raw"
            path.rename(original)
            path.symlink_to(original)
            with self.assertRaisesRegex(ValueError, "symlink"):
                verify_native_sonic(root)

    def test_checked_in_pack_replays_all_selected_recordings_offline(self) -> None:
        projection = verify_native_sonic(Path("data/examples/native-sonic"))
        self.assertEqual(projection["selected_recordings"], 100)
        self.assertEqual(projection["state_counts"], {"available": 55, "missing_http_404": 45})
        self.assertEqual(projection["retained_source_date_count"], 30)
        self.assertEqual(projection["missing_source_date_count"], 70)
        self.assertEqual(projection["artist_genre_memberships"], [])
        self.assertFalse(projection["full_corpus_claim"])


if __name__ == "__main__":
    unittest.main()
