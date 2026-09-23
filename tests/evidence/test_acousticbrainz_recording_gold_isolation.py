from __future__ import annotations

import sys
import unittest
from subprocess import run

from opennoise.analysis.acousticbrainz_discogs_overlap import AcousticBrainzDiscogsOverlapReport
from opennoise.evidence.acousticbrainz_recording_gold_isolation import (
    audit_acousticbrainz_recording_gold_isolation,
)


class AcousticBrainzRecordingGoldIsolationTests(unittest.TestCase):
    def test_audit_permanently_abstains_before_acousticbrainz_labels_are_read(self) -> None:
        report = audit_acousticbrainz_recording_gold_isolation(
            self._overlap(), overlap_receipt_sha256="a" * 64
        )

        self.assertEqual(report.decision, "abstain_missing_verified_prediction_lineage")
        self.assertFalse(report.source_isolated_recording_evaluation_ready)
        self.assertEqual(report.prediction_lineage_verification, "unavailable")
        self.assertFalse(report.independent_artist_genre_gold_ready)
        self.assertFalse(report.label_columns_read)

    def test_fabricated_clean_declaration_cannot_be_supplied(self) -> None:
        completed = run(
            [
                sys.executable,
                "scripts/audit_acousticbrainz_recording_gold_isolation.py",
                "--overlap-receipt",
                "ignored.json",
                "--output",
                "ignored-output.json",
                "--prediction-lineage",
                "fabricated.json",
            ],
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("unrecognized arguments: --prediction-lineage", completed.stderr)

    @staticmethod
    def _overlap() -> AcousticBrainzDiscogsOverlapReport:
        return AcousticBrainzDiscogsOverlapReport.model_validate(
            {
                "source_file_sha256": "d" * 64,
                "source_file_md5": "d" * 32,
                "catalog_file_sha256": "e" * 64,
                "source_data_rows": 100,
                "source_duplicate_recording_id_rows": 0,
                "local_recording_mbid_count": 10,
                "exact_recording_mbid_overlap_count": 7,
                "exact_release_group_consistent_overlap_count": 6,
                "release_group_mismatch_overlap_count": 1,
                "one_primary_artist_overlap_count": 6,
                "one_primary_artist_release_group_consistent_overlap_count": 5,
            }
        )
