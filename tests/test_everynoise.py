import hashlib
import tempfile
import unittest
from pathlib import Path

from pydantic import ValidationError

from musix.adapters.everynoise import (
    QUINT_SOURCE,
    SourceSpec,
    SourceVerificationError,
    adapt_quint_html,
    adapt_watch_csv,
    store_verified_bytes,
)


def _source(*, adapter: str, raw: bytes, records: int = 1) -> SourceSpec:
    return SourceSpec.model_validate(
        {
            "source_id": "test-source",
            "namespace": "test",
            "snapshot": "test-snapshot",
            "url": "https://example.invalid/source",
            "expected_bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "expected_records": records,
            "adapter": adapter,
        }
    )


class EveryNoiseAdapterTests(unittest.TestCase):
    def test_html_keeps_only_catalog_and_layout_fields(self) -> None:
        raw = (
            b'<div id=item1 preview_url="https://p.scdn.co/private" '
            b'class="genre scanme" style="color: #AD8907; top: 4997px; left: 783px; '
            b'font-size: 160%" onclick="playx(spotify-secret)">pop'
            b'<a href="https://spotify.example/item">nav</a> </div>'
        )
        result = adapt_quint_html(raw, _source(adapter="enao_html_map_v1", raw=raw))
        self.assertEqual(result.accepted_count, 1)
        self.assertEqual(result.quarantined_count, 0)
        self.assertEqual(result.records[0].catalog.name, "pop")
        self.assertEqual(result.records[0].layout.x_px, 783)
        self.assertEqual(result.records[0].layout.y_px, 4997)
        serialized = result.catalog_jsonl() + result.layout_jsonl()
        self.assertNotIn(b"preview", serialized)
        self.assertNotIn(b"spotify", serialized.lower())
        self.assertNotIn(b"onclick", serialized)

    def test_html_quarantines_malformed_and_conflicting_rows(self) -> None:
        raw = (
            b'<div id=item1 class="genre scanme" style="color: #ad8907; top: 2px; '
            b'left: 1px; font-size: 100%">pop</div>'
            b'<div id=item1 class="genre scanme" style="color: #ad8907; top: 3px; '
            b'left: 1px; font-size: 100%">rock</div>'
            b'<div id=item3 class="genre scanme" style="color: broken">jazz</div>'
        )
        result = adapt_quint_html(raw, _source(adapter="enao_html_map_v1", raw=raw, records=3))
        self.assertEqual(result.accepted_count, 1)
        self.assertEqual(result.quarantined_count, 2)
        self.assertIn("conflicting", result.quarantine[0].reason)
        self.assertIn("missing required", result.quarantine[1].reason)
        self.assertNotIn("rock", result.quarantine_jsonl().decode())

    def test_csv_parses_coordinates_and_quarantines_bad_rows(self) -> None:
        raw = b"genre,x,y,hex_colour\npiano blues,911,3891,#66882d\nbroken,9999,0,#nothex\n"
        result = adapt_watch_csv(raw, _source(adapter="enao_watch_csv_v1", raw=raw, records=2))
        self.assertEqual(result.accepted_count, 1)
        self.assertEqual(result.quarantined_count, 1)
        self.assertEqual(result.records[0].catalog.slug, "piano-blues")
        self.assertIsNone(result.records[0].layout.font_size_percent)

    def test_size_and_checksum_are_verified_before_parsing(self) -> None:
        with self.assertRaises(SourceVerificationError):
            adapt_quint_html(b"changed", QUINT_SOURCE)

    def test_verified_vault_is_content_addressed_and_idempotent(self) -> None:
        raw = b"genre,x,y,hex_colour\nblues,1,2,#123abc\n"
        source = _source(adapter="enao_watch_csv_v1", raw=raw)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = store_verified_bytes(raw, source, root)
            second = store_verified_bytes(raw, source, root)
            self.assertEqual(first, root / source.sha256)
            self.assertEqual(first, second)
            self.assertEqual(first.read_bytes(), raw)

    def test_source_contract_rejects_non_local_policy(self) -> None:
        value = QUINT_SOURCE.model_dump(mode="json")
        value["local_only"] = False
        with self.assertRaises(ValidationError):
            SourceSpec.model_validate(value)


if __name__ == "__main__":
    unittest.main()
