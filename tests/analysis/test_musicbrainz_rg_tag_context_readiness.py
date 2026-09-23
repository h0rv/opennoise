"""Contracts for the no-leakage positive-tag readiness checkpoint."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from opennoise.analysis.musicbrainz_rg_genre_recovery_v2 import (
    MusicBrainzRgGenreRecoveryV2Report,
    RecoveryMetric,
    SampledReleaseGroup,
    SampleGenre,
    SampleTag,
)
from opennoise.analysis.musicbrainz_rg_genre_recovery_v2 import (
    report_sha256 as sample_report_sha256,
)
from opennoise.analysis.musicbrainz_rg_tag_context_readiness import (
    _fixed_ranking_comparison,
    _fixed_rankings_before_p136_targets,
    audit_musicbrainz_rg_positive_tag_context,
    verify_readiness_report,
)


def _sample_report() -> MusicBrainzRgGenreRecoveryV2Report:
    metric = RecoveryMetric(
        correct=0,
        scoreable_denominator=0,
        target_group_denominator=0,
        abstentions=0,
        accuracy=0.0,
        coverage_adjusted_accuracy=0.0,
    )
    draft = MusicBrainzRgGenreRecoveryV2Report.model_construct(
        source_id="fixture-source",
        source_snapshot="fixture-snapshot",
        source_archive_sha256="a" * 64,
        source_archive_bytes=1,
        source_manifest_sha256="b" * 64,
        source_cache_receipt_sha256="c" * 64,
        reconciliation_sha256="d" * 64,
        sample_method="fixture",
        sample_modulus=1,
        holdout_rule="fixture",
        sample_limit=10,
        max_selected_record_bytes=10,
        max_retained_facts=10,
        raw_records_seen=2,
        selected_records=2,
        sampled_group_count=2,
        sampled_group_count_with_seed_genre=1,
        sampled_malformed_records=0,
        oversized_records=0,
        selected_oversized_records=0,
        selected_record_bytes=2,
        retained_fact_count=4,
        labeled_group_count=1,
        heldout_labeled_group_count=0,
        heldout_seed_label_pair_count=0,
        train_labeled_group_count=1,
        train_seed_label_count=1,
        heldout_seed_label_count=0,
        heldout_seed_labels_without_train_support=0,
        artist_transfer_macro_recall_by_seed=0.0,
        train_popularity_macro_recall_by_seed=0.0,
        warm_artist_group_count=0,
        cold_artist_group_count=0,
        artist_transfer_top1=metric,
        train_popularity_top1=metric,
        sample_content_sha256="e" * 64,
        sampled_groups=(
            SampledReleaseGroup(
                release_group_mbid="00000000-0000-0000-0000-000000000001",
                record_content_sha256="1" * 64,
                record_byte_length=1,
                artist_mbids=("artist-a",),
                proper_genres=(
                    SampleGenre(
                        genre_mbid="00000000-0000-0000-0000-000000000002",
                        name="Jazz",
                        vote_count=1,
                    ),
                ),
                positive_tags=(SampleTag(name=" Jazz ", vote_count=1),),
            ),
            SampledReleaseGroup(
                release_group_mbid="00000000-0000-0000-0000-000000000003",
                record_content_sha256="2" * 64,
                record_byte_length=1,
                artist_mbids=("artist-b", "artist-c"),
                proper_genres=(),
                positive_tags=(SampleTag(name="Fusion", vote_count=2),),
            ),
        ),
        output_sha256="0" * 64,
    )
    return draft.model_copy(update={"output_sha256": sample_report_sha256(draft)})


class MusicBrainzRgTagContextReadinessTests(unittest.TestCase):
    """The only permitted result without independent gold is abstention."""

    def test_fixture_gold_yields_a_no_score_readiness_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            sample_path = Path(temporary_directory) / "sample.json"
            sample_path.write_text(json.dumps(_sample_report().model_dump(mode="json")))

            report = audit_musicbrainz_rg_positive_tag_context(
                sample_report_path=sample_path,
                wikidata_p136_database_path=Path("data/public.sqlite"),
                seed_reconciliation_path=Path(
                    ".cache/musicbrainz-full-seed-targets/pipeline/seed-reconciliation.json"
                ),
                independent_gold_paths=(
                    Path("tests/fixtures/independent_artist_genre_gold_fixture_v1.json"),
                ),
            )

        self.assertFalse(report.performance_evaluation_performed)
        self.assertTrue(report.positive_only_recovery_evaluation_performed)
        self.assertFalse(report.native_proper_genres_used_as_targets)
        self.assertEqual(report.positive_tags_role, "weak_artist_context_only")
        self.assertEqual(report.groups_with_positive_tags, 2)
        self.assertEqual(report.positive_tag_observation_count, 2)
        self.assertEqual(report.positive_tag_artist_attachment_count, 3)
        self.assertEqual(report.distinct_normalized_positive_tag_count, 2)
        self.assertEqual(report.artist_local_positive_tag_top_k.top_k, 5)
        self.assertEqual(
            report.artist_local_positive_tag_top_k.positive_pair_denominator,
            report.wikidata_p136_overlapping_sample_positive_pair_count,
        )
        self.assertTrue(report.train_blind_global_tag_popularity_top_k.p136_label_blind)
        self.assertFalse(
            report.train_blind_global_tag_popularity_top_k.independently_held_out_baseline
        )
        self.assertEqual(
            report.train_blind_global_tag_popularity_top_k.positive_pair_denominator,
            report.wikidata_p136_overlapping_sample_positive_pair_count,
        )
        self.assertEqual(
            report.train_blind_global_tag_popularity_top_k.training_group_count,
            report.sampled_group_count,
        )
        self.assertEqual(report.gold_candidates[0].source_kind, "fixture_only")
        self.assertIn("fixture-only", report.gold_candidates[0].blocker)
        verify_readiness_report(report)

    def test_source_isolated_positive_recovery_does_not_score_native_genres(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            sample_path = Path(temporary_directory) / "sample.json"
            sample_path.write_text(json.dumps(_sample_report().model_dump(mode="json")))
            report = audit_musicbrainz_rg_positive_tag_context(
                sample_report_path=sample_path,
                wikidata_p136_database_path=Path("data/public.sqlite"),
                seed_reconciliation_path=Path(
                    ".cache/musicbrainz-full-seed-targets/pipeline/seed-reconciliation.json"
                ),
            )

        self.assertEqual(report.readiness, "positive_only_recovery_not_full_quality_evaluation")
        self.assertEqual(report.native_proper_genre_observation_count, 1)
        self.assertFalse(report.native_proper_genres_used_as_targets)
        self.assertFalse(report.precision_computed)

    def test_global_baseline_order_is_fixed_before_positive_pairs(self) -> None:
        groups = _sample_report().sampled_groups
        candidates = frozenset({"seed-jazz", "seed-fusion"})
        local_rankings, global_ranking = _fixed_rankings_before_p136_targets(
            groups=groups,
            seed_names={"seed-jazz": "jazz", "seed-fusion": "fusion"},
            candidate_seeds=candidates,
        )
        local, baseline = _fixed_ranking_comparison(
            positives={("artist-a", "seed-jazz")},
            candidate_seeds=candidates,
            local_rankings=local_rankings,
            global_ranking=global_ranking,
            training_group_count=len(groups),
        )

        self.assertTrue(local.candidate_universe_frozen_before_p136_targets)
        self.assertTrue(local.ranking_order_frozen_before_p136_targets)
        self.assertEqual(local.frozen_seed_candidate_count, 2)
        self.assertEqual(local.recovered_positive_pair_count, 1)
        self.assertTrue(baseline.p136_label_blind)
        self.assertFalse(baseline.artist_disjoint_from_local_arm)
        self.assertEqual(baseline.training_group_count, 2)
        self.assertEqual(baseline.recovered_positive_pair_count, 1)


if __name__ == "__main__":
    unittest.main()
