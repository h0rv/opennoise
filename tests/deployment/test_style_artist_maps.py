"""Source cohort selection and nonfabricated musical-profile geometry contracts."""

import unittest

import numpy as np
from scipy import sparse

from opennoise.deployment.style_artist_maps import map_context, style_artist_map


def _artist(index: int) -> str:
    return f"00000000-0000-0000-0000-{index:012d}"


class StyleArtistMapTests(unittest.TestCase):
    def test_source_vocabulary_reordering_preserves_binary_profile_geometry(self) -> None:
        artists = tuple(_artist(index) for index in range(4))
        matrix = sparse.csr_matrix(np.asarray([[1, 1, 0], [1, 1, 0], [1, 1, 1], [0, 1, 1]]))
        reordered = matrix[:, [2, 1, 0]].tocsr()
        self.assertFalse(reordered.has_sorted_indices)
        context = map_context(artists, ["noise", "drone", "ambient"], reordered)
        result = style_artist_map(
            context, "style", {artist: ["observed_artist_feature"] for artist in artists}
        )
        self.assertEqual(result["positioned_count"], 2)
        self.assertEqual(result["layout_edge_count"], 1)
        self.assertFalse(reordered.has_sorted_indices)

    def test_identical_global_profile_abstains_when_duplicate_is_outside_cohort(self) -> None:
        artists = tuple(_artist(index) for index in range(4))
        matrix = sparse.csr_matrix(np.asarray([[1, 1, 0], [1, 1, 0], [1, 1, 1], [0, 1, 1]]))
        context = map_context(artists, ["ambient", "drone", "noise"], matrix)
        result = style_artist_map(
            context, "style", {artist: ["observed_artist_feature"] for artist in artists[1:]}
        )
        duplicate = next(row for row in result["artists"] if row["artist_mbid"] == artists[1])
        self.assertIsNone(duplicate["x"])
        self.assertEqual(duplicate["abstention_reason"], "identical_usable_source_music_profile")
        self.assertEqual(result["positioned_count"], 2)

    def test_idf_cosine_uses_global_support_and_two_distinct_shared_values(self) -> None:
        artists = tuple(_artist(index) for index in range(4))
        matrix = sparse.csr_matrix(
            np.asarray([[1, 1, 1, 0], [1, 1, 0, 1], [1, 0, 1, 0], [0, 1, 0, 1]])
        )
        context = map_context(artists, ["ambient", "drone", "noise", "dub"], matrix)
        result = style_artist_map(
            context, "style", {artist: ["observed_artist_feature"] for artist in artists[:2]}
        )
        idf = 1 + np.log(5 / np.asarray([4, 4, 3, 3]))
        expected = (idf[0] + idf[1]) / np.sqrt(sum(idf[:3]) * (idf[0] + idf[1] + idf[3]))
        self.assertAlmostEqual(result["edges"][0]["weight"], expected)
        self.assertEqual(result["edges"][0]["shared_music_value_count"], 2)
        self.assertEqual(
            result["artists"][0]["neighbors"][0]["shared_music_values"], ["ambient", "drone"]
        )

    def test_identical_profiles_abstain_even_when_a_third_artist_connects(self) -> None:
        artists = tuple(_artist(index) for index in range(4))
        matrix = sparse.csr_matrix(np.asarray([[1, 1, 0], [1, 1, 0], [1, 1, 1], [0, 1, 1]]))
        context = map_context(artists, ["ambient", "drone", "noise"], matrix)
        result = style_artist_map(
            context, "style", {artist: ["observed_artist_feature"] for artist in artists}
        )
        nodes = {row["artist_mbid"]: row for row in result["artists"]}
        for artist in artists[:2]:
            self.assertIsNone(nodes[artist]["x"])
            self.assertEqual(
                nodes[artist]["abstention_reason"], "identical_usable_source_music_profile"
            )
        self.assertEqual(result["positioned_count"], 2)
        self.assertEqual(result["layout_edge_count"], 1)

    def test_source_singletons_and_votes_do_not_create_extra_geometry(self) -> None:
        artists = tuple(_artist(index) for index in range(3))
        matrix = sparse.csr_matrix(np.asarray([[1, 1, 1], [1, 1, 0], [1, 0, 0]]))
        context = map_context(artists, ["ambient", "drone", "unique tag"], matrix)
        self.assertEqual(context.vocabulary, ("ambient", "drone"))
        invalid = matrix.copy()
        invalid.data[0] = 2
        with self.assertRaisesRegex(ValueError, "binary"):
            map_context(artists, ["ambient", "drone", "unique tag"], invalid)

    def test_inferred_proposal_memberships_cannot_enter_source_map(self) -> None:
        artist = _artist(1)
        context = map_context((artist,), ["ambient"], sparse.csr_matrix([[1]]))
        with self.assertRaisesRegex(ValueError, "source memberships only"):
            style_artist_map(context, "style", {artist: ["inferred_feature_proposal"]})

    def test_selection_is_bounded_informative_degree_then_exact_id(self) -> None:
        artists = tuple(_artist(index) for index in range(205))
        matrix = sparse.csr_matrix(np.ones((205, 2)))
        context = map_context(artists, ["ambient", "drone"], matrix)
        result = style_artist_map(
            context, "style", {artist: ["observed_artist_feature"] for artist in reversed(artists)}
        )
        self.assertEqual(result["selected_count"], 200)
        self.assertEqual(result["omitted_count"], 5)
        self.assertEqual([row["artist_mbid"] for row in result["artists"]], list(artists[:200]))
        self.assertEqual(result["positioned_count"], 0)
        self.assertTrue(result["truncated"])
