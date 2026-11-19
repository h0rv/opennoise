import numpy as np
import pytest

from opennoise.layout import artist_vectors


@pytest.mark.parametrize("vectors", [np.array([[3.0, 4.0]]), np.empty((0, 2))])
def test_artist_vectors(tmp_path, vectors):
    np.save(tmp_path / "als_2.npy", vectors)
    np.testing.assert_array_equal(artist_vectors({"input_run": tmp_path}, "als_2"), vectors)


def test_artist_vectors_combines_normalized_sources(tmp_path):
    np.save(tmp_path / "als_2.npy", np.array([[3.0, 4.0], [0.0, 0.0]]))
    np.save(tmp_path / "audio_ab_all.npy", np.array([[0.0, 2.0], [4.0, 3.0]]))
    np.testing.assert_allclose(
        artist_vectors({"input_run": tmp_path}, "als_2+audio_ab_all"),
        [[0.6, 0.8, 0.0, 1.0], [0.0, 0.0, 0.8, 0.6]],
    )


def test_artist_vectors_missing_source(tmp_path):
    with pytest.raises(FileNotFoundError):
        artist_vectors({"input_run": tmp_path}, "missing")
