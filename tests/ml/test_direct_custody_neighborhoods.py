"""Evidence-boundary and sparse-ranking tests for portable direct neighborhoods."""

from __future__ import annotations

import unittest
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from typing import TYPE_CHECKING
from unittest.mock import patch

import numpy as np

from opennoise.ml.direct_custody_neighborhoods import (
    ARMS,
    MAX_ARTIST_DEGREE,
    SHRINKAGE,
    artist_neighbors,
    build_neighborhoods,
    evaluate,
    genre_neighbors,
    load_neighborhood_index,
    observation_index,
)
from opennoise.peers.direct_custody_membership_holdout import _split_memberships

if TYPE_CHECKING:
    from opennoise.ml.direct_custody_neighborhoods import Arm, ObservationIndex, RetrievalMetric


class DirectCustodyNeighborhoodTests(unittest.TestCase):
    def test_nested_split_has_disjoint_pairs_and_preserves_small_source_genres(self) -> None:
        source = {"large": tuple(f"artist-{i}" for i in range(100)), "small": ("a", "b")}
        outer, test = _split_memberships(source)
        inner, validation = _split_memberships(outer)
        for seed, artists in source.items():
            train_pairs = set(inner[seed])
            validation_pairs = set(validation.get(seed, ()))
            test_pairs = set(test.get(seed, ()))
            self.assertFalse(train_pairs & validation_pairs)
            self.assertFalse(train_pairs & test_pairs)
            self.assertFalse(validation_pairs & test_pairs)
            self.assertEqual(train_pairs | validation_pairs | test_pairs, set(artists))
        self.assertEqual(inner["small"], source["small"])
        self.assertEqual(
            (len(inner["large"]), len(validation["large"]), len(test["large"])), (64, 16, 20)
        )

    def test_every_arm_recovers_supported_target_and_counts_cold_abstention(self) -> None:
        index = observation_index({"a": ("one", "two"), "b": ("one", "two", "target")})
        for arm in ARMS:
            metric = evaluate(index, {"a": ("target", "cold")}, arm)
            self.assertEqual(metric.positive_count, 2)
            self.assertEqual(metric.hits_at_1, 1)
            self.assertEqual(metric.cold_artist_positive_count, 1)
            self.assertEqual(metric.supported_positive_count, 1)
            self.assertEqual(metric.recall_at_10, 0.5)
            self.assertEqual(metric, evaluate(index, {"a": ("target", "cold")}, arm))

    def test_direct_target_cannot_also_be_in_training(self) -> None:
        index = observation_index({"a": ("one", "two"), "b": ("one", "two")})
        with self.assertRaisesRegex(ValueError, "leaked"):
            evaluate(index, {"a": ("one",)}, "binary_cosine")
        with self.assertRaisesRegex(ValueError, "missing"):
            evaluate(index, {"unknown": ("one",)}, "binary_cosine")

    def test_single_shared_artist_is_an_explicit_abstention(self) -> None:
        index = observation_index({"a": ("one", "target"), "b": ("one", "other")})
        for arm in ARMS:
            self.assertEqual(genre_neighbors(index, arm).nnz, 0)
        metric = evaluate(index, {"b": ("target",)}, "binary_cosine")
        self.assertEqual(metric.supported_positive_count, 0)
        self.assertEqual(metric.cold_artist_positive_count, 0)
        self.assertEqual(metric.hits_at_10, 0)

    def test_shrinkage_has_exact_shared_support_interpretation(self) -> None:
        index = observation_index({"a": ("one", "two"), "b": ("one", "two", "extra")})
        degree = genre_neighbors(index, "degree_cosine")
        shrunk = genre_neighbors(index, "degree_shrunk")
        self.assertAlmostEqual(float(shrunk[0, 1]), float(degree[0, 1]) * 2 / (2 + SHRINKAGE))
        self.assertEqual(shrunk.diagonal().tolist(), [0.0, 0.0])

    def test_canonical_ties_at_neighbor_cutoff_ignore_input_order(self) -> None:
        source = {f"seed-{i:02}": ("one", "two") for i in range(25)}
        forward = observation_index(source)
        reverse = observation_index(dict(reversed(list(source.items()))))
        self.assertEqual(forward.artists, reverse.artists)
        first = genre_neighbors(forward, "binary_cosine")
        second = genre_neighbors(reverse, "binary_cosine")
        np.testing.assert_array_equal(first.toarray(), second.toarray())
        np.testing.assert_array_equal(first[0].indices, np.arange(1, 21))

    def test_bounds_fail_before_sparse_pair_expansion_instead_of_truncating(self) -> None:
        source = {f"seed-{i}": ("hub",) for i in range(MAX_ARTIST_DEGREE + 1)}
        with self.assertRaisesRegex(ValueError, "no silent feature truncation"):
            observation_index(source)

    def test_artist_query_requires_two_explained_direct_genres_and_excludes_self(self) -> None:
        index = observation_index(
            {"a": ("query", "match", "singleton"), "b": ("query", "match"), "c": ("other",)}
        )
        result = artist_neighbors(index, "query")
        self.assertEqual([row["artist_mbid"] for row in result], ["match"])
        score = result[0]["score"]
        assert isinstance(score, float)
        self.assertAlmostEqual(score, 1.0)
        self.assertEqual(artist_neighbors(index, "singleton"), [])
        self.assertEqual(artist_neighbors(index, "missing"), [])

    def test_orchestration_refits_correct_splits_selects_without_test_and_checks_bytes(
        self,
    ) -> None:
        source = {"seed": tuple(f"artist-{i}" for i in range(100))}
        outer, test = _split_memberships(source)
        inner, validation = _split_memberships(outer)
        inner_index, outer_index = observation_index(inner), observation_index(outer)
        base = evaluate(inner_index, validation, "binary_cosine")
        calls = []

        def metric(
            index: ObservationIndex, targets: dict[str, tuple[str, ...]], arm: Arm
        ) -> RetrievalMetric:
            calls.append((index.artists, targets, arm))
            # Deliberately reverse test ordering: the preview must follow validation.
            score = float(
                arm == ("specificity_transfer" if targets == validation else "binary_cosine")
            )
            return replace(base, recall_at_10=score)

        cache = Path(__file__).resolve().parents[2] / ".cache"
        cache.mkdir(exist_ok=True)
        with TemporaryDirectory(dir=cache) as directory:
            root = Path(directory)
            receipt = root / "receipt.json"
            receipt.write_text("fixture", encoding="utf-8")
            mocked_receipt = SimpleNamespace(
                output_sha256="1" * 64, claims_object_sha256="2" * 64, claim_count=100
            )
            claims = [
                SimpleNamespace(seed_id="seed", artist_mbid=artist) for artist in source["seed"]
            ]
            module = "opennoise.ml.direct_custody_neighborhoods"
            with (
                patch(
                    f"{module}.DirectProperGenreCustodyReceipt.model_validate_json",
                    return_value=mocked_receipt,
                ),
                patch(
                    f"{module}.iter_verified_portable_direct_proper_genre_claims",
                    return_value=claims,
                ),
                patch(f"{module}.evaluate", side_effect=metric),
            ):
                report = build_neighborhoods(
                    receipt_path=receipt, object_store=root, output=root / "run"
                )
            self.assertEqual(report["selected_arm"], "specificity_transfer")
            self.assertEqual([item[0] for item in calls[:4]], [inner_index.artists] * 4)
            self.assertEqual([item[0] for item in calls[4:]], [outer_index.artists] * 4)
            self.assertEqual([item[1] for item in calls[:4]], [validation] * 4)
            self.assertEqual([item[1] for item in calls[4:]], [test] * 4)
            loaded = load_neighborhood_index(root / "run")
            self.assertEqual(loaded.binary.nnz, 100)
            with (root / "run" / "model.json").open("ab") as stream:
                stream.write(b" ")
            with self.assertRaisesRegex(ValueError, "byte binding"):
                load_neighborhood_index(root / "run")

    def test_build_refuses_public_destination_before_any_input_read(self) -> None:
        with self.assertRaisesRegex(ValueError, "below the checkout .cache"):
            build_neighborhoods(
                receipt_path=Path("missing"),
                object_store=Path("missing"),
                output=Path("dist/direct-model"),
            )


if __name__ == "__main__":
    unittest.main()
