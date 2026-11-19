import numpy as np
import polars as pl
import pytest
from scipy import sparse

from opennoise import sonic
from opennoise.layout import audio_captions, best_islands


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


class Projection:
    def transform(self, vectors):
        return vectors[:, :2]


def test_place_shared_projection_and_empty_memberships():
    state = {
        "model": Projection(),
        "center": np.zeros(2),
        "rotation": np.eye(2),
        "reference": np.array([[0, 0], [0.5, 0.5], [1, 1]]),
        "repulsion": sonic.fit_repulsion(np.array([[0, 0], [0.5, 0.5], [1, 1]]), 3),
    }
    vectors = np.eye(2)
    points, placed, counts = sonic.place(
        state, sparse.csr_matrix([[1, 0], [0, 1], [0, 0]]), vectors, 1
    )
    np.testing.assert_allclose(points, sonic.transform(state, vectors))
    assert placed.tolist() == [True, True, False]
    assert counts.tolist() == [1, 1, 0]
    assert sonic.transform(state, np.empty((0, 2))).shape == (0, 2)


def test_fit_orientation_and_ranks_use_training_only(monkeypatch):
    class Embedding(Projection):
        def __init__(self, **kwargs):
            self.parameters = kwargs

        def fit_transform(self, vectors):
            return self.transform(vectors)

    monkeypatch.setattr(sonic, "UMAP", Embedding)
    vectors = np.array([[0.0, 0], [1, 0], [0, 1], [0.3, 0.8]])
    train = np.array([True, True, True, False])
    audio = vectors @ np.array([[0.0, -1], [1, 0]])
    config = {
        "sonic_neighbors": 2,
        "sonic_min_dist": 0.8,
        "umap_epochs": 10,
        "sonic_epochs": 1000,
        "sonic_repulsion_steps": 3,
        "seed": 42,
    }
    state, points = sonic.fit(vectors, audio, train, config)
    assert state["model"].parameters["n_epochs"] == 1000
    np.testing.assert_allclose(state["rotation"].T @ state["rotation"], np.eye(2), atol=1e-12)
    np.testing.assert_allclose(points, sonic.transform(state, vectors), atol=1e-12)
    audio[-1] = [999, -999]
    _, other = sonic.fit(vectors, audio, train, config)
    np.testing.assert_allclose(points, other)
    audio[-1] = vectors[-1] = [999, -999]
    other_state, _ = sonic.fit(vectors, audio, train, config)
    np.testing.assert_array_equal(state["repulsion"], other_state["repulsion"])
    with pytest.raises(ValueError, match="at least three"):
        sonic.fit(vectors, audio, ~train, config)


def test_place_aggregates_float32_vectors_in_float64(monkeypatch):
    captured = []
    monkeypatch.setattr(
        sonic, "transform", lambda state, vectors: captured.append(vectors) or vectors[:, :2]
    )
    vectors = np.random.default_rng(42).normal(size=(100, 3)).astype(np.float32)
    membership = sparse.csr_matrix(np.ones((1, 100), dtype=np.float32))
    sonic.place({}, membership, vectors, 3)
    expected = vectors.astype(float).sum(axis=0, keepdims=True)
    expected /= np.linalg.norm(expected, axis=1, keepdims=True)
    assert captured[0].dtype == np.float64
    np.testing.assert_allclose(captured[0], expected, atol=1e-15)


def test_repulsion_deterministic_bounded_and_subset_replay():
    points = np.random.default_rng(42).beta(0.5, 2, (100, 2))
    fields = sonic.fit_repulsion(points, 60)
    np.testing.assert_array_equal(fields, sonic.fit_repulsion(points, 60))
    projected = sonic.repulsion_transform(fields, points)
    np.testing.assert_array_equal(projected[::7], sonic.repulsion_transform(fields, points[::7]))
    assert projected.shape == points.shape
    assert np.isfinite(projected).all() and (projected >= 0).all() and (projected <= 1).all()
    assert not np.array_equal(projected, points)
    assert sonic.repulsion_transform(fields, np.empty((0, 2))).shape == (0, 2)
    np.testing.assert_array_equal(sonic.repulsion_transform([], points), points)
    assert sonic.fit_repulsion(points, 0) == []


@pytest.mark.parametrize("points", [[], [[0, 1, 2]], [[np.nan, 0]], [[0, np.inf]]])
def test_repulsion_invalid_points(points):
    with pytest.raises(ValueError, match="finite.*array"):
        sonic.repulsion_transform([], points)


def test_repulsion_invalid_fit_and_fields():
    with pytest.raises(ValueError, match="training points"):
        sonic.fit_repulsion(np.empty((0, 2)), 1)
    for steps in [-1, 0.5]:
        with pytest.raises(ValueError, match="nonnegative integer"):
            sonic.fit_repulsion(np.zeros((3, 2)), steps)
    for field in [np.zeros((3, 3, 2)), np.full((33, 33, 2), np.nan)]:
        with pytest.raises(ValueError, match="fields"):
            sonic.repulsion_transform([field], np.zeros((3, 2)))


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


def test_captions_use_heldout_features_and_handle_missing_audio():
    artists = pl.DataFrame({"item": range(5), "listeners": [2] * 5})
    features = pl.DataFrame({"item": range(5), "danceability": range(5)})
    points = np.array([[100, 100], [0, 3], [1, 2], [2, 1], [3, 0]])
    heldout = np.array([False, True, True, True, True])
    captions, scores = audio_captions(features, artists, sparse.eye(5), points, heldout)
    assert captions["x_max"] == "Higher danceability"
    assert captions["y_max"] == "Lower danceability"
    assert scores["x"]["danceability"] == {"rho": 1, "genres": 4}
    captions, scores = audio_captions(features.head(0), artists, sparse.eye(5), points, heldout)
    assert "Listening component" in captions["x_min"]
    assert scores == {"x": {}, "y": {}}
