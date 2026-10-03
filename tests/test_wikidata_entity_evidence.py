"""Literal entity identity, admission, and frozen request-plan regression tests."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any, override

from opennoise.ingest.wikidata import entity_evidence as evidence

MBID = "a5a49da8-f65f-4402-a715-1648004f9f03"


def statement(value: object, *, rank: str = "normal") -> dict[str, Any]:
    """Build a literal source statement fixture."""
    return {
        "id": "Q1$native-statement",
        "rank": rank,
        "mainsnak": {"snaktype": "value", "datavalue": {"type": "string", "value": value}},
        "references": [{"snaks": {"P248": []}}],
    }


def native_entity() -> dict[str, Any]:
    """Build an exact identifier source entity fixture."""
    return {
        "id": "Q1",
        "type": "item",
        "labels": {"en": {"language": "en", "value": "native"}},
        "claims": {"P434": [statement(MBID)], "P136": [statement({"id": "Q2"})]},
    }


def native_pack(tmp_path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Write an isolated frozen response fixture."""
    (tmp_path / "raw").mkdir()
    body = json.dumps({"entities": {"Q1": native_entity()}}).encode()
    (tmp_path / "raw/artists-0000.json").write_bytes(body)
    selected = [{"artist_mbid": MBID, "wikidata_qid": "Q1", "name": "MusicBrainz native name"}]
    record = {
        "kind": "artists",
        "index": 0,
        "requested": ["Q1"],
        "admitted": True,
        "http_status": 200,
        "body_complete": True,
        "raw_path": "raw/artists-0000.json",
        "sha256": evidence.digest(body),
    }
    context = json.dumps({"entities": {"Q2": {"id": "Q2", "type": "item"}}}).encode()
    (tmp_path / "raw/context-0000.json").write_bytes(context)
    context_record = {
        "kind": "context",
        "index": 0,
        "requested": ["Q2"],
        "admitted": True,
        "http_status": 200,
        "body_complete": True,
        "raw_path": "raw/context-0000.json",
    }
    return selected, [record, context_record]


