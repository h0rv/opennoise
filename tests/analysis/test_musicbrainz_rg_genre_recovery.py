"""Behavior tests for exact-label separation in the local RG holdout."""

from __future__ import annotations

import unittest

from opennoise.analysis.musicbrainz_rg_genre_recovery import (
    _native_seed_labels,
    _partition_groups,
    _score_holdout,
)
from opennoise.ingest.musicbrainz.release_group_native_artist_support import (
    NativeReleaseGroupFact,
)
from opennoise.ingest.musicbrainz.release_group_native_observation import (
    NativeGenreObservation,
    NativeTagObservation,
)


class MusicBrainzRgGenreRecoveryTests(unittest.TestCase):
    """Keep test release groups disjoint and community tags out of targets."""

    def test_group_id_partition_has_no_release_group_leakage(self) -> None:
        groups = {f"group-{index}": index for index in range(100)}

        train, test = _partition_groups(groups)

        self.assertTrue(train)
        self.assertTrue(test)
        self.assertFalse(train.keys() & test.keys())
        self.assertEqual(train.keys() | test.keys(), groups.keys())

    def test_only_positive_proper_genre_names_become_targets(self) -> None:
        fact = NativeReleaseGroupFact(
            release_group_mbid="00000000-0000-0000-0000-000000000001",
            record_content_sha256="a" * 64,
            record_byte_length=1,
            title="fixture",
            primary_type="Album",
            first_release_date=None,
            artist_credit=(),
            proper_genres=(
                NativeGenreObservation(
                    genre_mbid="00000000-0000-0000-0000-000000000002",
                    name="Ambient",
                    vote_count=3,
                ),
                NativeGenreObservation(
                    genre_mbid="00000000-0000-0000-0000-000000000003",
                    name="Hyperpop",
                    vote_count=0,
                ),
            ),
        )
        # This tag is deliberately unrelated and has no route into target extraction.
        tags = (NativeTagObservation(name="hyperpop", vote_count=900),)

        labels = _native_seed_labels(fact, {"ambient", "hyperpop"})

        self.assertEqual(labels, frozenset({"ambient"}))
        self.assertEqual(tags[0].name, "hyperpop")

    def test_score_uses_train_only_labels_and_counts_cold_group_abstention(self) -> None:
        train = {
            "train-ambient-1": (frozenset({"ambient"}), frozenset({"artist-a"})),
            "train-ambient-2": (frozenset({"ambient"}), frozenset({"artist-b"})),
            "train-rock": (frozenset({"rock"}), frozenset({"artist-c"})),
        }
        test = {
            "test-warm": (frozenset({"ambient"}), frozenset({"artist-a"})),
            "test-cold": (frozenset({"rock"}), frozenset({"artist-new"})),
        }

        score = _score_holdout(train, test)

        self.assertEqual(score.transfer_correct, 1)
        self.assertEqual(score.transfer_abstentions, 1)
        self.assertEqual(score.popularity_correct, 1)
        self.assertEqual(score.warm_groups, 1)
        self.assertEqual(score.label_pairs, 2)
        self.assertEqual(score.labels_without_train_support, 0)
        self.assertEqual(score.transfer_macro_recall, 0.5)


if __name__ == "__main__":
    unittest.main()
