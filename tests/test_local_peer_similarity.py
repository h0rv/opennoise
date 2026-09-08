"""Contract tests for the local-only receipt-bound peer index CLI helpers."""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from typing import Protocol, cast


class _PeerSimilarityScript(Protocol):
    def build_index(
        self,
        *,
        artifact: Path,
        gate: Path,
        historical_receipt: Path,
        reconciliation: Path,
        output: Path,
    ) -> None: ...

    def neighbors(self, index: Path, seed: str, limit: int) -> dict[str, object]: ...


def _load_script() -> _PeerSimilarityScript:
    path = Path(__file__).parents[1] / "scripts" / "local_peer_similarity.py"
    specification = importlib.util.spec_from_file_location("local_peer_similarity", path)
    assert specification is not None
    assert specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return cast("_PeerSimilarityScript", module)


def _neighbor_values(result: dict[str, object]) -> list[dict[str, object]]:
    value = result["neighbors"]
    assert isinstance(value, list)
    return [cast("dict[str, object]", item) for item in value]


class LocalPeerSimilarityTests(unittest.TestCase):
    def test_builds_receipt_bound_index_and_returns_explicit_abstention(self) -> None:
        module = _load_script()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            artifact = root / "peer.json"
            gate = root / "gate.json"
            receipt = root / "receipt.json"
            reconciliation = root / "reconciliation.json"
            index = root / "peer.sqlite"
            artifact.write_text(
                json.dumps(
                    {
                        "candidates": [
                            {
                                "source_genre_id": "item1",
                                "target_genre_id": "item2",
                                "score": 0.75,
                                "direct_score": 0.5,
                                "aggregate_score": 0.25,
                                "shared_direct_artist_count": 3,
                                "aggregate_listener_day_support": 4,
                                "aggregate_supporting_windows": 2,
                                "sufficiency": "combined",
                                "evidence_refs": ["source:one"],
                                "components": [{"component_kind": "direct_artist_overlap"}],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            artifact_hash = "a" * 64
            gate.write_text(
                json.dumps(
                    {
                        "passed": True,
                        "all_inputs_export_allowed": False,
                        "artifact_output_sha256": artifact_hash,
                        "candidate_pair_count": 1,
                        "revision": "peer-gate-test",
                    }
                ),
                encoding="utf-8",
            )
            receipt.write_text(
                json.dumps(
                    {
                        "candidate_output_sha256": artifact_hash,
                        "historical_inputs_used_for_construction": False,
                    }
                ),
                encoding="utf-8",
            )
            reconciliation.write_text(
                json.dumps(
                    {
                        "dispositions": [
                            {
                                "source_item_id": "item1",
                                "source_external_id": "seed:1",
                                "seed_name": "one",
                                "disposition": "accepted",
                            },
                            {
                                "source_item_id": "item2",
                                "source_external_id": "seed:2",
                                "seed_name": "two",
                                "disposition": "accepted",
                            },
                            {
                                "source_item_id": "item3",
                                "source_external_id": "seed:3",
                                "seed_name": "three",
                                "disposition": "unresolved",
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )
            module.build_index(
                artifact=artifact,
                gate=gate,
                historical_receipt=receipt,
                reconciliation=reconciliation,
                output=index,
            )
            result = module.neighbors(index, "item1", 25)
            abstained = module.neighbors(index, "item3", 25)

        self.assertEqual(result["scope"], "local_research_non_production")
        self.assertFalse(result["all_inputs_export_allowed"])
        neighbor = _neighbor_values(result)[0]
        self.assertEqual(neighbor["target_seed_id"], "item2")
        self.assertEqual(neighbor["score"], 0.75)
        self.assertEqual(neighbor["source_evidence_ref_count"], 1)
        self.assertEqual(neighbor["component_kinds"], ["direct_artist_overlap"])
        self.assertTrue(abstained["abstained"])
        self.assertEqual(_neighbor_values(abstained), [])

    def test_rejects_an_exportable_or_unbound_artifact(self) -> None:
        module = _load_script()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            artifact = root / "peer.json"
            gate = root / "gate.json"
            receipt = root / "receipt.json"
            reconciliation = root / "reconciliation.json"
            artifact.write_text('{"candidates": []}', encoding="utf-8")
            gate.write_text(
                json.dumps(
                    {
                        "passed": True,
                        "all_inputs_export_allowed": True,
                        "artifact_output_sha256": "a" * 64,
                        "candidate_pair_count": 0,
                        "revision": "peer-gate-test",
                    }
                ),
                encoding="utf-8",
            )
            receipt.write_text(
                json.dumps(
                    {
                        "candidate_output_sha256": "a" * 64,
                        "historical_inputs_used_for_construction": False,
                    }
                ),
                encoding="utf-8",
            )
            reconciliation.write_text('{"dispositions": []}', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "non-exportable"):
                module.build_index(
                    artifact=artifact,
                    gate=gate,
                    historical_receipt=receipt,
                    reconciliation=reconciliation,
                    output=root / "peer.sqlite",
                )


if __name__ == "__main__":
    unittest.main()