class EntityEvidenceTests(unittest.TestCase):
    """Bounded native claim and capture-plan behavior."""

    @override
    def setUp(self) -> None:
        """Create isolated disposable evidence fixture."""
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.tmp_path = Path(self.directory.name)

    def test_non_deprecated_claims_preserve_statement_evidence(self) -> None:
        """Verify the literal identity and replay contract."""
        entity = {"claims": {"P136": [statement("keep"), statement("drop", rank="deprecated")]}}
        claims = evidence.claims(entity, "P136")
        assert len(claims) == 1
        assert claims[0]["statement_id"] == "Q1$native-statement"
        assert claims[0]["reference_count"] == 1
        assert claims[0]["references_retained_in_raw"] is True

    def test_response_entity_identity_is_exact(self) -> None:
        """Verify the literal identity and replay contract."""
        with self.assertRaisesRegex(ValueError, "IDs differ"):
            evidence.entities(json.dumps({"entities": {"Q2": native_entity()}}).encode(), ["Q1"])
        with self.assertRaisesRegex(ValueError, "identity or type"):
            evidence.entities(
                json.dumps({"entities": {"Q1": {"id": "Q2", "type": "item"}}}).encode(), ["Q1"]
            )

    def test_exact_identifier_join_does_not_require_name_match(self) -> None:
        """Verify the literal identity and replay contract."""
        tmp_path = self.tmp_path
        selected, captures = native_pack(tmp_path)
        result = evidence.project(tmp_path, selected, captures)
        assert result["outcomes"] == {"exact_identity": 1}
        assert result["artists"][0]["name"] == "MusicBrainz native name"
        assert result["artists"][0]["labels"]["en"]["value"] == "native"
        assert evidence.context_plan(result) == ["Q2"]
        evidence.validate_capture_plan(tmp_path, selected, captures)

    def test_multiple_native_p434_values_are_quarantined(self) -> None:
        """Verify the literal identity and replay contract."""
        tmp_path = self.tmp_path
        selected, captures = native_pack(tmp_path)
        entity = native_entity()
        entity["claims"]["P434"].append(statement("804ccf06-6eed-434d-9145-d05dd7627b8c"))
        (tmp_path / captures[0]["raw_path"]).write_text(json.dumps({"entities": {"Q1": entity}}))
        result = evidence.project(tmp_path, selected, captures)
        assert result["outcomes"] == {"P434_not_unique_exact": 1}
        assert "claims" not in result["artists"][0]

    def test_forged_http_admission_is_rejected(self) -> None:
        """Verify the literal identity and replay contract."""
        tmp_path = self.tmp_path
        selected, captures = native_pack(tmp_path)
        captures[1]["http_status"] = 503
        with self.assertRaisesRegex(ValueError, "admission disagrees"):
            evidence.validate_capture_plan(tmp_path, selected, captures)

    def test_changed_context_request_is_rejected(self) -> None:
        """Verify the literal identity and replay contract."""
        tmp_path = self.tmp_path
        selected, captures = native_pack(tmp_path)
        captures[1]["requested"] = ["Q3"]
        with self.assertRaisesRegex(ValueError, "request plan differs"):
            evidence.validate_capture_plan(tmp_path, selected, captures)

    def test_malformed_identifier_is_quarantined(self) -> None:
        """Unhashable or non-UUID source values never create an inferred join."""
        entity = native_entity()
        entity["claims"]["P434"] = [statement({"id": "Q2"})]
        assert evidence.artist_identity_status(entity, MBID) == "P434_malformed"
        entity["claims"]["P434"] = [statement("not-a-uuid")]
        assert evidence.artist_identity_status(entity, MBID) == "P434_malformed"

    def test_self_rehashed_extra_file_is_not_approved(self) -> None:
        """The source receipt cannot admit an unrelated additional file."""
        expected = {
            "source-scan.json",
            "selection.json",
            "captures.json",
            "projection.json",
            "receipt.json",
        }
        with self.assertRaisesRegex(ValueError, "unapproved files"):
            evidence.verify_closed_capture_files(expected | {"unrelated.json"}, [])

    def test_unsafe_capture_path_fails_before_reading(self) -> None:
        """Native capture identities determine their exact raw paths."""
        record = {
            "kind": "artists",
            "index": 0,
            "raw_path": "../outside.json",
            "bytes": 1,
            "started_utc": "2026-10-03T00:00:00+00:00",
            "finished_utc": "2026-10-03T00:00:01+00:00",
        }
        with self.assertRaisesRegex(ValueError, "capture path"):
            evidence.verify_capture_receipts(self.tmp_path, [record])

    def test_reversed_capture_times_fail_before_reading(self) -> None:
        """Reject a forged ledger with completion preceding request start."""
        record = {
            "kind": "artists",
            "index": 0,
            "raw_path": "raw/artists-0000.json",
            "bytes": 1,
            "started_utc": "2026-10-03T00:00:01+00:00",
            "finished_utc": "2026-10-03T00:00:00+00:00",
        }
        with self.assertRaisesRegex(ValueError, "finish precedes"):
            evidence.verify_capture_receipts(self.tmp_path, [record])

    def test_batch_streamed_projection_matches_complete_canonical_bytes(self) -> None:
        """Low-memory replay must verify the same complete projection, not omit rows."""
        selected, captures = native_pack(self.tmp_path)
        expected = evidence.project(self.tmp_path, selected, captures)
        streamed = evidence.streaming_projection(self.tmp_path, selected, captures)
        assert evidence.json_digest(streamed) == evidence.json_digest(expected)
        assert evidence.context_plan_from_captures(
            self.tmp_path, selected, captures
        ) == evidence.context_plan(expected)
        assert list(streamed["artists"]) == expected["artists"]
