"""Check train-only range/missingness gates and fixed-frame metadata comparisons."""

import hashlib
import json
import math
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from typing import override

from opennoise.analysis.acoustic_representation import ArtistDescriptors, sonic_neighbors
from opennoise.analysis.acoustic_support import (
    AcousticSupportPolicy,
    fit_acoustic_support,
    supported_sonic_neighbors,
)
from scripts.evaluate_acoustic_support import evaluate_projection

FEATURES = ("tempo", "brightness", "flux", "loudness")


def profile(identity: str, position: float, count: int = 2) -> ArtistDescriptors:
    """Make explicit numeric test profiles, without musical labels or audio."""
    values = {
        "tempo": position * 2.0,
        "brightness": position * 3.0 + 3.0,
        "flux": position + 2.0,
        "loudness": position - 3.0,
    }
    return ArtistDescriptors(identity, count, values, dict.fromkeys(values, count))


class AcousticSupportTests(unittest.TestCase):
    @override
    def setUp(self) -> None:
        self.training = tuple(profile(str(i), float(i)) for i in range(4))
        self.frame = fit_acoustic_support(self.training, FEATURES)
        self.query = profile("query", 1.5)

    def test_fixed_frame_matches_baseline_and_is_order_invariant(self) -> None:
        result = supported_sonic_neighbors(self.query, self.training, self.frame)
        scales = {row.feature: row.scale for row in self.frame.descriptors}
        self.assertEqual(result["neighbors"], sonic_neighbors(self.query, self.training, scales))
        self.assertEqual(
            result,
            supported_sonic_neighbors(
                self.query,
                tuple(reversed(self.training)),
                fit_acoustic_support(tuple(reversed(self.training)), tuple(reversed(FEATURES))),
            ),
        )
        for neighbor in result["neighbors"]:
            self.assertEqual(neighbor["shared_features"], sorted(FEATURES))
        self.assertNotIn(self.query.artist_id, self.frame.training_artist_ids)
        self.assertTrue(
            all(self.query.artist_id not in s.training_artist_ids for s in self.frame.descriptors)
        )

    def test_unit_change_preserves_distances_and_range_decisions(self) -> None:
        def units(row: ArtistDescriptors) -> ArtistDescriptors:
            values = {
                k: value * 100.0 + 300.0 if value is not None else None
                for k, value in row.values.items()
            }
            return replace(row, values=values)

        changed = supported_sonic_neighbors(
            units(self.query),
            tuple(units(row) for row in self.training),
            fit_acoustic_support(tuple(units(row) for row in self.training), FEATURES),
        )
        before = supported_sonic_neighbors(self.query, self.training, self.frame)
        self.assertEqual(changed["status"], before["status"])
        for left, right in zip(changed["neighbors"], before["neighbors"], strict=True):
            self.assertEqual(left["artist_id"], right["artist_id"])
            self.assertAlmostEqual(float(str(left["distance"])), float(str(right["distance"])))

    def test_extreme_held_out_query_abstains_while_baseline_ranks_it(self) -> None:
        query = profile("extreme", 1000.0)
        scales = {row.feature: row.scale for row in self.frame.descriptors}
        self.assertEqual(len(sonic_neighbors(query, self.training, scales)), 4)
        result = supported_sonic_neighbors(query, self.training, self.frame)
        self.assertEqual(result["abstention_reason"], "outside_training_support")
        self.assertEqual(result["neighbors"], [])
        self.assertEqual(self.frame, fit_acoustic_support(self.training, FEATURES))

    def test_partial_candidate_cannot_compete_with_full_descriptor_distance(self) -> None:
        partial = profile("partial", 1.5)
        partial = replace(
            partial,
            values={**partial.values, "flux": None},
            observed_counts={**partial.observed_counts, "flux": 0},
        )
        scales = {row.feature: row.scale for row in self.frame.descriptors}
        self.assertEqual(len(sonic_neighbors(self.query, (partial,), scales)), 1)
        result = supported_sonic_neighbors(self.query, (*self.training, partial), self.frame)
        self.assertEqual(
            result["candidate_abstentions"],
            [{"artist_id": "partial", "reason": "incomplete_descriptors"}],
        )
        self.assertNotIn("partial", [row["artist_id"] for row in result["neighbors"]])

    def test_missing_sparse_and_empty_population_remain_explicit(self) -> None:
        sparse = profile("sparse", 1.5, count=1)
        self.assertEqual(
            supported_sonic_neighbors(sparse, self.training, self.frame)["abstention_reason"],
            "insufficient_recordings",
        )
        frame = fit_acoustic_support(self.training[:2], FEATURES)
        self.assertEqual(
            supported_sonic_neighbors(self.query, self.training, frame)["abstention_reason"],
            "insufficient_training_support",
        )
        self.assertEqual(
            supported_sonic_neighbors(self.query, (), self.frame)["abstention_reason"],
            "no_supported_candidates",
        )

    def test_constants_and_undersupported_features_are_not_distance_dimensions(self) -> None:
        training = tuple(
            replace(
                row,
                values={**row.values, "constant": 1.0, "rare": None},
                observed_counts={**row.observed_counts, "constant": 2, "rare": 0},
            )
            for row in self.training
        )
        frame = fit_acoustic_support(training, (*FEATURES, "constant", "rare"))
        self.assertEqual([row.feature for row in frame.descriptors], sorted(FEATURES))

    def test_invalid_observations_duplicates_and_support_policy_fail(self) -> None:
        for value in (math.inf, math.nan, True):
            with self.subTest(value=value), self.assertRaises(ValueError):
                fit_acoustic_support(
                    (
                        replace(
                            self.training[0], values={**self.training[0].values, "tempo": value}
                        ),
                    ),
                    FEATURES,
                )
        with self.assertRaises(ValueError):
            fit_acoustic_support((*self.training, self.training[0]), FEATURES)
        with self.assertRaises(ValueError):
            fit_acoustic_support(
                (
                    replace(
                        self.training[0],
                        observed_counts={**self.training[0].observed_counts, "tempo": 0},
                    ),
                ),
                FEATURES,
            )
        with self.assertRaises(ValueError):
            fit_acoustic_support(
                self.training,
                FEATURES,
                policy=AcousticSupportPolicy(maximum_standardized_offset=0.0),
            )


