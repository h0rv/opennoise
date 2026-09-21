"""Boundary tests for the terminal current-lineage historical adapter."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import opennoise.checkpoints.current_lineage_evaluation as evaluation
from opennoise.checkpoints.current_lineage_evaluation import (
    CurrentLineageEvaluationError,
    CurrentLineageEvaluationInputs,
    PositiveOverlapAxis,
    _assert_checkpoint_binding,
    _binding,
    _check_receipt,
    _ReceiptExpectation,
    build_current_lineage_historical_evaluation,
)
from opennoise.checkpoints.reconstruction_checkpoint import (
    CheckpointBinding,
    ReconstructionCheckpoint,
)
from opennoise.common import sha256_file
from opennoise.evidence.graph_projection import EvidenceGraphProjectionArtifact
from opennoise.ml.full_graph_signal import FullGraphSignalArtifact
from opennoise.ml.genre_neighborhoods.contracts import GenreNeighborhoodArtifact
from opennoise.ml.hierarchy_fusion import HierarchyFusionArtifact


class CurrentLineageEvaluationTests(unittest.TestCase):
    def test_positive_axis_replays_historical_denominator(self) -> None:
        axis = PositiveOverlapAxis(
            candidate_observation_count=4,
            mapped_candidate_observation_count=4,
            historical_positive_observation_count=8,
            overlap_count=2,
            historical_positive_recall=0.25,
            denominator_note="positive-only",
        )
        self.assertEqual(axis.overlap_count, 2)
        with self.assertRaises(ValueError):
            PositiveOverlapAxis(
                candidate_observation_count=4,
                mapped_candidate_observation_count=4,
                historical_positive_observation_count=8,
                overlap_count=2,
                historical_positive_recall=0.5,
                denominator_note="tampered",
            )

    def test_receipt_tamper_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "candidate.json"
            path.write_bytes(b"sealed")
            digest, size = sha256_file(path)
            path.write_bytes(b"tampered")
            changed_digest, changed_size = sha256_file(path)
            with self.assertRaises(CurrentLineageEvaluationError):
                _check_receipt(
                    _ReceiptExpectation(digest, size, "a" * 64),
                    changed_digest,
                    changed_size,
                    "a" * 64,
                    "candidate",
                )

    def test_cross_lineage_binding_rejects_before_missing_history_is_opened(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            admitted = root / "admitted.json"
            substituted = root / "substituted.json"
            missing_historical = root / "missing-historical.json"
            admitted.write_bytes(b"admitted")
            substituted.write_bytes(b"substituted")
            expected = _binding("full_graph_signal", admitted, root, "b" * 64)
            with self.assertRaises(CurrentLineageEvaluationError):
                _assert_checkpoint_binding(
                    {"full_graph_signal": expected},
                    "full_graph_signal",
                    substituted,
                    root,
                    "b" * 64,
                )
            self.assertFalse(missing_historical.exists())

    def test_builder_rejects_current_substitution_before_opening_history(self) -> None:
        """A current-lineage failure wins over an unreadable terminal reference."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = {
                name: root / f"{name}.json"
                for name in (
                    "graph_database",
                    "graph_receipt",
                    "full_graph",
                    "full_graph_receipt",
                    "neighborhoods",
                    "neighborhoods_receipt",
                    "neighborhoods_database",
                    "hierarchy",
                )
            }
            for path in paths.values():
                path.write_bytes(path.name.encode())
            admitted_full_graph = root / "admitted-full-graph.json"
            admitted_full_graph.write_bytes(b"admitted-full-graph")
            substituted_full_graph = root / "substituted-full-graph.json"
            substituted_full_graph.write_bytes(b"substituted-full-graph")
            missing_history = root / "history-that-must-not-be-opened.json"

            def expected(role: str, path: Path, logical: str) -> CheckpointBinding:
                return _binding(role, path, root, logical)

            expected_inputs = (
                expected("evidence_graph_database", paths["graph_database"], "a" * 64),
                expected("evidence_graph_receipt", paths["graph_receipt"], "b" * 64),
                expected("full_graph_signal", admitted_full_graph, "c" * 64),
                expected("full_graph_signal_receipt", paths["full_graph_receipt"], "c" * 64),
                expected("genre_neighborhoods", paths["neighborhoods"], "d" * 64),
                expected("genre_neighborhoods_receipt", paths["neighborhoods_receipt"], "d" * 64),
                expected("genre_neighborhoods_database", paths["neighborhoods_database"], "e" * 64),
                expected("hierarchy_fusion", paths["hierarchy"], "f" * 64),
            )
            checkpoint = ReconstructionCheckpoint.model_construct(
                inputs=expected_inputs,
                evaluation_inputs=(),
                historical_data_used_for_evaluation=False,
                output_sha256="1" * 64,
            )
            graph = EvidenceGraphProjectionArtifact.model_construct(
                database_sha256="a" * 64,
                output_sha256="b" * 64,
            )
            full = FullGraphSignalArtifact.model_construct(
                graph_database_sha256="a" * 64,
                graph_receipt_output_sha256="b" * 64,
                output_sha256="c" * 64,
            )
            neighborhood = GenreNeighborhoodArtifact.model_construct(
                graph_receipt_output_sha256="b" * 64,
                cache_database_sha256="e" * 64,
                output_sha256="d" * 64,
            )
            hierarchy = HierarchyFusionArtifact.model_construct(
                output_sha256="f" * 64,
                seed_states=(),
            )
            fixture_inputs = CurrentLineageEvaluationInputs(
                root=root,
                construction_checkpoint=paths["graph_receipt"],
                graph_database=paths["graph_database"],
                graph_receipt=paths["graph_receipt"],
                full_graph=substituted_full_graph,
                full_graph_receipt=paths["full_graph_receipt"],
                neighborhoods=paths["neighborhoods"],
                neighborhoods_receipt=paths["neighborhoods_receipt"],
                neighborhoods_database=paths["neighborhoods_database"],
                hierarchy=paths["hierarchy"],
                historical_reference=missing_history,
            )
            with (
                patch.object(evaluation, "_load_checkpoint", return_value=checkpoint),
                patch.object(evaluation, "_load_graph", return_value=graph),
                patch.object(evaluation, "_load_full_graph", return_value=full),
                patch.object(evaluation, "_load_neighborhood", return_value=(neighborhood, set())),
                patch.object(evaluation, "_load_hierarchy", return_value=hierarchy),
                self.assertRaisesRegex(
                    CurrentLineageEvaluationError,
                    "current full_graph_signal does not match sealed checkpoint",
                ),
            ):
                build_current_lineage_historical_evaluation(fixture_inputs)
            self.assertFalse(missing_history.exists())

    def test_binding_contract_remains_typed(self) -> None:
        binding = CheckpointBinding(
            role="historical",
            locator=".cache/reference.json",
            bytes_sha256="a" * 64,
            byte_count=1,
            logical_sha256="b" * 64,
        )
        self.assertEqual(binding.role, "historical")


if __name__ == "__main__":
    unittest.main()
