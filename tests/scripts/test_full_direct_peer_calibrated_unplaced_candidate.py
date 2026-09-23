"""Tests for bounded input reading in the local peer calibration builder."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from opennoise.serving.local.conservative_peer_holdout import Point
from scripts import build_full_direct_peer_calibrated_unplaced_candidate as candidate
from scripts.build_full_direct_peer_calibrated_unplaced_candidate import _direct_memberships


class FullDirectPeerCalibratedCandidateTests(unittest.TestCase):
    def test_membership_reader_streams_only_exact_identity_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "input.json"
            path.write_text(
                '{"direct_memberships":[{"artist_id":"artist-a","genre_id":"genre-a",'
                '"large_ignored_field":"x"},{"artist_id":"artist-b","genre_id":"genre-b"}]}',
                encoding="utf-8",
            )
            self.assertEqual(
                tuple(_direct_memberships(path)),
                (("artist-a", "genre-a"), ("artist-b", "genre-b")),
            )

    def test_membership_reader_rejects_missing_exact_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "input.json"
            path.write_text('{"direct_memberships":[{"artist_id":"artist-a"}]}', encoding="utf-8")
            with self.assertRaisesRegex(TypeError, "artist and genre"):
                tuple(_direct_memberships(path))

    def test_cli_rejects_output_outside_project_cache_before_reading_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with (
                patch.object(candidate, "_PROJECT_CACHE_ROOT", root / "cache"),
                patch(
                    "sys.argv",
                    [
                        "candidate",
                        "--public-input",
                        "missing",
                        "--layout",
                        "missing",
                        "--frontier",
                        "missing",
                        "--output",
                        str(root / "outside.json"),
                    ],
                ),
                self.assertRaisesRegex(ValueError, "project .cache"),
            ):
                candidate.main()

    def test_calibration_diagnostics_reports_anchor_strata(self) -> None:
        diagnostics = candidate._calibration_diagnostics(  # noqa: SLF001 - focused diagnostic contract
            anchors={"a": Point(0, 0), "b": Point(1, 0), "c": Point(2, 0)},
            edges=(("a", "b"), ("b", "c")),
        )
        self.assertEqual(diagnostics["target_count"], 3)
        strata = diagnostics["by_placed_peer_anchor_count"]
        if not isinstance(strata, dict):
            self.fail("diagnostics must expose peer-anchor strata")
        self.assertIn("one", strata)
        self.assertIn("two_or_more", strata)
