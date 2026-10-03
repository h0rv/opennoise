"""Meaningful numerical, train-only, held-out-label and absent-source context checks."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

import numpy as np
import zstandard

from opennoise.ml.fma_sonic_map import DIMENSIONS, Moments, derive_map, pca


def write_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    """Write only isolated native-ID test fixtures, never musical truths."""
    path.write_bytes(
        zstandard.ZstdCompressor().compress(
            b"".join((json.dumps(row) + "\n").encode() for row in rows)
        )
    )


TRAINING_FIXTURE_ROWS = 48


class SonicPCAMapTests(unittest.TestCase):
    def test_streamed_covariance_matches_independent_dense_covariance(self) -> None:
        values = np.random.default_rng(9021).normal(size=(233, DIMENSIONS))
        values[100:] += 17
        moments = Moments()
        for start in range(0, len(values), 19):
            moments.add(values[start : start + 19])
        np.testing.assert_allclose(moments.mean, values.mean(axis=0), atol=1e-12)
        np.testing.assert_allclose(
            moments.scatter / (moments.count - 1), np.cov(values.T), atol=1e-10
        )

    def test_canonical_sign_and_order_are_explicit(self) -> None:
        moments = Moments()
        moments.add(np.random.default_rng(4830).normal(size=(70, DIMENSIONS)))
        eigenvalues, axes = pca(moments)
        self.assertTrue(np.all(eigenvalues[:-1] >= eigenvalues[1:]))
        for axis in axes.T:
            self.assertGreaterEqual(axis[np.argmax(np.abs(axis))], 0)
        np.testing.assert_allclose(axes.T @ axes, np.eye(DIMENSIONS), atol=1e-12)

    def test_empty_nonfinite_and_wrong_dimension_training_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "two finite training"):
            pca(Moments())
        for bad in (np.full((2, DIMENSIONS), np.nan), np.ones((2, DIMENSIONS - 1))):
            with self.assertRaisesRegex(ValueError, "finite correctly shaped"):
                Moments().add(bad)

    def test_heldout_descriptors_and_labels_never_fit_covariance_or_genre_context(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            metadata = Path(temporary)
            ids = np.arange(1, 57)
            values = np.random.default_rng(9132).normal(size=(56, DIMENSIONS))
            folds = {
                int(identity): (
                    0 if identity <= TRAINING_FIXTURE_ROWS else 2,
                    True,
                    77 if identity <= TRAINING_FIXTURE_ROWS else 88,
                    int(identity),
                )
                for identity in ids
            }
            model = {"center": np.zeros(DIMENSIONS), "scale": np.ones(DIMENSIONS)}
            tracks = [
                {
                    "track_id": int(identity),
                    "genre_ids": [1] if identity <= TRAINING_FIXTURE_ROWS else [99],
                }
                for identity in ids
            ]
            write_rows(metadata / "tracks.jsonl.zst", tracks)
            write_rows(
                metadata / "artists.jsonl.zst",
                [
                    {"artist_id": 77, "name": "Train"},
                    {"artist_id": 88, "name": "Held out"},
                    {"artist_id": 89, "name": "No source descriptors"},
                ],
            )
            write_rows(
                metadata / "genres.jsonl.zst",
                [
                    {"genre_id": 1, "title": "Observed training"},
                    {"genre_id": 99, "title": "Only held-out source positives"},
                ],
            )
            (metadata / "projection-receipt.json").write_text(
                json.dumps({"columns": list(range(DIMENSIONS))})
            )
            with patch(
                "opennoise.ml.fma_sonic_map._load_inputs",
                return_value=(folds, model, ids, values, {}),
            ):
                first = derive_map(metadata, metadata, metadata)
            changed = values.copy()
            changed[48:] += 10000
            with patch(
                "opennoise.ml.fma_sonic_map._load_inputs",
                return_value=(folds, model, ids, changed, {}),
            ):
                second = derive_map(metadata, metadata, metadata)
            self.assertEqual(first["axes"], second["axes"])
            self.assertEqual(first["genres"], second["genres"])
            self.assertEqual(first["pca_training"]["finite_training_tracks"], 48)
            self.assertIsNone(first["genres"][1]["position"])
            self.assertEqual(first["genres"][1]["training_feature_positives"], 0)
            self.assertIsNone(first["artists"][2]["position"])
            self.assertNotEqual(first["artists"][1]["position"], second["artists"][1]["position"])
            self.assertFalse(first["artist_genres_inferred"])
            self.assertFalse(first["musical_validation_established"])
