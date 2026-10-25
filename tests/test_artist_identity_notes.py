from __future__ import annotations

import base64
import gzip
import hashlib
import json
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING
from unittest import mock

from opennoise.pipeline import artist_identity_notes as notes
from opennoise.pipeline.catalog_demo import write

if TYPE_CHECKING:
    from collections.abc import Iterator

QUERY = "00000000-0000-0000-0000-000000000001"
FIRST = "00000000-0000-0000-0000-000000000002"
SECOND = "00000000-0000-0000-0000-000000000003"
LONG = "00000000-0000-0000-0000-000000000004"
LITERAL = "00000000-0000-0000-0000-000000000005"


def _row(artist: str, name: str, comment: str) -> dict[str, object]:
    return {
        "artist_mbid": artist,
        "reference_mbid": QUERY,
        "name": name,
        "score": 15,
        "comment": comment,
        "type": "Person",
        "gender": None,
    }


@contextmanager
def _fixture(rows: list[dict[str, object]]) -> Iterator[Path]:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        baseline = root / "baseline.gz"
        artists = [
            {"id": i, "name": name}
            for i, name in [
                (QUERY, "Query"),
                (FIRST, "Same"),
                (SECOND, "Same"),
                (LONG, "Long"),
                (LITERAL, "Literal"),
            ]
        ]
        baseline.write_bytes(gzip.compress(json.dumps({"artists": artists}).encode(), mtime=0))
        body = json.dumps(rows).encode()
        record = {
            "body_base64": base64.b64encode(body).decode(),
            "bytes": len(body),
            "sha256": hashlib.sha256(body).hexdigest(),
            "reference": QUERY,
            "status": 200,
            "captured_utc": "2026-10-25T00:00:00Z",
            "url": "https://example.invalid/fixture-no-request",
        }
        packet = root / "packet.gz"
        packet.write_bytes(gzip.compress((json.dumps(record) + "\n").encode(), mtime=0))
        with mock.patch.multiple(
            notes,
            SNAPSHOT="baseline.gz",
            SNAPSHOT_SHA256=hashlib.sha256(baseline.read_bytes()).hexdigest(),
            PACKETS=(("packet.gz", hashlib.sha256(packet.read_bytes()).hexdigest()),),
        ):
            yield root


class IdentityNoteBoundaryTests(unittest.TestCase):
    def test_conflict_abstains_without_majority_and_preserves_literal_text(self) -> None:
        literal = '<img src="local-only" onerror="window.noteRan=true"> µ'
        rows = [
            _row(FIRST, "Same", "left"),
            _row(FIRST, "Same", "left"),
            _row(FIRST, "Same", "right"),
            _row(SECOND, "Same", "other artist"),
            _row(LONG, "Long", "x" * (notes.MAX_COMMENT_CHARS + 1)),
            _row(LITERAL, "Literal", literal),
        ]
        with _fixture(rows) as root:
            payload, report = notes.project(root)
        self.assertNotIn(FIRST, payload["notes"])
        self.assertEqual(payload["notes"][SECOND], "other artist")
        self.assertEqual(payload["notes"][LITERAL], literal)
        self.assertNotIn(LONG, payload["notes"])
        ledger = {row["id"]: row for row in report["identity_ledger"]}
        self.assertEqual(ledger[FIRST]["reason"], "conflicting_comments")
        self.assertEqual(ledger[LONG]["reason"], "invalid_comment")
        self.assertEqual(ledger[QUERY]["reason"], "no_matching_observation")
        self.assertEqual(len(ledger), 5)
        self.assertEqual(payload["policy"]["comment_max_characters"], 500)
        self.assertEqual(
            payload["policy"]["excluded_character_ranges_inclusive"], [[0, 31], [127, 127]]
        )

    def test_identity_guards_do_not_convert_aliases_or_invalid_scores_into_notes(self) -> None:
        names = {QUERY: "Query", FIRST: "Same"}
        cases = [
            ({"reference_mbid": SECOND}, "missing_or_different_reference"),
            ({"artist_mbid": SECOND}, "outside_native_gallery"),
            ({"score": True}, "invalid_score"),
            ({"score": "15"}, "invalid_score"),
            ({"score": float("nan")}, "invalid_score"),
            ({"score": 0}, "invalid_score"),
            ({"artist_mbid": QUERY, "name": "Query"}, "self_row"),
            ({"name": None}, "missing_name"),
            ({"name": "Alias"}, "different_native_name"),
        ]
        for change, reason in cases:
            with self.subTest(change=change):
                self.assertEqual(
                    notes.observation_reason(
                        {**_row(FIRST, "Same", "note"), **change}, QUERY, names
                    ),
                    reason,
                )
        self.assertIsNone(
            notes.observation_reason(_row(FIRST, "\uff33\uff21\uff2d\uff25", "note"), QUERY, names)
        )
        for value in ["", " ", "line\nbreak", "tab\tstop", "nul\x00", "delete\x7f"]:
            self.assertFalse(notes.valid_comment(value))

    def test_undeclared_or_nested_capture_fields_fail_closed(self) -> None:
        names = {QUERY: "Query", FIRST: "Same"}
        for row in [
            [],
            "text",
            {**_row(FIRST, "Same", "note"), "lyrics": "not permitted"},
            {**_row(FIRST, "Same", "note"), "comment": {"text": "nested"}},
        ]:
            with self.subTest(row=row), self.assertRaisesRegex(ValueError, "undeclared"):
                notes.observation_reason(row, QUERY, names)

    def test_repinning_a_fabricated_note_cannot_bypass_raw_replay(self) -> None:
        with _fixture([_row(FIRST, "Same", "source note")]) as root:
            payload, _ = notes.project(root)
            target = root / notes.NOTES
            write(target, payload)
            spec = {
                "path": notes.NOTES,
                "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
                "bytes": target.stat().st_size,
                "counts": payload["counts"],
            }
            self.assertEqual(notes.load(root, spec), {FIRST: "source note"})
            payload["notes"][FIRST] = "invented biography"
            write(target, payload)
            spec.update(
                sha256=hashlib.sha256(target.read_bytes()).hexdigest(), bytes=target.stat().st_size
            )
            with self.assertRaisesRegex(ValueError, "do not replay"):
                notes.load(root, spec)
