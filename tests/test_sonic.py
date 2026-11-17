import numpy as np
import polars as pl
import pytest
from scipy import sparse

from opennoise import sonic
from opennoise.layout import best_islands


@pytest.fixture
def audio():
    artists = pl.DataFrame({"item": [0, 1, 2, 3], "listeners": [2, 4, 8, 16]})
    features = pl.DataFrame(
        {
            "item": [2, 0, 1],
            "danceability": [1.0, 0.0, 0.5],
            "onset_rate": [10.0, 0.0, 5.0],
            "dynamic_complexity": [0.0, 10.0, 5.0],
            "mood_acoustic_acoustic": [0.0, 1.0, 0.5],
            "mood_electronic_electronic": [1.0, 0.0, 0.5],
        }
    )
    return artists, features


def test_artist_axes_signs_alignment_and_standardization(audio):
    artists, features = audio
    points, present = sonic.artist_axes(features, artists)
    assert present.tolist() == [True, True, True, False]
    np.testing.assert_allclose(points[:3, 0], [-np.sqrt(1.5), 0, np.sqrt(1.5)])
    np.testing.assert_allclose(points[:3, 1], [np.sqrt(1.5), 0, -np.sqrt(1.5)])
    np.testing.assert_array_equal(points[3], [0, 0])
    scaled = features.with_columns(pl.col("onset_rate") * 100 + 40)
    np.testing.assert_allclose(points, sonic.artist_axes(scaled, artists)[0])


def test_partial_audio_is_mean_imputed(audio):
    artists, features = audio
    features = features.with_columns(
        pl.when(pl.col("item") == 1).then(None).otherwise(pl.col("onset_rate")).alias("onset_rate")
    )
    points, present = sonic.artist_axes(features, artists)
    assert present.tolist() == [True, True, True, False]
    np.testing.assert_allclose(points[1], [0, 0])


def test_genre_weighting_and_audio_counts():
    matrix = sparse.csr_matrix([[1, 1, 1], [1, 0, 1], [0, 0, 0]])
    centers, placed, counts = sonic.genre_axes(
        matrix, np.array([[0, 4], [3, 1], [999, 999]]), [True, True, False], [2, 4, 8], 2
    )
    np.testing.assert_allclose(centers[0], [2, 2])
    assert counts.tolist() == [2, 1, 0]
    assert placed.tolist() == [True, False, False]


def test_rank_transform_shared_ties_constants_and_clipping():
    reference = np.array([[0, 2], [1, 2], [1, 2], [3, 2]])
    np.testing.assert_allclose(
        sonic.rank_transform(reference, reference), [[0, 0.5], [0.5, 0.5], [0.5, 0.5], [1, 0.5]]
    )
    np.testing.assert_allclose(
        sonic.rank_transform(reference, [[-1, 2], [2, 2], [9, 2]]),
        [[0, 0.5], [0.75, 0.5], [1, 0.5]],
    )
    assert sonic.rank_transform(reference, np.empty((0, 2))).shape == (0, 2)


def test_place_shared_genre_artist_transform_and_no_audio(audio):
    artists, features = audio
    matrix = sparse.csr_matrix(np.eye(4))
    genres, points, placed, audio_mask, counts = sonic.project(
        *sonic.artist_axes(features, artists), artists, matrix, 1
    )
    np.testing.assert_allclose(genres, points)
    np.testing.assert_allclose(genres, [[0, 1], [0.5, 0.5], [1, 0]])
    assert placed.tolist() == audio_mask.tolist() == [True, True, True, False]
    assert counts.tolist() == [1, 1, 1, 0]
    empty = sonic.project(*sonic.artist_axes(features.head(0), artists), artists, matrix, 1)
    assert empty[0].shape == empty[1].shape == (0, 2)
    assert not empty[2].any()


def test_invalid_features(audio):
    artists, features = audio
    with pytest.raises(pl.exceptions.ColumnNotFoundError):
        sonic.artist_axes(features.drop("onset_rate"), artists)
    with pytest.raises(pl.exceptions.ComputeError, match="1:1"):
        sonic.artist_axes(pl.concat([features, features]), artists)
    with pytest.raises(ValueError, match="no finite"):
        sonic.artist_axes(features.with_columns(pl.lit(float("nan")).alias("onset_rate")), artists)


def test_islands_selection_ignores_enao():
    results = {
        "a": {"family": "axes", "cv_neighbor_overlap@10": 1},
        "c": {"family": "islands", "cv_neighbor_overlap@10": 1, "cv_vector_overlap@10": 0.1},
        "d": {"family": "islands", "cv_neighbor_overlap@10": 0, "cv_vector_overlap@10": 0.2},
    }
    assert best_islands(results) == "d"


def test_listening_fill_uses_cosine_similarity_weights_and_only_audio_donors():
    vectors = np.array([[1.0, 0], [0.0, 2], [3.0, 4], [10.0, 0], [0.0, 0], [-1.0, 0]])
    present = np.array([True, True, False, False, False, False])
    points = np.array([[0.0, 10], [10.0, 0], [0, 0], [0, 0], [0, 0], [0, 0]])
    filled, placed = sonic.fill_artists(points, present, vectors)
    np.testing.assert_allclose(filled[2], [40 / 7, 30 / 7])
    np.testing.assert_allclose(filled[3], points[0])
    np.testing.assert_array_equal(filled[:2], points[:2])
    assert placed.tolist() == [True, True, True, True, False, False]
    assert present.tolist() == [True, True, False, False, False, False]


def test_listening_fill_without_targets_or_donors():
    present = np.array([True, True])
    points = np.array([[0.0, 1], [1.0, 0]])
    filled, placed = sonic.fill_artists(points, present, np.eye(2))
    np.testing.assert_array_equal(filled, points)
    np.testing.assert_array_equal(placed, present)
    filled, placed = sonic.fill_artists(points, ~present, np.eye(2))
    np.testing.assert_array_equal(filled, points)
    assert not placed.any()


def test_fill_restores_genre_member_counts(audio):
    artists, features = audio
    points, present = sonic.artist_axes(features, artists)
    vectors = np.array([[1.0, 0], [0.0, 1], [-1.0, 0], [1.0, 0]])
    points, present = sonic.fill_artists(points, present, vectors)
    _, placed, counts = sonic.genre_axes(
        sparse.csr_matrix([[1, 0, 0, 1]]), points, present, artists["listeners"].to_numpy(), 2
    )
    assert placed.tolist() == [True]
    assert counts.tolist() == [2]
