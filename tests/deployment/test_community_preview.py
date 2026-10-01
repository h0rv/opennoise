"""Boundary checks for the local inferred-community preview exporter."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
from scipy import sparse

from opennoise.common import sha256_file, sha256_json
from opennoise.deployment.community_preview import (
    community_positions,
    validate_hierarchy,
    verified_receipt,
)


class CommunityPreviewBoundaryTests(unittest.TestCase):
    def test_receipt_mutation_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / "artifact.json").write_text("{}", encoding="utf-8")
            receipt = {
                "files": {
                    "artifact.json": {
                        "sha256": sha256_file(directory / "artifact.json")[0],
                        "bytes": (directory / "artifact.json").stat().st_size,
                    }
                },
                "scope": "local_research_only",
            }
            receipt["output_sha256"] = sha256_json(receipt)
            receipt["scope"] = "mutated_scope"
            (directory / "report.json").write_text(json.dumps(receipt), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "identity mismatch"):
                verified_receipt(directory, "report.json")

    def test_receipt_path_escape_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / "model"
            directory.mkdir()
            receipt = {
                "files": {"../outside.json": {"sha256": "unused", "bytes": 0}},
                "scope": "local_research_only",
            }
            receipt["output_sha256"] = sha256_json(receipt)
            (directory / "report.json").write_text(json.dumps(receipt), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "escapes"):
                verified_receipt(directory, "report.json")

    def test_cyclic_hierarchy_is_rejected(self) -> None:
        model = {
            "communities": [
                {"id": "a", "parent_id": "b", "child_ids": ["b"]},
                {"id": "b", "parent_id": "a", "child_ids": ["a"]},
            ]
        }

        with self.assertRaisesRegex(ValueError, "cyclic"):
            validate_hierarchy(model)

    def test_positions_ignore_area_and_decade_centroid_columns(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            ids = ["community-a", "community-b", "community-c"]
            identities = {
                "community_ids": ids,
                "features": [
                    {"namespace": "artist_tag", "value": "house"},
                    {"namespace": "artist_genre", "value": "ambient"},
                    {"namespace": "area", "value": "berlin"},
                    {"namespace": "decade", "value": "1980s"},
                ],
            }
            (directory / "topic-feature-identities.json").write_text(
                json.dumps(identities), encoding="utf-8"
            )
            communities = [{"id": key, "level": "micro", "parent_id": None} for key in ids]
            model = {"communities": communities}
            first = sparse.csr_matrix(
                np.asarray(
                    [
                        [1.0, 0.0, 100.0, 0.0],
                        [0.7, 0.7, 0.0, 100.0],
                        [0.0, 1.0, 50.0, 50.0],
                    ]
                )
            )
            second = sparse.csr_matrix(
                np.asarray(
                    [
                        [1.0, 0.0, 0.0, 500.0],
                        [0.7, 0.7, 300.0, 0.0],
                        [0.0, 1.0, 900.0, 900.0],
                    ]
                )
            )
            sparse.save_npz(directory / "topic-centroids.npz", first)
            positions_a = community_positions(model, directory)
            sparse.save_npz(directory / "topic-centroids.npz", second)
            positions_b = community_positions(model, directory)

            self.assertTrue(positions_a)
            self.assertEqual(positions_a, positions_b)

    def test_duplicate_centroids_stay_unpositioned_when_a_third_community_connects(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            ids = ["community-a", "community-b", "community-c"]
            (directory / "topic-feature-identities.json").write_text(
                json.dumps(
                    {
                        "community_ids": ids,
                        "features": [
                            {"namespace": "artist_tag", "value": "house"},
                            {"namespace": "artist_genre", "value": "ambient"},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            sparse.save_npz(
                directory / "topic-centroids.npz",
                sparse.csr_matrix(
                    np.asarray(
                        [
                            [1.0, 0.0],
                            [1.0, 0.0],
                            [0.7, 0.7],
                        ]
                    )
                ),
            )
            model = {
                "communities": [{"id": key, "level": "micro", "parent_id": None} for key in ids]
            }

            positions = community_positions(model, directory)

            self.assertNotIn("community-a", positions)
            self.assertNotIn("community-b", positions)
            self.assertNotIn("community-c", positions)
