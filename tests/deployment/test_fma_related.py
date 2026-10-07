"""Reject incomplete or tampered suggestion packs at the catalog boundary."""

import json
import tempfile
import unittest
from collections import Counter
from pathlib import Path
from typing import Any

from opennoise.common import sha256_file
from opennoise.deployment.fma_related import export_related_music
from opennoise.ml.fma_inference import EVALUATION_SHA256, FEATURE_RECEIPT_SHA256


def pack(root: Path, rows: list[list[Any]]) -> None:
    """Bind a minimal native query fixture."""
    root.mkdir()
    shard = root / "0.json"
    shard.write_text(json.dumps({"rows": rows}))
    digest, size = sha256_file(shard)
    (root / "manifest.json").write_text(
        json.dumps(
            {
                "revision": "fma-frozen-descriptor-neighbors-v1",
                "labels_used": False,
                "musical_relevance_established": False,
                "provenance": {
                    "evaluation_sha256": EVALUATION_SHA256,
                    "feature_receipt_sha256": FEATURE_RECEIPT_SHA256,
                },
                "track_id_span": 500,
                "neighbor_count": 6,
                "counts": {
                    "queries": len(rows),
                    "supported_queries": sum(row[2] is None for row in rows),
                    "abstentions": dict(Counter(row[2] for row in rows if row[2])),
                },
                "method": "frozen descriptor comparison",
                "files": {"0.json": {"sha256": digest, "bytes": size}},
            }
        )
    )


class RelatedImportTests(unittest.TestCase):
    def test_changed_model_source_contract_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source, output = Path(temporary) / "source", Path(temporary) / "output"
            pack(source, [[1, [], "missing_feature_row"]])
            path = source / "manifest.json"
            data = json.loads(path.read_bytes())
            data["provenance"]["evaluation_sha256"] = "0" * 64
            path.write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError, "frozen source contract"):
                export_related_music(source, output, {}, {1})
            self.assertFalse(output.exists())

    def test_invalid_abstention_and_false_coverage_fail_before_copy(self) -> None:
        for reason in (None, "unknown_reason", "missing_feature_row"):
            with self.subTest(reason=reason), tempfile.TemporaryDirectory() as temporary:
                source, output = Path(temporary) / "source", Path(temporary) / "output"
                pack(source, [[1, [], reason]])
                if reason == "missing_feature_row":
                    path = source / "manifest.json"
                    data = json.loads(path.read_bytes())
                    data["counts"]["supported_queries"] = 1
                    path.write_text(json.dumps(data))
                with self.assertRaises(ValueError):
                    export_related_music(source, output, {}, {1})
                self.assertFalse(output.exists())

    def test_complete_native_queries_and_abstentions_survive(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source, output = Path(temporary) / "source", Path(temporary) / "output"
            pack(source, [[1, [2], None], [2, [], "missing_feature_row"]])
            files = {}
            export_related_music(source, output, files, {1, 2})
            self.assertEqual(
                (source / "0.json").read_bytes(), (output / "related-tracks/0.json").read_bytes()
            )
            self.assertIn("related-tracks/manifest.json", files)

    def test_missing_query_unknown_neighbor_and_self_link_fail_before_copy(self) -> None:
        for rows in (
            [[1, [2], None]],
            [[1, [99], None], [2, [], "missing_feature_row"]],
            [[1, [1], None], [2, [], "missing_feature_row"]],
        ):
            with self.subTest(rows=rows), tempfile.TemporaryDirectory() as temporary:
                source, output = Path(temporary) / "source", Path(temporary) / "output"
                pack(source, rows)
                with self.assertRaises(ValueError):
                    export_related_music(source, output, {}, {1, 2})
                self.assertFalse(output.exists())

    def test_tampered_bytes_fail_before_copy(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source, output = Path(temporary) / "source", Path(temporary) / "output"
            pack(source, [[1, [2], None], [2, [], "missing_feature_row"]])
            with (source / "0.json").open("ab") as stream:
                stream.write(b" ")
            with self.assertRaisesRegex(ValueError, "binding"):
                export_related_music(source, output, {}, {1, 2})
            self.assertFalse(output.exists())
