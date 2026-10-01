"""Evidence, hierarchy, and deterministic partition tests for inferred music topics."""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
from scipy import sparse

from opennoise.ml.emergent_topics import (
    TopicSettings,
    _split,
    _split_candidate,
    build_emergent_topics,
    fit_topics,
    load_features,
)


def _feature(value: str, namespace: str = "artist_tag", weight: float = 1) -> dict[str, object]:
    return {
        "namespace": namespace,
        "value": value,
        "weight": weight,
        "evidence_refs": [f"source:{value}"],
    }


def _rows() -> list[dict[str, object]]:
    return [
        {
            "artist_mbid": f"artist-{leaf}-{artist:02}",
            "features": [
                _feature(f"family {leaf // 4}"),
                _feature(f"branch {leaf // 2}"),
                _feature(f"texture {leaf}"),
            ],
        }
        for leaf in range(8)
        for artist in range(20)
    ]


def _write(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))


class EmergentTopicTests(unittest.TestCase):
    def test_small_outlier_initialization_cannot_block_a_supported_partition(self) -> None:
        matrix = sparse.csr_matrix([[1, 0, 0], [0.8, 0.6, 0], [0, 0, 1]], dtype=float)
        counts = np.array([1000, 30, 4])
        settings = TopicSettings(minimum_artists=20)
        self.assertIsNone(_split_candidate(matrix, counts, settings, 0.5))
        result = _split(matrix, counts, settings)
        assert result is not None
        labels, gain = result
        self.assertEqual(sorted(int(counts[labels == side].sum()) for side in (0, 1)), [34, 1000])
        self.assertGreater(gain, settings.minimum_split_gain)

    def test_real_hierarchical_splits_and_overlapping_assignments_have_auditable_labels(
        self,
    ) -> None:
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "features.jsonl"
            _write(path, _rows())
            data = load_features(path)
            model, assignments = fit_topics(
                data, TopicSettings(depths=(1, 2, 3), minimum_artists=10)
            )
        coverage = model["coverage"]
        assert isinstance(coverage, dict)
        self.assertEqual(coverage["community_count_by_level"], {"broad": 2, "sub": 4, "micro": 8})
        self.assertEqual(coverage["assigned_by_level"], {"broad": 160, "sub": 160, "micro": 160})
        node_rows = model["communities"]
        assert isinstance(node_rows, list)
        communities = {row["id"]: row for row in node_rows}
        for node in communities.values():
            self.assertEqual(node["label_origin"], "derived_feature_descriptors")
            self.assertFalse(node["quality_evaluated"])
            self.assertGreaterEqual(len({item["value"] for item in node["descriptors"]}), 2)
            if node["parent_id"]:
                self.assertIn(node["id"], communities[node["parent_id"]]["child_ids"])
        self.assertTrue(
            all(
                item["role"] == "inferred_community_membership"
                for items in assignments.values()
                for item in items
            )
        )

    def test_child_assignments_require_assigned_ancestors_even_at_high_threshold(self) -> None:
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "features.jsonl"
            _write(path, _rows())
            model, assignments = fit_topics(
                load_features(path),
                TopicSettings(
                    depths=(1, 2, 3),
                    minimum_artists=10,
                    membership_threshold=0.9,
                ),
            )
        node_rows = model["communities"]
        assert isinstance(node_rows, list)
        parents = {node["id"]: node["parent_id"] for node in node_rows}
        # Exact leaf cosine is1; diffuse broad ancestors are inherited with explicit reasons.
        self.assertTrue(
            any(item["level"] == "micro" for items in assignments.values() for item in items)
        )
        for memberships in assignments.values():
            present = {item["community_id"] for item in memberships}
            for item in memberships:
                parent = parents[item["community_id"]]
                self.assertTrue(parent is None or parent in present)

    def test_identical_musical_values_cannot_split_by_area_facet_or_votes(self) -> None:
        rows: list[dict[str, object]] = [
            {
                "artist_mbid": f"artist-{i}",
                "features": [
                    _feature(
                        "Ambient", "artist_genre" if i % 2 else "release_tag", 0.5 if i % 2 else 1
                    ),
                    _feature("Glitch", "artist_tag"),
                    _feature("area-a" if i % 2 else "area-b", "area"),
                    _feature("1990s" if i % 2 else "2020s", "decade"),
                ],
            }
            for i in range(20)
        ]
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "features.jsonl"
            _write(path, rows)
            data = load_features(path)
            model, assignments = fit_topics(data, TopicSettings(minimum_artists=2))
        self.assertEqual(data.group_keys, (("ambient", "glitch"),))
        coverage = model["coverage"]
        assert isinstance(coverage, dict)
        self.assertEqual(coverage["community_count_by_level"], {"broad": 1})
        self.assertEqual(assignments["artist-0"], assignments["artist-1"])

    def test_duplicate_source_facets_never_create_two_musical_features(self) -> None:
        rows: list[dict[str, object]] = [
            {
                "artist_mbid": f"artist-{i}",
                "features": [
                    _feature("Ambient", "artist_genre"),
                    _feature("ambient", "artist_tag"),
                    _feature("ambient", "release_genre"),
                    _feature("seen live"),
                ],
            }
            for i in range(20)
        ]
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "features.jsonl"
            _write(path, rows)
            data = load_features(path)
            model, assignments = fit_topics(data, TopicSettings(minimum_artists=2))
        self.assertEqual(data.group_keys, (("ambient",),))
        coverage = model["coverage"]
        assert isinstance(coverage, dict)
        self.assertEqual(coverage["assigned_by_level"]["micro"], 0)
        self.assertTrue(
            all(item["level"] == "broad" for items in assignments.values() for item in items)
        )
        self.assertNotIn(("artist_tag", "seen live"), data.features)

    def test_generic_music_features_alone_cannot_qualify_for_micro_topics(self) -> None:
        rows: list[dict[str, object]] = _rows() + [
            {"artist_mbid": f"generic-{i}", "features": [_feature("electronic"), _feature("dance")]}
            for i in range(20)
        ]
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "features.jsonl"
            _write(path, rows)
            _model, assignments = fit_topics(
                load_features(path), TopicSettings(depths=(1, 2, 4), minimum_artists=10)
            )
        self.assertFalse(
            any(item["level"] in {"sub", "micro"} for item in assignments["generic-0"])
        )

    def test_centroid_diagnostics_bind_training_feature_columns_and_core_profiles(self) -> None:
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "features.jsonl"
            _write(path, _rows())
            data = load_features(path)
            model, _assignments = fit_topics(
                data, TopicSettings(depths=(1, 2, 3), minimum_artists=10), include_centroids=True
            )
        centroids = model["centroids"]
        groups = model["core_group_ids"]
        assert isinstance(centroids, dict)
        assert isinstance(groups, dict)
        self.assertEqual(set(centroids), set(groups))
        self.assertTrue(all(len(row) == len(data.features) for row in centroids.values()))
        self.assertTrue(
            all(0 <= group < len(data.group_keys) for values in groups.values() for group in values)
        )

    def test_artist_order_does_not_change_model_labels_ids_or_assignments(self) -> None:
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "features.jsonl"
            settings = TopicSettings(depths=(1, 2, 3), minimum_artists=10)
            _write(path, _rows())
            first = fit_topics(load_features(path), settings)
            _write(path, list(reversed(_rows())))
            second = fit_topics(load_features(path), settings)
        self.assertEqual(first, second)

    def test_country_role_and_technical_tags_do_not_create_music_profiles(self) -> None:
        rows: list[dict[str, object]] = [
            {
                "artist_mbid": f"artist-{i}",
                "features": [
                    _feature("uk"),
                    _feature("london"),
                    _feature("musician"),
                    _feature("server name"),
                    _feature("UK garage"),
                    _feature("singer-songwriter", "artist_genre"),
                    _feature("GB", "area"),
                ],
            }
            for i in range(2)
        ]
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "features.jsonl"
            _write(path, rows)
            data = load_features(path)
        self.assertEqual(data.group_keys, (("singer-songwriter", "uk garage"),))
        self.assertIn(("area", "gb"), data.features)
        self.assertNotIn(("artist_tag", "server name"), data.features)

    def test_unknown_namespace_or_missing_evidence_is_rejected(self) -> None:
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "features.jsonl"
            _write(
                path,
                [{"artist_mbid": "artist", "features": [_feature("historical", "artist_name")]}],
            )
            with self.assertRaisesRegex(ValueError, "forbidden"):
                load_features(path)
            _write(
                path,
                [
                    {
                        "artist_mbid": "artist",
                        "features": [{"namespace": "artist_tag", "value": "ambient"}],
                    }
                ],
            )
            with self.assertRaisesRegex(ValueError, "evidence"):
                load_features(path)

    def test_build_persists_complete_assignments_and_rejects_public_output(self) -> None:
        cache = Path(__file__).resolve().parents[2] / ".cache"
        with TemporaryDirectory(dir=cache) as temporary:
            root = Path(temporary)
            path = root / "features.jsonl"
            _write(path, _rows())
            report = build_emergent_topics(
                features_path=path,
                output=root / "model",
                settings=TopicSettings(depths=(1, 2, 3), minimum_artists=10),
            )
            coverage = report["coverage"]
            assert isinstance(coverage, dict)
            self.assertEqual(coverage["artist_count"], 160)
            self.assertEqual(len((root / "model/assignments.jsonl").read_text().splitlines()), 160)
            self.assertEqual(
                len((root / "model/musical-profiles.jsonl").read_text().splitlines()), 160
            )
            with self.assertRaises(FileExistsError):
                build_emergent_topics(features_path=path, output=root / "model")
            with self.assertRaisesRegex(ValueError, "inside project .cache"):
                build_emergent_topics(features_path=path, output=Path("dist/topics"))
