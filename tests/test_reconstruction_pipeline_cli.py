"""Parser contracts for the explicit reconstruction workflow."""

from __future__ import annotations

import unittest
from pathlib import Path

from scripts.run_genre_reconstruction_pipeline import build_parser


class ReconstructionPipelineCliTests(unittest.TestCase):
    """Keep stage names and required artifact boundaries stable."""

    def test_reconcile_requires_explicit_inputs(self) -> None:
        arguments = build_parser().parse_args(
            [
                "reconcile",
                "--seed-artifact",
                "seed.json",
                "--taxonomy-artifact",
                "taxonomy.json",
                "--output",
                "reconciliation.json",
            ]
        )
        self.assertEqual(arguments.command, "reconcile")
        self.assertEqual(arguments.seed_artifact, Path("seed.json"))
        self.assertIsNone(arguments.musicbrainz_input)

    def test_peer_settings_are_parameterized(self) -> None:
        arguments = build_parser().parse_args(
            [
                "peer",
                "--public-input",
                "input.json",
                "--output",
                "peer.json",
                "--metric",
                "cosine",
                "--maximum-neighbors",
                "12",
            ]
        )
        self.assertEqual(arguments.metric, "cosine")
        self.assertEqual(arguments.maximum_neighbors, 12)
        self.assertEqual(arguments.minimum_shared_artists, 2)

    def test_peer_can_bind_the_verified_seed_reconciliation(self) -> None:
        arguments = build_parser().parse_args(
            [
                "peer",
                "--public-input",
                "input.json",
                "--seed-reconciliation",
                "reconciliation.json",
                "--output",
                "peer.json",
            ]
        )
        self.assertEqual(arguments.seed_reconciliation, Path("reconciliation.json"))

    def test_historical_evaluation_requires_object_store_receipt(self) -> None:
        with self.assertRaises(SystemExit):
            build_parser().parse_args(
                [
                    "peer-evaluate",
                    "--candidate",
                    "candidate.json",
                    "--public-input",
                    "input.json",
                    "--public-database",
                    "public.sqlite",
                    "--historical-database",
                    "historical.sqlite",
                    "--output",
                    "report.json",
                ]
            )
