import numpy as np
import pytest

from opennoise.placement import bounds, project


def test_bounds_finite_and_constant():
    a, b = bounds([np.array([[1.0, 3.0], [5.0, 3.0]]), np.empty((0, 2))])
    np.testing.assert_array_equal(a, [[0, 0], [1, 0]])
    assert b.shape == (0, 2)
    with pytest.raises(ValueError, match="finite"):
        bounds([np.array([[np.nan, 0]])])
    with pytest.raises(ValueError, match="finite"):
        bounds([np.empty((0, 2))])


def test_project_uses_only_training_points():
    vectors = np.eye(6)
    points = np.arange(12).reshape(6, 2)
    train = np.array([True] * 5 + [False])
    first = project(vectors, points, train, vectors[:1], {})
    points[-1] = 10000
    np.testing.assert_array_equal(first, project(vectors, points, train, vectors[:1], {}))
    assert project(vectors, points, train, np.empty((0, 6)), {}).shape == (0, 2)
