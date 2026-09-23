"""Checks for the local exact full-signature peer-graph ablation."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from opennoise.peers.direct_custody_graph import build_direct_custody_peer_graph
from opennoise.peers.signature_ablation import build_exact_signature_ablation_report
from tests.peers.test_direct_custody_graph import _build_fixture, _uuid


class ExactSignatureAblationTests(unittest.TestCase):
    def _graph(self, directory: Path) -> tuple[Path, Path]:
        cohort = tuple(_uuid(number) for number in range(1, 1_001))
        extra_signature = (_uuid(2_001), _uuid(2_002))
        singleton_signature = _uuid(2_003)
        assignments = {
            "a": (*cohort, *extra_signature, singleton_signature),
            "b": (*cohort, *extra_signature),
            "c": (*cohort, singleton_signature),
            "d": (*extra_signature, singleton_signature),
        }
        custody, object_store, receipt_sha = _build_fixture(directory, assignments)
        database = directory / "graph.sqlite"
        receipt_path = directory / "graph.receipt.json"
        build_direct_custody_peer_graph(
            custody=custody,
            object_store=object_store,
            custody_receipt_byte_sha256=receipt_sha,
            database=database,
            receipt_output=receipt_path,
        )
        return database, receipt_path

    def test_removes_only_exact_signature_and_is_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            database, receipt_path = self._graph(Path(name))
            first = build_exact_signature_ablation_report(
                database=database, receipt_path=receipt_path
            )
            second = build_exact_signature_ablation_report(
                database=database, receipt_path=receipt_path
            )
        self.assertEqual(first, second)
        self.assertEqual(first.baseline_suspect_pair_count, 3)
        self.assertFalse(first.historical_inputs_used)
        self.assertFalse(first.h3_inputs_used)
        self.assertFalse(first.automatic_candidate_suppression)
        self.assertFalse(first.fact_deletion_authorized)
        self.assertFalse(first.public_export_authorized)
        ablation = first.ablations[0]
        self.assertEqual(ablation.dominant_signature, ("a", "b", "c"))
        self.assertEqual(ablation.removed_artist_count, 1_000)
        self.assertEqual(ablation.removed_seed_artist_claim_count, 3_000)
        pairs = {(pair.left_seed_id, pair.right_seed_id): pair for pair in ablation.pairs}
        self.assertEqual(pairs[("a", "b")].residual_shared_artist_count, 2)
        self.assertEqual(pairs[("a", "b")].disposition, "cohort_resilient")
        self.assertEqual(pairs[("a", "c")].residual_shared_artist_count, 1)
        self.assertIsNone(pairs[("a", "c")].residual_idf_weighted_jaccard)
        self.assertEqual(pairs[("a", "c")].disposition, "cohort_dependent")
        neighborhoods = {item.seed_id: item for item in ablation.endpoint_neighborhoods}
        self.assertEqual(set(neighborhoods), {"a", "b", "c"})
        self.assertIn("b", neighborhoods["a"].shadow_top_ten)

    def test_tampered_receipt_is_rejected_before_ablation(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            database, receipt_path = self._graph(Path(name))
            payload = json.loads(receipt_path.read_text(encoding="utf-8"))
            payload["output_sha256"] = "0" * 64
            receipt_path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "receipt output hash"):
                build_exact_signature_ablation_report(database=database, receipt_path=receipt_path)


if __name__ == "__main__":
    unittest.main()
