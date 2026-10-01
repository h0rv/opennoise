"""Verify artist map evidence, bounded selection, geometry, and abstention boundaries."""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import numpy as np
from scipy.sparse.linalg import ArpackNoConvergence

from opennoise.ml.direct_custody_artist_maps import (
    MAX_ARTISTS_PER_GENRE,
    build_genre_artist_maps,
    genre_artist_map,
)
from opennoise.ml.direct_custody_neighborhoods import observation_index


class DirectCustodyArtistMapTests(unittest.TestCase):
    def test_single_target_genre_overlap_never_creates_similarity(self) -> None:
        index = observation_index({"target": ("one", "two", "three")})
        result = genre_artist_map(index, "target")
        self.assertEqual(result["selected_count"], 3)
        self.assertEqual(result["positioned_count"], 0)
        self.assertEqual(result["abstained_count"], 3)
        self.assertEqual(result["layout_edge_count"], 0)
        artists = result["artists"]
        assert isinstance(artists, list)
        for artist in artists:
            self.assertIsNone(artist["x"])
            self.assertIsNone(artist["y"])
            self.assertEqual(artist["neighbors"], [])
            self.assertEqual(artist["abstention_reason"], "single_direct_genre")
            self.assertEqual(artist["source_affinity_score"], 0)

    def test_supported_artists_have_exact_shared_profile_explanations(self) -> None:
        index = observation_index({"target": ("one", "two", "three"), "other": ("one", "two")})
        result = genre_artist_map(index, "target")
        self.assertEqual(result["positioned_count"], 2)
        self.assertEqual(result["abstained_count"], 1)
        self.assertFalse(result["quality_evaluated"])
        artists = result["artists"]
        assert isinstance(artists, list)
        for artist in artists:
            if artist["id"] == "three":
                self.assertIsNone(artist["x"])
                continue
            self.assertTrue(0 <= artist["x"] <= 16 / 9)
            self.assertTrue(0 <= artist["y"] <= 1)
            self.assertEqual(artist["neighbors"][0]["shared_seed_ids"], ["other", "target"])
            self.assertEqual(artist["neighbors"][0]["shared_genre_count"], 2)
            self.assertAlmostEqual(artist["neighbors"][0]["score"], 1)

    def test_idf_weighted_cosine_uses_full_profile_mass(self) -> None:
        index = observation_index({"a": ("one", "two"), "b": ("one", "two"), "c": ("one",)})
        result = genre_artist_map(index, "a")
        artists = result["artists"]
        assert isinstance(artists, list)
        rare_weight = 1 + np.log(3 / 2)
        expected = 2 / np.sqrt((2 + rare_weight) * 2)
        self.assertAlmostEqual(artists[0]["neighbors"][0]["score"], expected)

    def test_selection_is_bounded_by_affinity_then_mbid_with_explicit_omissions(self) -> None:
        source = tuple(f"artist-{i:04}" for i in range(205))
        index = observation_index({"target": source, "other": source[-2:]})
        result = genre_artist_map(index, "target")
        artists = result["artists"]
        assert isinstance(artists, list)
        ids = {artist["id"] for artist in artists}
        self.assertEqual(result["total_count"], 205)
        self.assertEqual(result["selected_count"], MAX_ARTISTS_PER_GENRE)
        self.assertEqual(result["omitted_count"], 5)
        self.assertTrue(result["truncated"])
        self.assertTrue(set(source[-2:]) <= ids)
        self.assertEqual(ids, set(source[:198]) | set(source[-2:]))
        self.assertEqual(result["positioned_count"], 2)

    def test_coherent_source_profiles_beat_broad_high_degree_hubs(self) -> None:
        broad = tuple(f"broad-{i:04}" for i in range(200))
        coherent = ("z-coherent-one", "z-coherent-two")
        outsiders = tuple(f"outside-{i:04}" for i in range(800))
        memberships = {
            "target": broad + coherent,
            "focused": coherent,
            "general-a": broad + outsiders,
            "general-b": broad + outsiders,
            "general-c": broad + outsiders,
        }
        result = genre_artist_map(observation_index(memberships), "target")
        artists = result["artists"]
        assert isinstance(artists, list)
        by_id = {artist["id"]: artist for artist in artists}
        self.assertEqual(result["selected_count"], 200)
        self.assertEqual(result["omitted_count"], 2)
        self.assertTrue(set(coherent) <= set(by_id))
        self.assertEqual(set(by_id), set(broad[:198]) | set(coherent))
        self.assertEqual(by_id[coherent[0]]["direct_genre_count"], 2)
        self.assertEqual(by_id[broad[0]]["direct_genre_count"], 4)
        self.assertAlmostEqual(by_id[coherent[0]]["source_affinity_score"], 2 / 7)
        self.assertAlmostEqual(by_id[broad[0]]["source_affinity_score"], 200 / 1005)
        self.assertFalse(result["cohort_relevance_evaluated"])

    def test_singleton_other_genre_support_does_not_create_affinity(self) -> None:
        index = observation_index({"target": ("one", "two"), "unique": ("one",)})
        result = genre_artist_map(index, "target")
        artists = result["artists"]
        assert isinstance(artists, list)
        self.assertEqual([artist["source_affinity_score"] for artist in artists], [0, 0])

    def test_multigenre_profiles_without_two_shared_genres_abstain(self) -> None:
        index = observation_index({"target": ("one", "two"), "a": ("one",), "b": ("two",)})
        result = genre_artist_map(index, "target")
        self.assertEqual(result["positioned_count"], 0)
        artists = result["artists"]
        assert isinstance(artists, list)
        self.assertEqual(artists[0]["abstention_reason"], "no_two_genre_overlap_in_selected_cohort")

    def test_source_order_does_not_change_selection_scores_or_geometry(self) -> None:
        memberships = {
            "target": ("one", "two", "three"),
            "a": ("one", "two"),
            "b": ("two", "three"),
        }
        reversed_source = {
            seed: tuple(reversed(artists)) for seed, artists in reversed(memberships.items())
        }
        self.assertEqual(
            genre_artist_map(observation_index(memberships), "target"),
            genre_artist_map(observation_index(reversed_source), "target"),
        )

    def test_failed_spectral_fit_abstains_instead_of_inventing_positions(self) -> None:
        index = observation_index({"a": ("one", "two"), "b": ("one", "two")})
        error = ArpackNoConvergence("fixture", np.array([]), np.empty((0, 0)))
        with patch(
            "opennoise.ml.direct_custody_artist_maps.build_weighted_spectral_coordinates",
            side_effect=error,
        ):
            result = genre_artist_map(index, "a")
        self.assertEqual(result["positioned_count"], 0)
        self.assertEqual(result["layout_state"], "abstained_spectral_nonconvergence")
        artists = result["artists"]
        assert isinstance(artists, list)
        self.assertEqual(artists[0]["abstention_reason"], "spectral_nonconvergence")

    def test_batch_writes_each_source_genre_and_refuses_overwrite(self) -> None:
        index = observation_index({"a": ("one", "two"), "b": ("one", "two")})
        cache = Path(__file__).resolve().parents[2] / ".cache"
        with TemporaryDirectory(dir=cache) as temporary:
            output = Path(temporary) / "maps"
            result = build_genre_artist_maps(index, output_directory=output)
            self.assertEqual(result["genre_count"], 2)
            self.assertEqual(result["positioned_artist_occurrence_count"], 4)
            self.assertEqual(
                json.loads((output / "a.json").read_bytes()), genre_artist_map(index, "a")
            )
            with self.assertRaises(FileExistsError):
                build_genre_artist_maps(index, output_directory=output)

    def test_public_destinations_and_unsafe_source_filenames_are_rejected(self) -> None:
        index = observation_index({"../escape": ("one",)})
        with self.assertRaisesRegex(ValueError, "inside project .cache"):
            build_genre_artist_maps(index, output_directory=Path("dist/artist-maps"))
        cache = Path(__file__).resolve().parents[2] / ".cache"
        with TemporaryDirectory(dir=cache) as temporary, self.assertRaisesRegex(ValueError, "safe"):
            build_genre_artist_maps(index, output_directory=Path(temporary) / "maps")
        with self.assertRaisesRegex(ValueError, "observed"):
            genre_artist_map(index, "missing")
