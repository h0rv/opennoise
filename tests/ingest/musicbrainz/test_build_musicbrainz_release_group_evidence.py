from __future__ import annotations

import io
import unittest
from contextlib import redirect_stderr

from musix.ingest.musicbrainz.release_group_evidence import ReleaseGroupEvidenceProgress
from scripts.build_musicbrainz_release_group_evidence import _progress_reporter


class ReleaseGroupEvidenceProgressReporterTests(unittest.TestCase):
    def test_reports_only_at_the_configured_aggregate_cadence(self) -> None:
        output = io.StringIO()
        with redirect_stderr(output):
            report = _progress_reporter(every_records=100_000)
            report(ReleaseGroupEvidenceProgress(records_seen=10_000, elapsed_seconds=1.0))
            report(ReleaseGroupEvidenceProgress(records_seen=100_000, elapsed_seconds=2.0))
            report(ReleaseGroupEvidenceProgress(records_seen=199_999, elapsed_seconds=3.0))
            report(ReleaseGroupEvidenceProgress(records_seen=200_000, elapsed_seconds=4.0))

        self.assertEqual(
            output.getvalue().splitlines(),
            [
                "release-group progress records_seen=100000 elapsed_seconds=2.000",
                "release-group progress records_seen=200000 elapsed_seconds=4.000",
            ],
        )

    def test_rejects_nonpositive_progress_cadence(self) -> None:
        with self.assertRaisesRegex(ValueError, "must be positive"):
            _progress_reporter(every_records=0)
