import numpy as np
import pytest

from opennoise.layout_metrics import evaluation_scores, layout_scores, nearest, neighbor_overlap


def test_neighbors():
    points = np.array([[0, 0], [1, 0], [4, 0], [10, 0]])
    assert nearest(points, 1).tolist() == [[1], [0], [1], [2]]
    assert neighbor_overlap(points, points, 1) == 1
    assert neighbor_overlap(points, points[[0, 2, 1, 3]], 1) == 0
    assert neighbor_overlap(points, points, 10) == 1
    assert nearest(np.zeros((3, 2)), 2).tolist() == [[1, 2], [0, 2], [0, 1]]


def test_rotation():
    points = np.random.default_rng(42).normal(size=(30, 2))
    rotated = points @ np.array([[0, -1], [1, 0]])
    assert neighbor_overlap(rotated, points) == 1


def test_cosine():
    points = np.array([[1, 0], [2, 0.1], [0, 1]])
    assert nearest(points, 1, "cosine").tolist() == [[1], [0], [1]]
    assert neighbor_overlap(points, points, 1, "cosine") == pytest.approx(2 / 3)


def test_scores():
    reference = np.array([[1, 4], [2, 3], [3, 2], [4, 1]])
    scores = layout_scores(-reference, reference, reference, 8)
    assert scores["spearman_x"] == -1
    assert scores["spearman_y"] == -1
    assert scores["coverage"] == 0.5
    assert scores["neighbor_overlap@10"] == 1
    assert "spearman_x" not in layout_scores(reference, reference, reference, 4, axes=False)
    assert layout_scores(np.ones((4, 2)), reference, reference, 4)["spearman_x"] is None


def test_empty():
    points = np.empty((0, 2))
    assert neighbor_overlap(points, points) is None
    scores = layout_scores(points, points, points, 0)
    assert scores["coverage"] == 0
    assert scores["spearman_x"] is None
    assert neighbor_overlap(np.ones((1, 2)), np.ones((1, 2))) is None


def test_invalid():
    with pytest.raises(ValueError, match="positive"):
        nearest(np.ones((2, 2)), 0)
    with pytest.raises(ValueError, match="finite"):
        nearest(np.array([[np.nan, 0]]))
    with pytest.raises(ValueError, match="counts"):
        neighbor_overlap(np.ones((2, 2)), np.ones((3, 2)))
    with pytest.raises(ValueError, match="total_test"):
        layout_scores(np.ones((2, 2)), np.ones((2, 2)), np.ones((2, 2)), 1)


def test_cv_mean_and_test_separation():
    rng = np.random.default_rng(7)
    reference = rng.normal(size=(90, 2))
    points = reference.copy()
    folds = np.repeat(np.arange(5), 15).tolist() + [0] * 15
    folds = np.array(folds)
    test = np.arange(90) >= 75
    points[15:30] = points[15:30][::-1]
    scores = evaluation_scores(points, reference, reference, test, folds, 30, [15] * 5)
    expected = [
        neighbor_overlap(points[i : i + 15], reference[i : i + 15]) for i in range(0, 75, 15)
    ]
    assert scores["cv_neighbor_overlap@10"] == pytest.approx(np.mean(expected))
    assert scores["cv_fold_overlap@10"] == expected
    assert scores["test_coverage"] == 0.5
    assert scores["cv_coverage"] == 1
    changed = points.copy()
    changed[test] = rng.normal(size=(15, 2))
    other = evaluation_scores(changed, reference, reference, test, folds, 30, [15] * 5)
    assert scores["test_neighbor_overlap@10"] != other["test_neighbor_overlap@10"]
    assert {k: v for k, v in scores.items() if k.startswith("cv_")} == {
        k: v for k, v in other.items() if k.startswith("cv_")
    }
