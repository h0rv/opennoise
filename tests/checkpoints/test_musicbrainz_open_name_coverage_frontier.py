"""Contracts for the local-only open MusicBrainz name frontier."""

from __future__ import annotations

import unittest

from opennoise.checkpoints.musicbrainz_open_name_coverage_frontier import (
    OpenNameCoverageFrontier,
    frontier_sha256,
    verify_open_name_coverage_frontier,
)


def _frontier() -> OpenNameCoverageFrontier:
    values: dict[str, object] = {
        "microgenre_stratum_blocker": "No open granularity stratum is available.",
        "seed_reconciliation_output_sha256": "a" * 64,
        "direct_custody_output_sha256": "b" * 64,
        "native_census_output_sha256": "c" * 64,
        "tag_census_output_sha256": "d" * 64,
        "hierarchy_output_sha256": "e" * 64,
        "source_anchor_frontier_output_sha256": "f" * 64,
        "source_anchor_seed_count": 3,
        "source_anchor_musicbrainz_seed_count": 2,
        "source_anchor_wikidata_seed_count": 1,
        "source_anchor_cross_source_seed_count": 1,
        "direct_artist_proper_genre_seed_count": 1,
        "direct_artist_proper_genre_claim_count": 2,
        "direct_artist_proper_genre_artist_count": 1,
        "native_release_group_proper_name_seed_count": 2,
        "native_release_group_proper_observation_count": 3,
        "release_group_tag_name_seed_count": 3,
        "release_group_tag_observation_count": 4,
        "public_and_musicbrainz_identity_seed_count": 1,
        "direct_artist_proper_and_public_identity_seed_count": 1,
        "hierarchy_accepted_seed_count": 1,
        "direct_artist_proper_and_native_proper_seed_count": 1,
        "native_proper_and_tag_name_seed_count": 2,
        "direct_artist_proper_and_hierarchy_accepted_seed_count": 1,
        "output_sha256": "0" * 64,
    }
    draft = OpenNameCoverageFrontier.model_validate(values)
    return draft.model_copy(update={"output_sha256": frontier_sha256(draft)})


class OpenNameCoverageFrontierTests(unittest.TestCase):
    """The coverage report must remain local-only and source-role preserving."""

    def test_replays_its_hash_without_microgenre_or_membership_promotion(self) -> None:
        report = _frontier()

        verify_open_name_coverage_frontier(report)

        self.assertFalse(report.microgenre_stratum_available)
        self.assertFalse(report.artist_membership_constructed)
        self.assertFalse(report.static_or_model_promotion)

    def test_rejects_proper_genre_coverage_outside_musicbrainz_anchor_frontier(self) -> None:
        with self.assertRaisesRegex(ValueError, "proper-genre custody"):
            OpenNameCoverageFrontier(
                **_frontier()
                .model_copy(
                    update={
                        "source_anchor_musicbrainz_seed_count": 0,
                        "output_sha256": "0" * 64,
                    }
                )
                .model_dump()
            )


if __name__ == "__main__":
    unittest.main()
