"""Native taxonomy replay, optional export boundaries and rehashed tamper rejection."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from opennoise.common import canonical_json, sha256_file
from opennoise.pipeline.portable_taxonomy import (
    build_portable_taxonomy,
    validate_portable_taxonomy,
)

ROOT = Path(__file__).resolve().parents[2]


class PortableTaxonomyTests(unittest.TestCase):
    def test_all_source_nodes_replay_deterministically_with_cold_abstentions(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            first, second = Path(temporary) / "first", Path(temporary) / "second"
            receipt = build_portable_taxonomy(ROOT, first)
            self.assertEqual(receipt, build_portable_taxonomy(ROOT, second))
            self.assertEqual(receipt, validate_portable_taxonomy(ROOT, first))
            data = json.loads((first / "data.json").read_bytes())
            graph = json.loads((first / "graph.json").read_bytes())
            self.assertEqual(len(data["genres"]), 1000)
            self.assertEqual(data["counts"]["positioned"] + data["counts"]["unpositioned"], 1000)
            self.assertGreater(data["counts"]["isolated"], 0)
            self.assertEqual(graph["evaluation"]["all_node_fold_denominator"], 5000)
            self.assertFalse(data["scope"]["artist_membership_inference"])
            self.assertFalse(data["scope"]["across_component_semantics"])
            self.assertFalse(data["scope"]["independent_musical_validation"])
            self.assertTrue(data["scope"]["selection_possibly_truncated"])
            self.assertEqual(
                json.loads((first / "artists/data.json").read_bytes())["revision"],
                "open-foundation-portable-v1",
            )
            for name in receipt["files_sha256"]:
                self.assertEqual((first / name).read_bytes(), (second / name).read_bytes())
            with self.assertRaises(FileExistsError):
                build_portable_taxonomy(ROOT, first)

    def test_graph_tamper_rejected_after_receipt_rehash(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "output"
            receipt = build_portable_taxonomy(ROOT, output)
            graph_path = output / "graph.json"
            graph = json.loads(graph_path.read_bytes())
            graph["evaluation"]["micro_recall_at_10"] = 1.0
            graph_path.write_bytes(canonical_json(graph))
            receipt["files_sha256"]["graph.json"] = sha256_file(graph_path)[0]
            (output / "receipt.json").write_bytes(canonical_json(receipt))
            with self.assertRaisesRegex(ValueError, "source graph does not replay"):
                validate_portable_taxonomy(ROOT, output)


if __name__ == "__main__":
    unittest.main()
