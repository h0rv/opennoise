"""Check source detection calibration, abstention and component isolation."""

import json
import math
import tempfile
import unittest
from pathlib import Path

from opennoise.analysis.emergent_community_evaluation import FeatureFact
from opennoise.common import sha256_file
from opennoise.ml.overlapping_source_styles import fit_overlapping_styles
from opennoise.ml.source_reobservation import (
    SourceReobservationCalibration,
    calibration_from_dict,
    calibration_to_dict,
    fit_source_reobservation,
    load_source_reobservation,
    score_bin,
)
from scripts.evaluate_source_reobservation import partition_components, source_permission
from tests.ml.test_overlapping_source_styles import fixture


class SourceReobservationTests(unittest.TestCase):
    def test_scores_preserve_baseline_ranks_and_missing_queries_abstain(self) -> None:
        profiles = fixture()
        model = fit_overlapping_styles(profiles, rarity_power=0.35)
        scored = model.score_batch(profiles, ("query", "a", "cold", "missing"))
        ranked = model.rank_batch(profiles, ("query", "a", "cold", "missing"))
        self.assertEqual(
            ranked, {artist: tuple(v for v, _s in rows) for artist, rows in scored.items()}
        )
        self.assertEqual(ranked["query"], ("rare",))
        self.assertEqual(ranked["missing"], ())
        self.assertEqual(ranked["cold"], ())

    def test_calibration_records_source_event_and_thin_bins_abstain(self) -> None:
        model = fit_source_reobservation(
            [(0.2, True)] * 32 + [(0.2, False)] * 32 + [(8.0, True)],
            source_sha256="source",
            scorer_sha256="scorer",
            split_salt="split",
        )
        rate, support = model.estimate(0.2)
        self.assertEqual(support, 64)
        assert rate is not None
        self.assertAlmostEqual(rate, (32 + 32 * 33 / 65) / 96)
        self.assertEqual(model.estimate(8.0), (None, 1))
        proposals = model.proposals((("retained", 0.2), ("thin", 8.0)))
        self.assertEqual(len(proposals), 1)
        self.assertFalse(proposals[0]["native_fact"])
        self.assertIsNone(proposals[0]["semantic_membership_probability"])
        self.assertFalse(proposals[0]["genre_identity_validated"])
        self.assertEqual(calibration_from_dict(calibration_to_dict(model)), model)
        self.assertEqual(model.proposals((("x", 0.2),), minimum_detection_rate=1), ())

    def test_bound_artifact_rejects_other_scorer_and_semantic_role(self) -> None:
        model = fit_source_reobservation(
            [(0.2, True)] * 32, source_sha256="s", scorer_sha256="m", split_salt="split"
        )
        raw = calibration_to_dict(model)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "calibration.json"
            path.write_text(json.dumps(raw))
            digest = sha256_file(path)[0]
            self.assertEqual(
                load_source_reobservation(
                    str(path), expected_sha256=digest, source_sha256="s", scorer_sha256="m"
                ),
                model,
            )
            with self.assertRaisesRegex(ValueError, "scorer"):
                load_source_reobservation(
                    str(path),
                    expected_sha256=digest,
                    source_sha256="s",
                    scorer_sha256="full-source-refit",
                )
            path.write_text("{}")
            with self.assertRaisesRegex(ValueError, "file identity"):
                load_source_reobservation(
                    str(path), expected_sha256=digest, source_sha256="s", scorer_sha256="m"
                )
        raw["semantic_membership_probability"] = True
        with self.assertRaisesRegex(ValueError, "role contract"):
            calibration_from_dict(raw)

    def test_fit_requires_exact_projection_research_permission(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "features.jsonl"
            source.write_text("fixture")
            path = Path(directory) / "receipt.json"
            receipt = {
                "feature_sha256": sha256_file(source)[0],
                "research_model_input_authorized": True,
                "research_model_scope": "local_noncommercial_research",
                "public_export_authorized": False,
                "derived_output_obligations": "attribution; noncommercial; share alike",
            }
            path.write_text(json.dumps(receipt))
            self.assertFalse(source_permission(source, path)["public_export_authorized"])
            for field, value in (
                ("research_model_input_authorized", False),
                ("feature_sha256", "other"),
                ("training_authorized", False),
            ):
                path.write_text(json.dumps({**receipt, field: value}))
                with self.assertRaisesRegex(ValueError, "authorization"):
                    source_permission(source, path)

    def test_invalid_scores_counts_and_events_rejected(self) -> None:
        for score in (0, -1, math.nan, math.inf):
            with self.assertRaises(ValueError):
                score_bin(score)
        with self.assertRaises(ValueError):
            SourceReobservationCalibration("s", "m", "split", (1,), (2,))
        with self.assertRaises(TypeError):
            fit_source_reobservation(
                [(1.0, 1)],  # ty: ignore[invalid-argument-type]
                source_sha256="s",  # type: ignore[list-item]
                scorer_sha256="m",
                split_salt="split",
            )

    def test_duplicate_pair_and_shared_release_never_cross_three_roles(self) -> None:
        facts = []
        for index in range(100):
            facts.extend(
                [
                    FeatureFact(f"a{index}", "style", f"release:{index}"),
                    FeatureFact(f"b{index}", "style", f"release:{index}"),
                    FeatureFact(f"a{index}", "style", f"artist:{index}"),
                    FeatureFact(f"a{index}", "genre", f"artist:{index}"),
                ]
            )
        calibration, test = partition_components(facts)
        self.assertTrue(calibration)
        self.assertTrue(test)
        self.assertFalse(calibration & test)
        for index in range(100):
            component = {(f"a{index}", "style"), (f"b{index}", "style"), (f"a{index}", "genre")}
            self.assertIn(len(component & calibration), (0, 3))
            self.assertIn(len(component & test), (0, 3))
        self.assertEqual(partition_components(reversed(facts)), (calibration, test))


if __name__ == "__main__":
    unittest.main()
