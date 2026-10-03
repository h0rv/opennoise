"""Native pagination, counts and exact credit admission cannot create musical relevance."""

from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path
from typing import TYPE_CHECKING

from opennoise.common import canonical_json
from opennoise.serving.metadata.recording_facts import recording_source_url
from opennoise.serving.metadata.selected_recording_catalog import (
    expected_core_captures,
    project_browse,
)

if TYPE_CHECKING:
    from typing import Any

ARTIST = "00000000-0000-0000-0000-000000000001"
OTHER = "00000000-0000-0000-0000-000000000002"
RECORDING = "00000000-0000-0000-0000-000000000003"


def recording(artist: str = ARTIST) -> dict[str, Any]:
    """Use literal core-only credits, independent of display names."""
    return {
        "id": RECORDING,
        "title": "Native literal",
        "artist-credit": [{"artist": {"id": artist, "name": "same name"}}],
    }


def page(rows: list[dict[str, Any]], count: int = 999, offset: int = 0) -> bytes:
    """Retain native advertised count independently of the returned first page."""
    return canonical_json(
        {"recording-count": count, "recording-offset": offset, "recordings": rows}
    )


class SelectedCatalogTests(unittest.TestCase):
    def test_first_page_retains_full_denominator_and_unfetched_count(self) -> None:
        result = project_browse(page([recording()]), ARTIST)
        self.assertEqual(result["advertised_recording_count"], 999)
        self.assertEqual(result["unfetched_recording_count"], 998)
        self.assertFalse(result["complete_catalog_fetched"])
        self.assertEqual(result["representativeness"], "not_assessed_native_first_page")

    def test_same_name_credit_mismatch_does_not_join(self) -> None:
        result = project_browse(page([recording(OTHER)]), ARTIST)
        self.assertEqual(result["recording_mbids"], [])
        self.assertEqual(len(result["rejected_rows"]), 1)

    def test_mixed_row_and_missing_uuid_are_excluded(self) -> None:
        mixed = recording()
        mixed["tags"] = [{"name": "fabricated"}]
        result = project_browse(page([mixed, {"title": "Missing ID"}]), ARTIST)
        self.assertEqual(result["recording_mbids"], [])
        self.assertEqual(len(result["rejected_rows"]), 2)

    def test_negative_or_bool_counts_and_wrong_offset_fail(self) -> None:
        for body in [
            page([], count=-1),
            page([], count=True),
            page([], offset=2),
            page([recording()], count=0),
        ]:
            with self.subTest(body=body), self.assertRaises(ValueError):
                project_browse(body, ARTIST)

    def test_extra_page_and_ambiguous_envelope_fail(self) -> None:
        with self.assertRaises(ValueError):
            project_browse(page([recording(), recording(), recording()]), ARTIST)
        payload = {
            "recording-count": 1,
            "recording-offset": 0,
            "recordings": [recording()],
            "genres": [],
        }
        with self.assertRaises(ValueError):
            project_browse(canonical_json(payload), ARTIST)

    def test_tampered_credit_or_supplementary_fields_cannot_be_admitted(self) -> None:
        original = project_browse(page([recording()], count=1), ARTIST)
        self.assertEqual(original["recording_mbids"], [RECORDING])
        forged = recording()
        forged["artist-credit"][0]["artist"]["id"] = OTHER
        changed = project_browse(page([forged], count=1), ARTIST)
        self.assertFalse(changed["complete_catalog_fetched"])
        self.assertEqual(changed["recording_mbids"], [])


class NativeLookupReplayTests(unittest.TestCase):
    def test_native_mixed_response_cannot_remain_accepted_after_self_rehash(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            path = directory / "native.body"
            body = canonical_json(recording())
            path.write_bytes(body)
            native = {
                "artist_mbid": ARTIST,
                "recording_mbid": RECORDING,
                "url": recording_source_url(RECORDING),
                "fetched_at": "2026-10-03T00:00:00+00:00",
                "status_code": 200,
                "outcome": "complete_http_200",
                "path": "native.body",
                "bytes": len(body),
                "sha256": hashlib.sha256(body).hexdigest(),
            }
            accepted = expected_core_captures(directory, [native])
            self.assertEqual(accepted[0]["outcome"], "accepted_core")
            mixed = recording()
            mixed["tags"] = [{"name": "unapproved source field"}]
            body = canonical_json(mixed)
            path.write_bytes(body)
            native.update(bytes=len(body), sha256=hashlib.sha256(body).hexdigest())
            rebuilt = expected_core_captures(directory, [native])
            self.assertEqual(rebuilt[0]["outcome"], "unapproved_payload")
            self.assertNotEqual(accepted, rebuilt)
