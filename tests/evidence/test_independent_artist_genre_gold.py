from __future__ import annotations

import json
import unittest
from pathlib import Path

from pydantic import ValidationError

from opennoise.evidence.independent_artist_genre_gold import (
    IndependentArtistGenreGoldSet,
    evaluate_independent_gold,
    load_gold_set,
    load_prediction_set,
)


class IndependentArtistGenreGoldTests(unittest.TestCase):
    def test_fixture_is_diagnostic_and_cannot_pass_production_gate(self) -> None:
        gold, gold_sha256 = load_gold_set(
            Path("tests/fixtures/independent_artist_genre_gold_fixture_v1.json")
        )
        predictions, prediction_sha256 = load_prediction_set(
            Path("tests/fixtures/independent_artist_genre_predictions_fixture_v1.json")
        )
        report = evaluate_independent_gold(
            gold,
            predictions,
            gold_file_sha256=gold_sha256,
            prediction_file_sha256=prediction_sha256,
        )
        self.assertEqual((report.true_positive, report.false_positive), (1, 1))
        self.assertEqual((report.false_negative, report.true_negative), (1, 1))
        self.assertFalse(report.independently_sourced)
        self.assertFalse(report.production_threshold_met)
        self.assertFalse(report.release_quality_eligible)
        self.assertIn("fixture-only", report.failures[0])

    def test_rejects_construction_source_and_unsealed_split(self) -> None:
        fixture = Path("tests/fixtures/independent_artist_genre_gold_fixture_v1.json")
        raw = json.loads(fixture.read_text())
        raw["source_custody"]["excluded_provenance"].remove("wikidata")
        with self.assertRaises(ValidationError):
            IndependentArtistGenreGoldSet.model_validate(raw)

    def test_rejects_automatic_fma_track_tag_promotion(self) -> None:
        fixture = Path("tests/fixtures/independent_artist_genre_gold_fixture_v1.json")
        raw = load_gold_set(fixture)[0].model_dump()
        raw["independent_public_gold_labels"] = True
        raw["source_custody"]["source_kind"] = "fma_metadata_with_reviewed_identity_bridge"
        raw["source_custody"]["identity_bridge_kind"] = "reviewed_exact_external_id"
        with self.assertRaisesRegex(ValidationError, "cannot automatically"):
            IndependentArtistGenreGoldSet.model_validate(raw)

        raw = json.loads(fixture.read_text())
        raw["judgments"][0]["split_bucket"] = 4
        with self.assertRaises(ValidationError):
            IndependentArtistGenreGoldSet.model_validate(raw)


if __name__ == "__main__":
    unittest.main()
