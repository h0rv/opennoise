"""Check reconstruction isolation, constrained optimization, and source explanations."""

from __future__ import annotations

import hashlib
import json
import unittest
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
from scipy import sparse

from opennoise.common import canonical_json, sha256_file
from opennoise.ml.direct_custody_neighborhoods import ObservationIndex, observation_index
from opennoise.ml.direct_custody_reconstruction import (
    ARMS,
    REVISION,
    ReconstructionMetric,
    build_reconstruction,
    evaluate_transfer,
    fit_transfer,
    load_reconstruction,
    predict_artist_genres,
    select_arm,
    split_observations,
    verify_artist_proposal,
)


class DirectCustodyReconstructionTests(unittest.TestCase):
    def test_nested_holdout_is_disjoint_complete_and_order_independent(self) -> None:
        source = {"a": tuple(f"artist-{i}" for i in range(100)), "b": ("one", "two")}
        outer, test = split_observations(source, partition="outer")
        inner, validation = split_observations(outer, partition="inner")
        for seed, original in source.items():
            self.assertFalse(set(inner[seed]) & set(validation[seed]))
            self.assertFalse(set(inner[seed]) & set(test[seed]))
            self.assertFalse(set(validation[seed]) & set(test[seed]))
            self.assertEqual(
                set(original), set(inner[seed]) | set(validation[seed]) | set(test[seed])
            )
        self.assertEqual((len(inner["a"]), len(validation["a"]), len(test["a"])), (64, 16, 20))
        self.assertEqual(inner["b"], source["b"])
        reversed_source = {seed: tuple(reversed(values)) for seed, values in source.items()}
        self.assertEqual((outer, test), split_observations(reversed_source, partition="outer"))
        self.assertNotEqual(test, split_observations(source, partition="other")[1])

    def test_ridge_is_zero_diagonal_constrained_least_squares_solution(self) -> None:
        index = observation_index({"a": ("one", "two"), "b": ("one", "three"), "c": ("one",)})
        gram = (index.binary.T @ index.binary).toarray().astype(float)
        transfer = fit_transfer(index, "ridge_10")
        np.testing.assert_array_equal(np.diag(transfer), np.zeros(3))
        for target in range(3):
            features = np.array([j for j in range(3) if j != target])
            expected = np.linalg.solve(
                gram[np.ix_(features, features)] + 10 * np.eye(2), gram[features, target]
            )
            np.testing.assert_allclose(transfer[features, target], expected, rtol=1e-12)

    def test_all_arms_count_cold_targets_and_reject_leakage(self) -> None:
        index = observation_index({"a": ("one", "two"), "b": ("one", "two", "target")})
        for arm in ARMS:
            transfer = fit_transfer(index, arm)
            metric = evaluate_transfer(index, {"a": ("target", "cold")}, transfer)
            self.assertEqual(metric.positive_count, 2)
            self.assertEqual(metric.hits_at_1, 1)
            self.assertEqual(metric.cold_artist_positive_count, 1)
            self.assertEqual(metric.recall_at_10, 0.5)
            with self.assertRaisesRegex(ValueError, "leaked"):
                evaluate_transfer(index, {"a": ("one",)}, transfer)
        transfer = fit_transfer(index, ARMS[0])
        with self.assertRaisesRegex(ValueError, "missing"):
            evaluate_transfer(index, {"unknown": ("one",)}, transfer)
        with self.assertRaisesRegex(ValueError, "duplicate"):
            evaluate_transfer(index, {"a": ("cold", "cold")}, transfer)

    def test_validation_selection_and_declared_tie_rule(self) -> None:
        index = observation_index({"a": ("one",), "b": ("two",)})
        empty = evaluate_transfer(index, {}, fit_transfer(index, ARMS[0]))
        metrics = dict.fromkeys(ARMS, empty)
        self.assertEqual(select_arm(metrics), ARMS[0])
        metrics["ridge_100"] = replace(empty, recall_at_10=0.5, mrr_at_10=0.2)
        metrics["ridge_10"] = replace(empty, recall_at_10=0.5, mrr_at_10=0.3)
        self.assertEqual(select_arm(metrics), "ridge_10")
        metrics[ARMS[0]] = replace(empty, macro_seed_recall_at_10=0.4)
        self.assertEqual(select_arm(metrics), ARMS[0])

    def test_signed_contributions_sum_to_score_and_known_genres_are_excluded(self) -> None:
        index = observation_index({"a": ("query",), "b": ("query",), "c": ("other",)})
        matrix = np.array([[0, 100, 2], [100, 0, -0.5], [0, 0, 0]], dtype=float)
        result = predict_artist_genres(index, matrix, "query")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["seed_id"], "c")
        self.assertEqual(result[0]["score"], 1.5)
        self.assertEqual(
            result[0]["contributions"],
            [
                {"seed_id": "a", "weight": 2.0},
                {"seed_id": "b", "weight": -0.5},
            ],
        )
        self.assertEqual(predict_artist_genres(index, matrix, "cold"), [])
        matrix[1, 2] = -3
        self.assertEqual(predict_artist_genres(index, matrix, "query"), [])

    def test_signed_proposal_replay_rejects_removed_opposition_and_wrong_score(self) -> None:
        index = observation_index({"a": ("query",), "b": ("query",), "c": ("other",)})
        matrix = np.array([[0, 100, 2], [100, 0, -0.5], [0, 0, 0]], dtype=float)
        verify_artist_proposal(
            index=index,
            transfer=matrix,
            seed_id="c",
            artist_mbid="query",
            score=1.5,
            via_seed_ids=("a",),
            opposing_seed_ids=("b",),
        )
        with self.assertRaisesRegex(ValueError, "do not replay"):
            verify_artist_proposal(
                index=index,
                transfer=matrix,
                seed_id="c",
                artist_mbid="query",
                score=1.5,
                via_seed_ids=("a",),
                opposing_seed_ids=(),
            )
        with self.assertRaisesRegex(ValueError, "do not replay"):
            verify_artist_proposal(
                index=index,
                transfer=matrix,
                seed_id="c",
                artist_mbid="query",
                score=2,
                via_seed_ids=("a",),
                opposing_seed_ids=("b",),
            )
        with self.assertRaisesRegex(ValueError, "duplicates a direct"):
            verify_artist_proposal(
                index=index,
                transfer=matrix,
                seed_id="a",
                artist_mbid="query",
                score=100,
                via_seed_ids=("b",),
                opposing_seed_ids=(),
            )

    def test_disconnected_source_genres_abstain(self) -> None:
        index = observation_index({"a": ("one",), "b": ("two",)})
        for arm in ARMS:
            transfer = fit_transfer(index, arm)
            np.testing.assert_array_equal(transfer, np.zeros((2, 2)))
            self.assertEqual(predict_artist_genres(index, transfer, "one"), [])

    def test_prediction_ties_use_canonical_seed_order(self) -> None:
        index = observation_index({"source": ("query",), "a": ("one",), "b": ("two",)})
        matrix = np.array([[0, 0, 0], [0, 0, 0], [1, 1, 0]], dtype=float)
        self.assertEqual(predict_artist_genres(index, matrix, "query", limit=1)[0]["seed_id"], "a")

    def test_coefficient_bytes_verified_before_loading(self) -> None:
        index = observation_index({"a": ("one",), "b": ("two",)})
        with TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / "model.json").write_bytes(b"{}")
            (directory / "identities.json").write_bytes(
                canonical_json({"artists": index.artists, "seeds": index.seeds})
            )
            sparse.save_npz(directory / "observations.npz", index.binary)
            np.save(directory / "transfer.npy", fit_transfer(index, "ridge_10"))
            report = {
                "revision": REVISION,
                "artist_count": len(index.artists),
                "observed_seed_count": len(index.seeds),
                "files": {
                    name: {
                        "sha256": sha256_file(directory / name)[0],
                        "bytes": (directory / name).stat().st_size,
                    }
                    for name in (
                        "model.json",
                        "identities.json",
                        "observations.npz",
                        "transfer.npy",
                    )
                },
            }
            report["output_sha256"] = hashlib.sha256(canonical_json(report)).hexdigest()
            (directory / "report.json").write_text(json.dumps(report))
            self.assertEqual(load_reconstruction(directory)[0].artists, index.artists)
            with (directory / "transfer.npy").open("ab") as stream:
                stream.write(b"tampered")
            with self.assertRaisesRegex(ValueError, "byte binding"):
                load_reconstruction(directory)

    def test_orchestration_selects_before_test_and_refits_separate_partitions(self) -> None:
        source = {"seed": tuple(f"artist-{i}" for i in range(100))}
        outer, test = split_observations(source, partition="outer")
        inner, validation = split_observations(outer, partition="inner")
        base = evaluate_transfer(observation_index(inner), validation, np.zeros((1, 1)))
        calls = []

        def evaluate(
            index: ObservationIndex,
            targets: dict[str, tuple[str, ...]],
            transfer: np.ndarray,
        ) -> ReconstructionMetric:
            del transfer
            position = len(calls)
            calls.append((index.binary.nnz, targets))
            # Last validation arm wins; baseline wins test, which must not reselect.
            score = float(position in (len(ARMS) - 1, len(ARMS)))
            return replace(base, recall_at_10=score)

        cache = Path(__file__).resolve().parents[2] / ".cache"
        cache.mkdir(exist_ok=True)
        with TemporaryDirectory(dir=cache) as temporary:
            root = Path(temporary)
            receipt = root / "receipt.json"
            receipt.write_text("fixture")
            mocked_receipt = SimpleNamespace(output_sha256="1" * 64, claims_object_sha256="2" * 64)
            claims = [
                SimpleNamespace(seed_id="seed", artist_mbid=artist) for artist in source["seed"]
            ]
            module = "opennoise.ml.direct_custody_reconstruction"
            with (
                patch(
                    f"{module}.DirectProperGenreCustodyReceipt.model_validate_json",
                    return_value=mocked_receipt,
                ),
                patch(
                    f"{module}.iter_verified_portable_direct_proper_genre_claims",
                    return_value=claims,
                ),
                patch(f"{module}.evaluate_transfer", side_effect=evaluate),
            ):
                report = build_reconstruction(
                    receipt_path=receipt, object_store=root, output=root / "run"
                )
            self.assertEqual(report["selected_arm"], ARMS[-1])
            self.assertEqual(calls[: len(ARMS)], [(64, validation)] * len(ARMS))
            self.assertEqual(calls[len(ARMS) :], [(80, test)] * 2)
            self.assertEqual(load_reconstruction(root / "run")[0].binary.nnz, 100)

    def test_public_destination_is_rejected_before_source_read(self) -> None:
        with self.assertRaisesRegex(ValueError, "inside project .cache"):
            build_reconstruction(
                receipt_path=Path("missing"), object_store=Path("missing"), output=Path("dist")
            )
