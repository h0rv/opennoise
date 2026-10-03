"""Verify source-bound transport guards without making network requests."""

from __future__ import annotations

import hashlib
import io
import json
import tempfile
import unittest
from http import HTTPStatus
from http.client import HTTPMessage
from pathlib import Path
from typing import Any, override
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError, URLError
from urllib.request import Request

from opennoise.serving.metadata import listening_destinations as listening
from opennoise.serving.metadata import recording_facts as facts
from scripts import audit_recording_provider_transport as auditor

ARTIST = "00000000-0000-0000-0000-000000000001"
RECORDINGS = (
    "00000000-0000-0000-0000-000000000002",
    "00000000-0000-0000-0000-000000000003",
)
URL_ID = "00000000-0000-0000-0000-000000000004"
URL = "https://open.spotify.com/track/0OIl0OIl0OIl0OIl0OIl01"


def write_json(path: Path, value: object) -> bytes:
    """Write a small native fixture and return the exact serialized bytes."""
    body = (json.dumps(value, indent=2) + "\n").encode()
    path.write_bytes(body)
    return body


class ProviderTransportTests(unittest.TestCase):
    @override
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.pack = self.root / "listening"
        self.facts = self.root / "facts"
        self.pack.mkdir()
        (self.facts / "raw").mkdir(parents=True)
        selection = {
            "revision": facts.REVISION,
            "selection_method": "fixture exact credited recording roster",
            "source_projection_sha256": "a" * 64,
            "artists": [
                {"artist_mbid": ARTIST, "name": "Artist", "recording_mbids": list(RECORDINGS)}
            ],
        }
        selection_body = write_json(self.facts / "selection.json", selection)
        credit_captures: list[dict[str, Any]] = []
        listening_captures: list[dict[str, Any]] = []
        for i, recording in enumerate(RECORDINGS):
            core = {
                "id": recording,
                "title": f"Track {i}",
                "artist-credit": [{"artist": {"id": ARTIST, "name": "Artist"}}],
            }
            body = write_json(self.facts / "raw" / (recording + ".json"), core)
            credit_captures.append(
                {
                    "artist_mbid": ARTIST,
                    "recording_mbid": recording,
                    "url": facts.recording_source_url(recording),
                    "fetched_at": "2026-10-03T00:00:00Z",
                    "status_code": 200,
                    "outcome": "accepted_core",
                    "path": "raw/" + recording + ".json",
                    "sha256": hashlib.sha256(body).hexdigest(),
                    "bytes": len(body),
                }
            )
            source = {
                **core,
                "relations": [
                    {
                        "target-type": "url",
                        "type": "free streaming",
                        "url": {"id": URL_ID, "resource": URL},
                    }
                ]
                if i == 0
                else [],
            }
            source_body = write_json(self.pack / f"recording-{i:03d}.json", source)
            listening_captures.append(
                {
                    "artist": ARTIST,
                    "recording": recording,
                    "url": f"https://musicbrainz.org/ws/2/recording/{recording}?inc=artist-credits+url-rels&fmt=json",
                    "path": f"recording-{i:03d}.json",
                    "status": 200,
                    "fetched_at": "2026-10-03T00:00:00Z",
                    "sha256": hashlib.sha256(source_body).hexdigest(),
                    "bytes": len(source_body),
                }
            )
        projection = facts.replay_recording_facts(self.facts, selection, credit_captures)
        projection_body = write_json(self.facts / "recording-facts.json", projection)
        write_json(
            self.facts / "receipt.json",
            {
                "revision": facts.REVISION,
                "license": facts.LICENSE,
                "license_url": facts.LICENSE_URL,
                "selection_sha256": hashlib.sha256(selection_body).hexdigest(),
                "projection_sha256": hashlib.sha256(projection_body).hexdigest(),
                "max_requests": facts.MAX_REQUESTS,
                "max_response_bytes": facts.MAX_BYTES,
                "scope": "portable_core_metadata_only",
                "metadata_only": True,
                "tags_or_genres_requested": False,
                "captures": credit_captures,
                "request_count": len(credit_captures),
                "response_bytes": sum(row["bytes"] for row in credit_captures),
            },
        )
        write_json(
            self.pack / "receipt.json",
            {
                "revision": listening.REVISION,
                "selection": [[ARTIST, recording] for recording in RECORDINGS],
                "captures": listening_captures,
            },
        )
        write_json(
            self.pack / "listening-destinations.json", listening.replay(self.pack, self.facts)
        )

    def test_ascii_base62_ids_and_only_literal_track_urls_are_allowed(self) -> None:
        self.assertTrue(auditor.permitted_url(URL))
        for url in (
            URL + "?si=x",
            URL + "#fragment",
            URL + "\n",
            URL.replace("open.spotify.com", "evil.example"),
            URL.replace("/track/", "/album/"),
            URL.replace("https://", "http://"),
            URL.replace("open.spotify.com", "user@open.spotify.com"),
            URL.replace("open.spotify.com", "open.spotify.com:443"),
            URL.replace("0", "\uff10"),
        ):
            with self.subTest(url=url):
                self.assertFalse(auditor.permitted_url(url))

    def test_closed_roster_and_license_replay_preserve_missing_destinations(self) -> None:
        links = auditor.load_bound_destinations(self.pack, self.facts)
        self.assertEqual(len(links), 1)
        self.assertEqual(links[0]["recording_mbid"], RECORDINGS[0])
        listing = json.loads((self.pack / "listening-destinations.json").read_bytes())
        self.assertEqual(listing["eligible_recordings"], 2)
        self.assertEqual(listing["recordings"][1]["destinations"], [])
        receipt_path = self.facts / "receipt.json"
        receipt = json.loads(receipt_path.read_bytes())
        receipt["license"] = "unverified"
        write_json(receipt_path, receipt)
        with self.assertRaisesRegex(ValueError, "receipt boundary"):
            auditor.load_bound_destinations(self.pack, self.facts)

    def test_path_traversal_is_rejected_before_capture_open(self) -> None:
        receipt_path = self.pack / "receipt.json"
        receipt = json.loads(receipt_path.read_bytes())
        receipt["captures"][0]["path"] = "../outside.json"
        write_json(receipt_path, receipt)
        original = Path.read_bytes
        opened = []

        def recorded(path: Path) -> bytes:
            opened.append(path)
            return original(path)

        with (
            patch.object(Path, "read_bytes", recorded),
            self.assertRaisesRegex(ValueError, "noncanonical"),
        ):
            auditor.load_bound_destinations(self.pack, self.facts)
        self.assertEqual(opened, [receipt_path])

    def test_missing_extra_and_duplicate_source_rows_are_rejected(self) -> None:
        listing_path = self.pack / "listening-destinations.json"
        listing = json.loads(listing_path.read_bytes())
        for rows in (listing["recordings"][:1], listing["recordings"] * 2):
            with self.subTest(rows=len(rows)):
                write_json(listing_path, {**listing, "recordings": rows})
                with self.assertRaises(ValueError):
                    auditor.load_bound_destinations(self.pack, self.facts)
        write_json(listing_path, listing)
        extra = self.pack / "unlisted.json"
        extra.write_text("{}", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "not closed"):
            auditor.load_bound_destinations(self.pack, self.facts)
        extra.unlink()
        receipt_path = self.pack / "receipt.json"
        receipt = json.loads(receipt_path.read_bytes())
        receipt["captures"][1] = receipt["captures"][0]
        write_json(receipt_path, receipt)
        with self.assertRaisesRegex(ValueError, "duplicate recording capture"):
            auditor.load_bound_destinations(self.pack, self.facts)

    def test_tampered_source_bytes_and_symlinked_capture_are_rejected(self) -> None:
        source = self.pack / "recording-000.json"
        original = source.read_bytes()
        source.write_bytes(original + b" ")
        with self.assertRaisesRegex(ValueError, "byte binding"):
            auditor.load_bound_destinations(self.pack, self.facts)
        source.unlink()
        external = self.root / "external.json"
        external.write_bytes(original)
        source.symlink_to(external)
        with self.assertRaisesRegex(ValueError, "regular files only"):
            auditor.load_bound_destinations(self.pack, self.facts)

    def test_redirects_are_rejected_before_a_second_request(self) -> None:
        for target in (URL, URL.replace("0OIl", "abcd"), "https://evil.example"):
            with self.subTest(target=target), self.assertRaises(HTTPError):
                auditor.RestrictedRedirect().redirect_request(
                    Request(URL), io.BytesIO(), 302, "Found", HTTPMessage(), target
                )

    def test_transport_success_failure_and_redirect_never_verify_playback(self) -> None:
        response = MagicMock()
        response.status = HTTPStatus.OK
        response.geturl.return_value = URL
        opener = MagicMock()
        opener.open.return_value.__enter__.return_value = response
        with patch.object(auditor, "build_opener", return_value=opener):
            result = auditor.check_transport(URL)
        self.assertTrue(result["transport_reachable"])
        self.assertFalse(result["playback_verified"])
        self.assertIn("unverified", result["availability"])
        opener.open.assert_called_once()
        self.assertEqual(opener.open.call_args.args[0].get_method(), "HEAD")
        for failure in (HTTPError(URL, 302, "Found", HTTPMessage(), None), URLError("timeout")):
            with self.subTest(failure=type(failure).__name__):
                opener.open.side_effect = failure
                with patch.object(auditor, "build_opener", return_value=opener):
                    result = auditor.check_transport(URL)
                self.assertFalse(result["transport_reachable"])
                self.assertFalse(result["playback_verified"])
                self.assertIn("unverified", result["availability"])

    def test_existing_report_is_rejected_before_transport(self) -> None:
        with (
            patch.object(auditor, "check_transport") as transport,
            self.assertRaises(FileExistsError),
        ):
            auditor.audit(self.pack, self.facts, self.root)
        transport.assert_not_called()

    def test_uncredited_raw_recording_is_rejected_after_byte_rebinding(self) -> None:
        source_path = self.pack / "recording-000.json"
        source = json.loads(source_path.read_bytes())
        source["artist-credit"][0]["artist"]["id"] = URL_ID
        body = write_json(source_path, source)
        receipt_path = self.pack / "receipt.json"
        receipt = json.loads(receipt_path.read_bytes())
        receipt["captures"][0].update(sha256=hashlib.sha256(body).hexdigest(), bytes=len(body))
        write_json(receipt_path, receipt)
        with self.assertRaisesRegex(ValueError, "exact artist credit"):
            auditor.load_bound_destinations(self.pack, self.facts)

    def test_non_free_source_relation_is_rejected_after_native_replay(self) -> None:
        source_path = self.pack / "recording-000.json"
        source = json.loads(source_path.read_bytes())
        source["relations"][0]["type"] = "streaming"
        body = write_json(source_path, source)
        receipt_path = self.pack / "receipt.json"
        receipt = json.loads(receipt_path.read_bytes())
        receipt["captures"][0].update(sha256=hashlib.sha256(body).hexdigest(), bytes=len(body))
        write_json(receipt_path, receipt)
        write_json(
            self.pack / "listening-destinations.json", listening.replay(self.pack, self.facts)
        )
        with self.assertRaisesRegex(ValueError, "free-streaming"):
            auditor.load_bound_destinations(self.pack, self.facts)

    def test_unsafe_transport_url_is_rejected_without_request(self) -> None:
        with (
            patch.object(auditor, "build_opener") as opener,
            self.assertRaisesRegex(ValueError, "allowlist"),
        ):
            auditor.check_transport("file:///etc/passwd")
        opener.assert_not_called()
