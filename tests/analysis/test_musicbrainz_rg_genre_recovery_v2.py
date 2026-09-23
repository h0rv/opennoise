"""Behavior checks for hash selection and the bounded whole-group holdout."""

from __future__ import annotations

import unittest
from uuid import UUID

from opennoise.analysis.musicbrainz_rg_genre_recovery_v2 import (
    _MAX_SELECTED_RECORDS,
    MusicBrainzRgGenreRecoveryV2Report,
    RecoveryMetric,
    _check_sample_limits,
    _partition_groups,
    _sample_selected,
    _score_holdout,
    _seed_labels,
    report_sha256,
    verify_report,
)
from opennoise.sources.musicbrainz import MusicBrainzGenre, MusicBrainzReleaseGroup, MusicBrainzTag


class MusicBrainzRgGenreRecoveryV2Tests(unittest.TestCase):
    """Keep sample selection stable and score each held-out group once."""

    def test_hash_selection_is_stable_for_record_content(self) -> None:
        selected_record_hash = "d4e33e2934280979f580a63f992daa7d0de2cd64a145d5c403a75c3dc5c0004e"
        rejected_record_hash = "a" * 64

        self.assertTrue(_sample_selected(selected_record_hash))
        self.assertFalse(_sample_selected(rejected_record_hash))

    def test_partition_keeps_each_release_group_on_one_side(self) -> None:
        groups = {f"group-{index}": index for index in range(100)}

        train, test = _partition_groups(groups)

        self.assertTrue(train)
        self.assertTrue(test)
        self.assertFalse(train.keys() & test.keys())
        self.assertEqual(train.keys() | test.keys(), groups.keys())

    def test_only_positive_proper_genres_become_targets(self) -> None:
        group = MusicBrainzReleaseGroup(
            id=UUID("00000000-0000-0000-0000-000000000001"),
            title="fixture",
            genres=(
                MusicBrainzGenre(
                    id=UUID("00000000-0000-0000-0000-000000000002"),
                    name="Ambient",
                    count=3,
                ),
                MusicBrainzGenre(
                    id=UUID("00000000-0000-0000-0000-000000000003"),
                    name="Noise",
                    count=0,
                ),
            ),
            tags=(MusicBrainzTag(name="noise", count=900),),
        )

        labels = _seed_labels(group, frozenset({"ambient", "noise"}))

        self.assertEqual(labels, frozenset({"ambient"}))

    def test_split_has_disjoint_release_groups_and_cold_abstentions(self) -> None:
        train = {
            "train-ambient": (frozenset({"ambient"}), frozenset({"artist-a"})),
            "train-rock": (frozenset({"rock"}), frozenset({"artist-b"})),
        }
        test = {
            "test-warm": (frozenset({"ambient"}), frozenset({"artist-a"})),
            "test-cold": (frozenset({"rock"}), frozenset({"artist-new"})),
        }

        score = _score_holdout(train, test)

        self.assertEqual(score.transfer_correct, 1)
        self.assertEqual(score.transfer_abstentions, 1)
        self.assertEqual(score.warm_groups, 1)
        self.assertEqual(score.label_pairs, 2)
        self.assertEqual(score.transfer_macro_recall, 0.5)
        self.assertEqual(score.popularity_correct, 1)

    def test_transfer_votes_use_train_only_artist_labels(self) -> None:
        train = {
            "train-a": (frozenset({"ambient"}), frozenset({"artist-a"})),
            "train-b": (frozenset({"ambient"}), frozenset({"artist-b"})),
        }
        test = {
            "test-a": (frozenset({"rock"}), frozenset({"artist-a"})),
        }

        score = _score_holdout(train, test)

        self.assertEqual(score.transfer_correct, 0)
        self.assertEqual(score.transfer_abstentions, 0)
        self.assertEqual(score.transfer_macro_recall, 0.0)

    def test_sample_caps_fail_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "record cap exceeded"):
            _check_sample_limits(
                selected_records=_MAX_SELECTED_RECORDS + 1,
                selected_record_bytes=0,
                retained_facts=0,
            )

    def test_report_hash_covers_denominators_and_scores(self) -> None:
        zero_metric = RecoveryMetric(
            correct=0,
            scoreable_denominator=0,
            target_group_denominator=0,
            abstentions=0,
            accuracy=0.0,
            coverage_adjusted_accuracy=0.0,
        )
        report = MusicBrainzRgGenreRecoveryV2Report(
            source_id="musicbrainz_json_release_group_research_20260905",
            source_snapshot="20260905-001001",
            source_archive_sha256="a" * 64,
            source_archive_bytes=1,
            source_manifest_sha256="b" * 64,
            source_cache_receipt_sha256="c" * 64,
            reconciliation_sha256="d" * 64,
            sample_method="fixture",
            sample_modulus=450,
            holdout_rule="fixture",
            sample_limit=1,
            max_selected_record_bytes=1,
            max_retained_facts=1,
            raw_records_seen=0,
            selected_records=0,
            sampled_group_count=0,
            sampled_group_count_with_seed_genre=0,
            sampled_malformed_records=0,
            oversized_records=0,
            selected_oversized_records=0,
            selected_record_bytes=0,
            retained_fact_count=0,
            labeled_group_count=0,
            heldout_labeled_group_count=0,
            heldout_seed_label_pair_count=0,
            train_labeled_group_count=0,
            train_seed_label_count=0,
            heldout_seed_label_count=0,
            heldout_seed_labels_without_train_support=0,
            artist_transfer_macro_recall_by_seed=0.0,
            train_popularity_macro_recall_by_seed=0.0,
            warm_artist_group_count=0,
            cold_artist_group_count=0,
            artist_transfer_top1=zero_metric,
            train_popularity_top1=zero_metric,
            sample_content_sha256="e" * 64,
            sampled_groups=(),
            output_sha256="0" * 64,
        )
        verified = report.model_copy(update={"output_sha256": report_sha256(report)})

        verify_report(verified)

        changed = verified.model_copy(update={"raw_records_seen": 1})
        with self.assertRaisesRegex(ValueError, "output hash does not replay"):
            verify_report(changed)


if __name__ == "__main__":
    unittest.main()
