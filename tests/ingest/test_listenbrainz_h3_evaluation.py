"""Boundary tests for evaluation-only ListenBrainz/H3 accounting."""

from __future__ import annotations

import unittest

from musix.ingest.listenbrainz_h3_evaluation import (
    ListenBrainzH3EvaluationCoverage,
    ListenBrainzH3EvaluationMetrics,
)
from scripts.evaluate_listenbrainz_propagation_h3 import build_parser


class ListenBrainzH3EvaluationTests(unittest.TestCase):
    def test_h3_resolution_and_candidate_abstention_are_complete_partitions(self) -> None:
        coverage = ListenBrainzH3EvaluationCoverage(
            h3_observation_count=10,
            h3_mapped_positive_count=4,
            h3_unique_mapped_positive_count=3,
            h3_unmapped_genre_observation_count=1,
            h3_unbridged_artist_observation_count=4,
            h3_conflicted_artist_observation_count=1,
            h3_positive_genre_count=3,
            candidate_genre_count=2,
            candidate_genre_with_h3_positive_count=2,
            abstained_h3_positive_genre_count=1,
            evaluated_positive_count=3,
        )
        self.assertEqual(coverage.abstained_h3_positive_genre_count, 1)
        with self.assertRaisesRegex(ValueError, "resolution paths"):
            ListenBrainzH3EvaluationCoverage(
                **{**coverage.model_dump(), "h3_unbridged_artist_observation_count": 3}
            )

    def test_metrics_bind_hits_to_explicit_conditional_and_global_denominators(self) -> None:
        metrics = ListenBrainzH3EvaluationMetrics(
            hit_count_at_50=2,
            candidate_available_positive_count=4,
            all_mapped_unique_positive_count=10,
            predicted_candidate_count_at_50=50,
            candidate_available_recall_at_50=0.5,
            global_recall_at_50=0.2,
        )
        self.assertIsNone(metrics.precision_at_50)
        self.assertEqual(
            metrics.precision_unavailable_reason, "positive_only_h3_absences_are_unknown"
        )
        with self.assertRaisesRegex(ValueError, "candidate-available positives"):
            ListenBrainzH3EvaluationMetrics(
                hit_count_at_50=2,
                candidate_available_positive_count=11,
                all_mapped_unique_positive_count=10,
                predicted_candidate_count_at_50=50,
                candidate_available_recall_at_50=0.5,
                global_recall_at_50=0.2,
            )

    def test_cli_requires_separate_frontier_and_h3_custody_inputs(self) -> None:
        arguments = build_parser().parse_args(
            [
                "--frontier-v5",
                "frontier.json",
                "--frontier-v5-receipt",
                "frontier.receipt.json",
                "--listenbrainz-propagation",
                "listenbrainz.json",
                "--listenbrainz-propagation-receipt",
                "listenbrainz.receipt.json",
                "--bridge",
                "bridge.json",
                "--bridge-receipt",
                "bridge.receipt.json",
                "--bridge-receipt-sha256",
                "a" * 64,
                "--historical-database",
                "historical.sqlite",
                "--output",
                "evaluation.json",
                "--object-store",
                "objects",
                "--receipt",
                "receipt.json",
            ]
        )
        self.assertEqual(arguments.frontier_v5.name, "frontier.json")


if __name__ == "__main__":
    unittest.main()
