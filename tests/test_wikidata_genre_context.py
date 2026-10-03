"""Typed native vocabulary and lossless compressed custody regression tests."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any, override

import zstandard

from opennoise.ingest.wikidata import genre_context as context
from opennoise.ingest.wikidata.entity_evidence import digest, write


def statement(qid: str) -> dict[str, Any]:
    """Return a literal native wikibase entity statement fixture."""
    return {
        "id": "Q1$source",
        "rank": "normal",
        "mainsnak": {
            "snaktype": "value",
            "datavalue": {"type": "wikibase-entityid", "value": {"id": qid}},
        },
    }


class GenreContextTests(unittest.TestCase):
    """Preserve literal property roles, coverage gaps and raw transport custody."""

    @override
    def setUp(self) -> None:
        """Write an isolated native-response fixture."""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / "raw").mkdir()
        native = {
            "entities": {
                "Q1": {
                    "id": "Q1",
                    "type": "item",
                    "claims": {"P31": [statement("Q999")], "P279": [statement("Q2")]},
                }
            }
        }
        self.body = json.dumps(native).encode()
        compressed = zstandard.ZstdCompressor().compress(self.body)
        (self.root / "raw/genres-000.json.zst").write_bytes(compressed)
        self.record = {
            "phase": "genres",
            "index": 0,
            "requested": ["Q1"],
            "endpoint": context.ENDPOINT,
            "params": {
                "action": "wbgetentities",
                "ids": "Q1",
                "props": "claims|labels",
                "languages": context.LANGUAGES,
                "format": "json",
                "maxlag": "5",
            },
            "started_utc": "2026-10-03T00:00:00+00:00",
            "finished_utc": "2026-10-03T00:00:01+00:00",
            "raw_path": "raw/genres-000.json.zst",
            "admitted": True,
            "body_complete": True,
            "http_status": 200,
            "bytes": len(self.body),
            "sha256": digest(self.body),
            "compressed_bytes": len(compressed),
            "compressed_sha256": digest(compressed),
        }
        write(self.root / "raw/genres-000.receipt.json", self.record)

    def test_p31_is_not_a_parent_or_similarity_edge(self) -> None:
        """Only native P279 statements enter the outward parent plan."""
        projected = context.project(self.root, ["Q1"], [self.record])
        assert context.parents(projected) == ["Q2"]
        assert projected["entities"]["Q1"]["claims"]["P31"][0]["datavalue"]["value"] == {
            "id": "Q999"
        }

    def test_unavailable_observed_labels_remain_explicit(self) -> None:
        """Every original observed genre remains in the denominator."""
        projected = context.project(self.root, ["Q1", "Q3"], [self.record])
        assert projected["entities"]["Q3"]["status"] == "response_unavailable"
        assert projected["entities"]["Q3"]["labels"] == {}
        assert projected["observed_P136_qids"] == ["Q1", "Q3"]

    def test_compressed_capture_roundtrip_checks_exact_native_bytes(self) -> None:
        """Lossless compression retains independently hashed original body bytes."""
        context.verify_capture(self.root, self.record, "raw/genres-000")

    def test_changed_original_hash_is_rejected(self) -> None:
        """Re-hashing a ledger cannot alter the expected original native body."""
        self.record["sha256"] = "0" * 64
        (self.root / "raw/genres-000.receipt.json").write_text(json.dumps(self.record))
        with self.assertRaisesRegex(ValueError, "decompressed native bytes"):
            context.verify_capture(self.root, self.record, "raw/genres-000")

    def test_successful_json_with_http_failure_is_not_admitted(self) -> None:
        """A parsable error-status body supplies no factual source entity."""
        self.record["http_status"] = 503
        assert context.capture_admission(self.record, self.body) is False

    def test_every_noise_identifier_is_not_a_consumed_property(self) -> None:
        """Unconsumed external metadata in full native snapshots stays outside features."""
        native = json.loads(self.body)
        native["entities"]["Q1"]["claims"]["P9881"] = [statement("Q99")]
        body = json.dumps(native).encode()
        (self.root / "raw/genres-000.json.zst").write_bytes(
            zstandard.ZstdCompressor().compress(body)
        )
        projected = context.project(self.root, ["Q1"], [self.record])
        assert set(projected["entities"]["Q1"]["claims"]) == {"P31", "P279"}
        assert context.parents(projected) == ["Q2"]