class PortableAcousticSupportTests(unittest.TestCase):
    def test_actual_receipt_bound_projection_preserves_sparse_denominators(self) -> None:
        root = Path(__file__).resolve().parents[2]
        projection = root / "data/examples/acoustic-descriptors/acoustic-descriptors.json"
        receipt = root / "data/examples/acoustic-descriptors/receipt.json"
        report = evaluate_projection(projection, receipt)
        self.assertEqual(
            report["coverage"],
            {
                "queries": 10,
                "baseline_ranked_queries": 10,
                "baseline_ranked_pairs": 90,
                "supported_queries": 6,
                "supported_pairs": 30,
                "query_abstentions": {"insufficient_recordings": 4},
            },
        )
        for outcome in report["outcomes"]:
            result, frame = outcome["supported_comparison"], outcome["training_frame"]
            self.assertNotIn(outcome["query"], frame["training_artist_ids"])
            self.assertEqual(len(result["fixed_features"]), 14)
            for neighbor in result["neighbors"]:
                self.assertEqual(neighbor["shared_features"], result["fixed_features"])
        self.assertFalse(report["scope"]["native_feature_custody_verified"])
        self.assertFalse(report["scope"]["independent_musical_relevance_evaluated"])

    def test_actual_projection_reordering_and_matching_hash_tag_injection(self) -> None:
        root = Path(__file__).resolve().parents[2]
        source = root / "data/examples/acoustic-descriptors"
        original = evaluate_projection(
            source / "acoustic-descriptors.json", source / "receipt.json"
        )
        artifact = json.loads((source / "acoustic-descriptors.json").read_bytes())
        proof = json.loads((source / "receipt.json").read_bytes())
        artifact["artists"].reverse()
        artifact["features"].reverse()
        with tempfile.TemporaryDirectory() as directory:
            projection, receipt = (
                Path(directory) / "projection.json",
                Path(directory) / "receipt.json",
            )
            projection.write_text(json.dumps(artifact))
            proof["projection_sha256"] = hashlib.sha256(projection.read_bytes()).hexdigest()
            receipt.write_text(json.dumps(proof))
            report = evaluate_projection(projection, receipt)
            self.assertEqual(report["coverage"], original["coverage"])
            for actual, expected in zip(report["outcomes"], original["outcomes"], strict=True):
                self.assertEqual(actual["query"], expected["query"])
                self.assertEqual(actual["supported_comparison"], expected["supported_comparison"])
                self.assertEqual(actual["training_frame"], expected["training_frame"])
            artifact["artists"][0]["genres"] = ["electronic"]
            projection.write_text(json.dumps(artifact))
            proof["projection_sha256"] = hashlib.sha256(projection.read_bytes()).hexdigest()
            receipt.write_text(json.dumps(proof))
            with self.assertRaisesRegex(ValueError, "unapproved acoustic profile fields"):
                evaluate_projection(projection, receipt)
