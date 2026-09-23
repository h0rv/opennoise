"""CLI coverage for the local MusicBrainz static quality report command."""

from __future__ import annotations

import sys
import unittest
from unittest.mock import patch

from scripts import report_musicbrainz_direct_static_quality


class ReportMusicBrainzDirectStaticQualityTests(unittest.TestCase):
    """The command passes only explicit local paths to the report boundary."""

    def test_runs_the_local_report_writer(self) -> None:
        report = object()
        arguments = [
            "report_musicbrainz_direct_static_quality.py",
            "--direct-custody-receipt",
            "receipt.json",
            "--direct-custody-object-store",
            "objects",
            "--local-candidate-directory",
            "candidate",
            "--policy-review-input",
            "review.json",
            "--output",
            "quality.json",
        ]
        with (
            patch.object(sys, "argv", arguments),
            patch.object(
                report_musicbrainz_direct_static_quality,
                "build_musicbrainz_direct_static_quality_report",
                return_value=report,
            ) as build,
            patch.object(
                report_musicbrainz_direct_static_quality,
                "write_musicbrainz_direct_static_quality_report",
                return_value="a" * 64,
            ) as write,
        ):
            result = report_musicbrainz_direct_static_quality.main()

        self.assertEqual(result, 0)
        self.assertEqual(build.call_args.kwargs["local_candidate_directory"].name, "candidate")
        self.assertIs(write.call_args.args[1], report)
