"""Focused behavioral tests for the deterministic review-only latent benchmark."""

from __future__ import annotations

import unittest
from unittest.mock import patch

import numpy as np
from scipy import sparse

from opennoise.ml.latent_genre_similarity import (
    InputBinding,
    LatentGenreSimilarityArtifact,
    LatentGenreSimilarityError,
    LatentGenreSimilaritySettings,
    RetrievalMetric,
    _metric,
    _rank_latent,
    _validate_pair_indices,
)


class LatentGenreSimilarityTests(unittest.TestCase):
    """Low-rank ranking and positive-only accounting."""

    @staticmethod
    def _bindings() -> tuple[InputBinding, ...]:
        return (
            InputBinding(
                role="full_graph_artifact",
                byte_sha256="a" * 64,
                byte_count=1,
                logical_sha256="b" * 64,
            ),
            InputBinding(
                role="full_graph_receipt",
                byte_sha256="a" * 64,
                byte_count=1,
                logical_sha256="b" * 64,
            ),
            InputBinding(
                role="matrix_cache_metadata",
                byte_sha256="a" * 64,
                byte_count=1,
                logical_sha256="b" * 64,
            ),
            InputBinding(
                role="binary_train_matrix",
                byte_sha256="a" * 64,
                byte_count=1,
                logical_sha256="b" * 64,
            ),
            InputBinding(
                role="pair_split",
                byte_sha256="a" * 64,
                byte_count=1,
                logical_sha256="b" * 64,
            ),
        )

    def test_fixed_seed_latent_ranking_replays_and_excludes_train_labels(self) -> None:
        """The same sparse input yields one ranking and never recommends an observed train seed."""
        matrix = sparse.csr_matrix(
            np.asarray(
                (
                    (1.0, 1.0, 0.0, 0.0),
                    (1.0, 0.0, 1.0, 0.0),
                    (0.0, 1.0, 0.0, 1.0),
                    (0.0, 0.0, 1.0, 1.0),
                ),
                dtype=np.float32,
            )
        )
        settings = LatentGenreSimilaritySettings(rank=2, maximum_evaluation_artists=100)

        first = _rank_latent(matrix, [0], settings)
        second = _rank_latent(matrix, [0], settings)

        self.assertTrue(np.array_equal(first[0], second[0]))
        self.assertNotIn(0, first[0])
        self.assertNotIn(1, first[0])

    def test_positive_only_metric_accounts_for_abstentions(self) -> None:
        """An absent ranking abstains rather than treating a missing pair as negative evidence."""
        result = _metric("latent_svd", {1: {2}, 3: {4}}, {1: np.asarray([2])}, 2)

        self.assertEqual(result.heldout_positive_count, 2)
        self.assertEqual(result.scoreable_positive_count, 1)
        self.assertEqual(result.abstained_positive_count, 1)
        self.assertEqual(result.recall_at_10, 0.5)

    def test_latent_ranking_abstains_without_a_train_edge(self) -> None:
        """A fully held-out artist cannot acquire a fabricated latent preference."""
        matrix = sparse.csr_matrix(
            np.asarray(((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 0.0)), dtype=np.float32)
        )
        settings = LatentGenreSimilaritySettings(rank=2, maximum_evaluation_artists=100)

        rankings = _rank_latent(matrix, [2], settings)

        self.assertEqual(rankings[2].tolist(), [])

    def test_latent_ranking_abstains_for_a_zero_projection_with_a_train_edge(self) -> None:
        """An observed train edge outside the retained SVD basis cannot create tied candidates."""
        matrix = sparse.csr_matrix(np.diag(np.asarray((1.0, 1.0, 0.0, 0.0), dtype=np.float32)))
        right = np.asarray(((1.0, 0.0, 0.0, 0.0), (0.0, 0.0, 1.0, 0.0)), dtype=np.float32)
        settings = LatentGenreSimilaritySettings(rank=2, maximum_evaluation_artists=100)

        with patch("opennoise.ml.latent_genre_similarity.svds", return_value=(None, None, right)):
            rankings = _rank_latent(matrix, [1], settings)

        self.assertEqual(rankings[1].tolist(), [])

    def test_latent_ranking_abstains_for_a_nonfinite_projection(self) -> None:
        """Nonfinite latent coordinates are an abstention, never a ranked prediction."""
        matrix = sparse.csr_matrix(np.diag(np.asarray((1.0, 1.0, 0.0, 0.0), dtype=np.float32)))
        right = np.asarray(((float("nan"), 0.0, 0.0, 0.0), (0.0, 1.0, 0.0, 0.0)), dtype=np.float32)
        settings = LatentGenreSimilaritySettings(rank=2, maximum_evaluation_artists=100)

        with patch("opennoise.ml.latent_genre_similarity.svds", return_value=(None, None, right)):
            rankings = _rank_latent(matrix, [0], settings)

        self.assertEqual(rankings[0].tolist(), [])

    def test_pair_coordinates_reject_negative_rows_and_columns(self) -> None:
        """A cache coordinate cannot escape the sparse matrix through Python negative indexing."""
        valid = {
            "rows": np.asarray((0,), dtype=np.int32),
            "columns": np.asarray((0,), dtype=np.int32),
            "heldout_rows": np.asarray((1,), dtype=np.int32),
            "heldout_columns": np.asarray((1,), dtype=np.int32),
        }
        for field in ("rows", "columns", "heldout_rows", "heldout_columns"):
            with self.subTest(field=field):
                tampered = {key: value.copy() for key, value in valid.items()}
                tampered[field][0] = -1
                with self.assertRaises(LatentGenreSimilarityError):
                    _validate_pair_indices(tampered, 2, 1, 1)

    def test_metric_rejects_nonreplaying_counts(self) -> None:
        """A rehashed report cannot change a recall numerator without its fraction."""
        with self.assertRaises(ValueError):
            RetrievalMetric(
                model="latent_svd",
                eligible_artist_count=2,
                heldout_positive_count=2,
                scoreable_positive_count=2,
                abstained_positive_count=0,
                recovered_at_10_count=1,
                recovered_at_25_count=1,
                recall_at_10=1.0,
                recall_at_25=0.5,
            )

    def test_metric_rejects_recovery_from_an_abstained_positive(self) -> None:
        """A rehashed metric cannot claim a hit from an artist it says it abstained on."""
        with self.assertRaises(ValueError):
            RetrievalMetric(
                model="latent_svd",
                eligible_artist_count=2,
                heldout_positive_count=2,
                scoreable_positive_count=1,
                abstained_positive_count=1,
                recovered_at_10_count=1,
                recovered_at_25_count=2,
                recall_at_10=0.5,
                recall_at_25=1.0,
            )

    def test_artifact_rejects_a_baseline_with_a_different_artist_cohort(self) -> None:
        """A report cannot rehash a baseline evaluated on fewer held-out artists."""
        metric = RetrievalMetric(
            model="latent_svd",
            eligible_artist_count=2,
            heldout_positive_count=2,
            scoreable_positive_count=2,
            abstained_positive_count=0,
            recovered_at_10_count=1,
            recovered_at_25_count=1,
            recall_at_10=0.5,
            recall_at_25=0.5,
        )
        with self.assertRaises(ValueError):
            LatentGenreSimilarityArtifact(
                inputs=self._bindings(),
                settings=LatentGenreSimilaritySettings(),
                settings_sha256="c" * 64,
                train_pair_count=2,
                heldout_pair_count=2,
                evaluated_artist_count=2,
                latent=metric,
                binary_jaccard=metric.model_copy(
                    update={"model": "binary_jaccard", "eligible_artist_count": 1}
                ),
                train_only_popularity=metric.model_copy(update={"model": "train_only_popularity"}),
                direct_only=metric.model_copy(update={"model": "direct_only"}),
                output_sha256="d" * 64,
            )

    def test_artifact_rejects_duplicate_input_role(self) -> None:
        """A rehashed report cannot substitute one receipt while omitting another input role."""
        metric = RetrievalMetric(
            model="latent_svd",
            eligible_artist_count=2,
            heldout_positive_count=2,
            scoreable_positive_count=2,
            abstained_positive_count=0,
            recovered_at_10_count=1,
            recovered_at_25_count=1,
            recall_at_10=0.5,
            recall_at_25=0.5,
        )
        bindings = self._bindings()
        with self.assertRaises(ValueError):
            LatentGenreSimilarityArtifact(
                inputs=(bindings[0], bindings[0], bindings[2], bindings[3], bindings[4]),
                settings=LatentGenreSimilaritySettings(),
                settings_sha256="c" * 64,
                train_pair_count=2,
                heldout_pair_count=2,
                evaluated_artist_count=2,
                latent=metric,
                binary_jaccard=metric.model_copy(update={"model": "binary_jaccard"}),
                train_only_popularity=metric.model_copy(update={"model": "train_only_popularity"}),
                direct_only=metric.model_copy(update={"model": "direct_only"}),
                output_sha256="d" * 64,
            )


if __name__ == "__main__":
    unittest.main()
