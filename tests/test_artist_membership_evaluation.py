from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from pydantic import ValidationError

from musix.serving.artist_membership_evaluation import (
    ArtistMembershipEvaluationStore,
    ArtistMembershipJudgmentSet,
    evaluate_artist_memberships,
    load_judgment_set,
    publish_evaluation_evidence,
)
from musix.storage import LocalObjectStore
from tests.test_public_model_gate import _artifact


class ArtistMembershipEvaluationTests(unittest.TestCase):
    def _judgments(self):  # noqa: ANN202
        return load_judgment_set(Path("tests/fixtures/artist_membership_judgments_v1.json"))

    def test_calibration_reports_separate_macro_metrics_abstentions_and_replay(self) -> None:
        judgments, judgment_file_sha256 = self._judgments()
        report = evaluate_artist_memberships(
            _artifact(),
            judgments,
            judgment_file_sha256=judgment_file_sha256,
            model_file_sha256="a" * 64,
        )

        self.assertTrue(report.passed)
        self.assertFalse(report.release_quality_eligible)
        self.assertEqual(report.direct.macro_precision, 1.0)
        self.assertEqual(report.direct.macro_recall, 1.0)
        self.assertEqual(report.direct.macro_f1, 1.0)
        self.assertEqual(report.direct.abstention_rate, 0.5)
        self.assertEqual(report.one_hop.macro_f1, 1.0)
        self.assertEqual(report.one_hop.abstention_rate, 0.5)
        self.assertEqual(len(report.direct.facet_breakdown), 2)
        self.assertEqual(len(report.one_hop.facet_breakdown), 1)
        self.assertTrue(report.stability.exact_replay)
        self.assertEqual(
            report.stability.initial_evaluation_sha256,
            report.stability.replay_evaluation_sha256,
        )

    def test_rejects_unheld_out_or_hash_changed_judgment_input(self) -> None:
        raw = json.loads(Path("tests/fixtures/artist_membership_judgments_v1.json").read_text())
        raw["judgments"][0]["split_bucket"] = 0
        with self.assertRaises(ValidationError):
            ArtistMembershipJudgmentSet.model_validate(raw)

        raw = json.loads(Path("tests/fixtures/artist_membership_judgments_v1.json").read_text())
        raw["judgments"][0]["expected_member"] = False
        with self.assertRaises(ValidationError):
            ArtistMembershipJudgmentSet.model_validate(raw)

    def test_sqlite_ledger_and_object_store_bind_the_input_and_report_bytes(self) -> None:
        judgments, judgment_file_sha256 = self._judgments()
        report = evaluate_artist_memberships(
            _artifact(), judgments, judgment_file_sha256=judgment_file_sha256
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report_path = root / "artist-membership-evaluation-v1.json"
            report_path.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
            ledger = ArtistMembershipEvaluationStore(root / "evaluations.sqlite")
            self.assertFalse(ledger.record(report))
            self.assertTrue(ledger.record(report))
            receipt = publish_evaluation_evidence(
                LocalObjectStore(root / "objects"),
                Path("tests/fixtures/artist_membership_judgments_v1.json"),
                report_path,
                report,
            )
            self.assertEqual(receipt.judgment.sha256, judgment_file_sha256)
            self.assertTrue(receipt.report.key.value.startswith("evaluation/artist-membership/"))


if __name__ == "__main__":
    unittest.main()
