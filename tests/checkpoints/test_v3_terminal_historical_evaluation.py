"""Focused boundaries for the local-only v3 terminal historical evaluator."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import opennoise.checkpoints.v3_terminal_historical_evaluation as evaluation
from opennoise.checkpoints.v3_terminal_historical_evaluation import (
    ExactNameCoverage,
    FileBinding,
    PositiveOverlap,
    V3TerminalHistoricalEvaluation,
    V3TerminalHistoricalEvaluationError,
    V3TerminalHistoricalEvaluationInputs,
    _exact_name_mapping,
    _load_fixed_v3_candidate,
    _load_historical,
    _require_fresh_local_report_paths,
    _verify_construction_isolation,
    _verify_pinned_v3_custody,
    v3_terminal_historical_evaluation_sha256,
    verify_v3_terminal_historical_evaluation_receipt,
    write_v3_terminal_historical_evaluation,
)
from opennoise.models.historical_signal import HistoricalSignalArtifact, HistoricalSignalNode
from opennoise.models.modeling import GenreIdentity, PublicModelArtifact
from opennoise.pipeline.candidate_public_projection import CandidatePublicProjectionV3Report


class V3TerminalHistoricalEvaluationTests(unittest.TestCase):
    def test_tampered_model_bytes_are_rejected_before_database_or_history(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            model_path = root / "model.json"
            receipt_path = root / "receipt.json"
            database_path = root / "serving.sqlite"
            model_path.write_bytes(b"tampered-model")
            receipt_path.write_bytes(b"receipt")
            database_path.write_bytes(b"database")
            receipt = CandidatePublicProjectionV3Report.model_construct(
                model_file_sha256="0" * 64,
                model_byte_size=1,
                serving_database_sha256="1" * 64,
                model_logical_sha256="2" * 64,
                receipt_logical_sha256="3" * 64,
            )
            model = PublicModelArtifact.model_construct(output_sha256="2" * 64)
            inputs = V3TerminalHistoricalEvaluationInputs(
                model=model_path,
                receipt=receipt_path,
                serving_database=database_path,
                historical_reference=root / "must-not-open.json",
            )
            with (
                patch.object(
                    evaluation.CandidatePublicProjectionV3Report,
                    "model_validate_json",
                    return_value=receipt,
                ),
                patch.object(
                    evaluation.PublicModelArtifact, "model_validate_json", return_value=model
                ),
                self.assertRaisesRegex(
                    V3TerminalHistoricalEvaluationError, "model bytes do not match receipt"
                ),
            ):
                _load_fixed_v3_candidate(inputs)
            self.assertFalse(inputs.historical_reference.exists())

    def test_ambiguous_names_remain_abstentions(self) -> None:
        model = PublicModelArtifact.model_construct(
            genres=(
                GenreIdentity(genre_id="open:jazz", name="Jazz", evidence_refs=("catalog:jazz",)),
                GenreIdentity(genre_id="open:pop", name="Pop", evidence_refs=("catalog:pop",)),
            )
        )
        historical = HistoricalSignalArtifact.model_construct(
            nodes=(
                HistoricalSignalNode.model_construct(genre_id="enao-legacy:jazz", name="jazz"),
                HistoricalSignalNode.model_construct(genre_id="enao-legacy:pop-a", name="pop"),
                HistoricalSignalNode.model_construct(genre_id="enao-legacy:pop-b", name="POP"),
            )
        )
        mapping, coverage = _exact_name_mapping(model, historical)
        self.assertEqual(mapping, {"open:jazz": "enao-legacy:jazz"})
        self.assertEqual(coverage.unique_exact_name_match_count, 1)
        self.assertEqual(coverage.ambiguous_name_abstention_count, 1)
        self.assertEqual(coverage.candidate_abstention_count, 1)
        self.assertEqual(coverage.historical_abstention_count, 2)
        self.assertEqual(coverage.exact_identifier_match_count, 0)

    def test_historical_absence_is_an_abstention_not_a_precision_denominator(self) -> None:
        overlap = PositiveOverlap(
            candidate_positive_count=2,
            mapped_candidate_positive_count=1,
            historical_positive_count=4,
            overlap_count=1,
            historical_observed_positive_coverage=0.25,
            denominator_note="observed positives only",
        )
        self.assertIsNone(overlap.candidate_precision)
        self.assertEqual(overlap.historical_observed_positive_coverage, 0.25)
        with self.assertRaisesRegex(ValueError, "observed-positive coverage"):
            PositiveOverlap(
                candidate_positive_count=2,
                mapped_candidate_positive_count=1,
                historical_positive_count=4,
                overlap_count=1,
                historical_observed_positive_coverage=0.5,
                denominator_note="tampered denominator",
            )

    def test_duplicate_candidate_name_is_an_abstention_not_a_many_to_one_mapping(self) -> None:
        model = PublicModelArtifact.model_construct(
            genres=(
                GenreIdentity(genre_id="open:pop-a", name="Pop", evidence_refs=("catalog:a",)),
                GenreIdentity(genre_id="open:pop-b", name="POP", evidence_refs=("catalog:b",)),
            )
        )
        historical = HistoricalSignalArtifact.model_construct(
            nodes=(HistoricalSignalNode.model_construct(genre_id="enao-legacy:pop", name="pop"),)
        )
        mapping, coverage = _exact_name_mapping(model, historical)
        self.assertEqual(mapping, {})
        self.assertEqual(coverage.unique_exact_name_match_count, 0)
        self.assertEqual(coverage.ambiguous_name_abstention_count, 2)
        self.assertEqual(coverage.candidate_abstention_count, 2)
        self.assertEqual(coverage.historical_abstention_count, 1)

    def test_historical_token_leakage_is_rejected(self) -> None:
        model = PublicModelArtifact.model_construct(
            genres=(
                GenreIdentity(
                    genre_id="enao-legacy:item1",
                    name="pop",
                    evidence_refs=("catalog:genre:1",),
                ),
            ),
            artifacts=(),
        )
        with self.assertRaisesRegex(V3TerminalHistoricalEvaluationError, "historical construction"):
            _verify_construction_isolation(model)

    def test_tampered_terminal_report_receipt_is_rejected(self) -> None:
        binding = FileBinding(
            role="fixture",
            bytes_sha256="a" * 64,
            byte_count=1,
            logical_sha256="b" * 64,
        )
        axis = PositiveOverlap(
            candidate_positive_count=1,
            mapped_candidate_positive_count=1,
            historical_positive_count=1,
            overlap_count=1,
            historical_observed_positive_coverage=1.0,
            denominator_note="observed positive fixture",
        )
        base = V3TerminalHistoricalEvaluation(
            candidate_model=binding,
            candidate_receipt=binding,
            candidate_serving_database=binding,
            historical_reference=binding,
            exact_name_coverage=ExactNameCoverage(
                candidate_genre_count=1,
                historical_genre_count=1,
                exact_identifier_match_count=0,
                unique_exact_name_match_count=1,
                ambiguous_name_abstention_count=0,
                candidate_abstention_count=0,
                historical_abstention_count=0,
            ),
            membership_seed_presence=axis,
            neighborhoods=axis,
            output_sha256="0" * 64,
        )
        report = base.model_copy(
            update={"output_sha256": v3_terminal_historical_evaluation_sha256(base)}
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.json"
            receipt_path = Path(directory) / "receipt.json"
            receipt = write_v3_terminal_historical_evaluation(path, receipt_path, report)
            verify_v3_terminal_historical_evaluation_receipt(path, receipt, report)
            path.write_bytes(b"tampered")
            with self.assertRaisesRegex(V3TerminalHistoricalEvaluationError, "receipt"):
                verify_v3_terminal_historical_evaluation_receipt(path, receipt, report)

    def test_report_outputs_must_be_fresh_and_local(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            existing = root / "report.json"
            existing.write_text("already exists", encoding="utf-8")
            with self.assertRaisesRegex(V3TerminalHistoricalEvaluationError, "fresh"):
                _require_fresh_local_report_paths(existing, root / "receipt.json")
        with self.assertRaisesRegex(V3TerminalHistoricalEvaluationError, "under /tmp"):
            _require_fresh_local_report_paths(
                Path("docs/v3-terminal-report.json"),
                Path("docs/v3-terminal-receipt.json"),
            )

    def test_pinned_custody_rejects_self_consistent_manifest_substitution(self) -> None:
        receipt = CandidatePublicProjectionV3Report.model_construct(
            manifest_sha256="0" * 64,
            candidate_sha256="327bbf377cb9ad8a1ed48821718979606622175f255ece5958d674146aba6763",
            historical_candidate_binding_sha256=(
                "ddaf45593ad78a6c6535691bf499c003d86e36227dd1bceb3e97e60dfae9d6a6"
            ),
            source_artifact_set_sha256=(
                "5faa89fb81d69de534b985fb15b4d35cd3402191e4048569540a95778ac34f0a"
            ),
        )
        with self.assertRaisesRegex(V3TerminalHistoricalEvaluationError, "pinned custody"):
            _verify_pinned_v3_custody(
                "c430b9948b863404827dd346fed6324a38b650ab2a827608078fc145b79fd1ba",
                "3bd6adb0d213a4e95ed06e78426f47e85b7ac20e3e0b662de7ee1097140008af",
                "1fca548fa214aae999f7b2462fd2ebf3e265a7f5195a3d6d76b5393f06bd8df9",
                receipt,
            )

    def test_historical_reference_is_pinned_before_parsing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "historical.json"
            path.write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(V3TerminalHistoricalEvaluationError, "pinned"):
                _load_historical(path)


if __name__ == "__main__":
    unittest.main()
