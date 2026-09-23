from __future__ import annotations

import unittest

from opennoise.ingest.musicbrainz.release_group_native_census_decision import (
    _PINNED_CENSUS_OUTPUT_SHA256,
    _PINNED_LAYOUT_SHA256,
    _PINNED_RECONCILIATION_SHA256,
    NativeGenreCoverageScope,
    NativeGenreVoteTotals,
    ReleaseGroupNativeCensusDecisionError,
    ReleaseGroupNativeCensusDecisionReport,
    _scope,
    _Totals,
    report_sha256,
    verify_release_group_native_census_decision,
)


class ReleaseGroupNativeCensusDecisionTests(unittest.TestCase):
    def test_scope_sums_vote_signs_and_credit_components_without_membership(self) -> None:
        coverage = _scope(
            frozenset({"noise", "rock"}),
            {
                "noise": _Totals(
                    observation_count=3,
                    zero_vote_count=1,
                    negative_vote_count=1,
                    missing_vote_count=1,
                ),
                "rock": _Totals(
                    observation_count=7,
                    positive_vote_count=5,
                    zero_vote_count=1,
                    missing_vote_count=1,
                    credited_artist_component_count=9,
                ),
            },
        )

        self.assertEqual(coverage.exact_normalized_name_count, 2)
        self.assertEqual(coverage.names_with_credited_artist_components_count, 1)
        self.assertEqual(coverage.vote_totals.observation_count, 10)
        self.assertEqual(coverage.vote_totals.positive_vote_count, 5)
        self.assertEqual(coverage.vote_totals.zero_vote_count, 2)
        self.assertEqual(coverage.vote_totals.negative_vote_count, 1)
        self.assertEqual(coverage.vote_totals.missing_vote_count, 2)
        self.assertEqual(coverage.vote_totals.credited_artist_component_count, 9)
        self.assertEqual(
            tuple(item.matching_name_count for item in coverage.positive_vote_support_bins),
            (1, 1, 1, 0),
        )

    def test_verifier_rejects_a_rehashed_nested_invariant_violation(self) -> None:
        valid_scope = _scope(
            frozenset({"rock"}),
            {"rock": _Totals(observation_count=1, positive_vote_count=1)},
        )
        invalid_scope = NativeGenreCoverageScope.model_construct(
            exact_normalized_name_count=1,
            names_with_credited_artist_components_count=2,
            vote_totals=NativeGenreVoteTotals(
                observation_count=1,
                positive_vote_count=1,
                zero_vote_count=0,
                negative_vote_count=0,
                missing_vote_count=0,
                credited_artist_component_count=0,
            ),
            positive_vote_support_bins=valid_scope.positive_vote_support_bins,
        )
        preliminary = ReleaseGroupNativeCensusDecisionReport.model_construct(
            source_census_output_sha256=_PINNED_CENSUS_OUTPUT_SHA256,
            seed_reconciliation_sha256=_PINNED_RECONCILIATION_SHA256,
            layout_sha256=_PINNED_LAYOUT_SHA256,
            seed_coverage=valid_scope,
            unplaced_coverage=invalid_scope,
            top_supported_unplaced_names=(),
            output_sha256="0" * 64,
        )
        tampered = preliminary.model_copy(update={"output_sha256": report_sha256(preliminary)})

        with self.assertRaisesRegex(ReleaseGroupNativeCensusDecisionError, "declared invariants"):
            verify_release_group_native_census_decision(tampered)
