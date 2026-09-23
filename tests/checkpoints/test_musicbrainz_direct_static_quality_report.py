"""Behavioral tests for the local MusicBrainz direct static quality report."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from opennoise.checkpoints.musicbrainz_direct_local_static_candidate import (
    LocalCandidateMembership,
    LocalMusicBrainzStaticCandidateManifest,
)
from opennoise.checkpoints.musicbrainz_direct_static_policy_review import (
    MusicBrainzDirectStaticPolicyReviewInput,
)
from opennoise.checkpoints.musicbrainz_direct_static_quality_report import (
    MusicBrainzDirectStaticQualityReportError,
    _measure,
    quality_report_sha256,
    write_musicbrainz_direct_static_quality_report,
)
from opennoise.deployment.musicbrainz_direct_proper_genre_custody import (
    DirectProperGenreClaim,
    DirectProperGenreCustodyReceipt,
)

_SEED_IDS = tuple(f"item{index:03d}" for index in range(412))


class MusicBrainzDirectStaticQualityReportTests(unittest.TestCase):
    """The report records local completeness without changing publication policy."""

    def test_measures_complete_exact_rows_and_stable_samples(self) -> None:
        rows = self._rows()
        report = _measure(
            self._receipt(), self._manifest(), self._review(), self._claims(rows), rows
        )

        self.assertEqual(report.placed_seed_count, 412)
        self.assertEqual((report.source_claim_count, report.candidate_row_count), (412, 412))
        self.assertEqual((report.source_coverage, report.name_coverage), (1, 1))
        self.assertEqual(report.duplicate_count, 0)
        self.assertEqual(report.exclusion_count, 0)
        self.assertIsNone(report.ambiguous_name_rejection_count)
        self.assertFalse(report.ambiguous_name_exclusions_measured)
        self.assertEqual(report.exact_id_integrity_failure_count, 0)
        self.assertEqual(len(report.per_genre_row_counts), 412)
        self.assertEqual(len(report.review_sample_public_source_links), 12)
        self.assertEqual(len(report.largest_genres), 5)
        self.assertEqual(len(report.smallest_genres), 5)
        self.assertEqual(len(report.suspicious_review_samples), 4)
        self.assertEqual(report.output_sha256, quality_report_sha256(report))
        self.assertTrue(
            report.review_sample_public_source_links[0].public_source_link.startswith(
                "https://musicbrainz.org/artist/"
            )
        )

    def test_counts_a_missing_source_row_as_an_exclusion_for_review(self) -> None:
        rows = self._rows()
        extra = DirectProperGenreClaim(
            seed_id=_SEED_IDS[0],
            artist_mbid="ffffffff-ffff-ffff-ffff-ffffffffffff",
            musicbrainz_genre_id=rows[0].musicbrainz_genre_id,
            source_record_id="musicbrainz:artist:ffffffff-ffff-ffff-ffff-ffffffffffff",
            source_record_sha256="f" * 64,
            source_evidence_ref="source:extra",
        )
        report = _measure(
            self._receipt(), self._manifest(), self._review(), (*self._claims(rows), extra), rows
        )

        self.assertEqual(report.exclusion_count, 1)
        self.assertIsNone(report.ambiguous_name_rejection_count)
        self.assertEqual(report.missing_source_row_count, 1)
        self.assertLess(report.source_coverage, 1)

    def test_writes_once_as_canonical_json(self) -> None:
        rows = self._rows()
        report = _measure(
            self._receipt(), self._manifest(), self._review(), self._claims(rows), rows
        )
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "quality.json"
            byte_sha256 = write_musicbrainz_direct_static_quality_report(output, report)

            self.assertEqual(len(byte_sha256), 64)
            self.assertTrue(output.read_bytes().endswith(b"\n"))
            with self.assertRaisesRegex(
                MusicBrainzDirectStaticQualityReportError, "already exists"
            ):
                write_musicbrainz_direct_static_quality_report(output, report)

    @staticmethod
    def _rows() -> tuple[LocalCandidateMembership, ...]:
        return tuple(
            LocalCandidateMembership(
                seed_id=seed_id,
                artist_mbid=f"00000000-0000-0000-0000-{index:012x}",
                canonical_name=f"Artist {index}",
                musicbrainz_genre_id=f"10000000-0000-0000-0000-{index:012x}",
                source_record_id=f"musicbrainz:artist:00000000-0000-0000-0000-{index:012x}",
                source_record_sha256=f"{index:064x}",
                source_evidence_ref=f"source:{index}",
            )
            for index, seed_id in enumerate(_SEED_IDS)
        )

    @staticmethod
    def _claims(
        rows: tuple[LocalCandidateMembership, ...],
    ) -> tuple[DirectProperGenreClaim, ...]:
        return tuple(
            DirectProperGenreClaim(
                seed_id=row.seed_id,
                artist_mbid=row.artist_mbid,
                musicbrainz_genre_id=row.musicbrainz_genre_id,
                source_record_id=row.source_record_id,
                source_record_sha256=row.source_record_sha256,
                source_evidence_ref=row.source_evidence_ref,
            )
            for row in rows
        )

    @staticmethod
    def _receipt() -> DirectProperGenreCustodyReceipt:
        return DirectProperGenreCustodyReceipt.model_construct(
            output_sha256="a" * 64,
            claims_object_sha256="b" * 64,
        )

    @staticmethod
    def _manifest() -> LocalMusicBrainzStaticCandidateManifest:
        return LocalMusicBrainzStaticCandidateManifest.model_construct(output_sha256="c" * 64)

    @staticmethod
    def _review() -> MusicBrainzDirectStaticPolicyReviewInput:
        return MusicBrainzDirectStaticPolicyReviewInput.model_construct(
            placed_candidate_seed_ids=_SEED_IDS,
            output_sha256="d" * 64,
        )
