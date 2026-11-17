import math

import numpy as np
import pytest

from opennoise.metrics import average_precision, best_cluster, name_agreement, overlap, ranking


def test_ranking():
    recall, ndcg = ranking([1, 3, 2], [1, 2], 3)
    assert recall == 1
    assert ndcg == pytest.approx(1.5 / (1 + 1 / math.log2(3)))


def test_empty():
    assert ranking([], []) == (0, 0)
    assert ranking([], [1]) == (0, 0)
    assert overlap([], [], 10) == 0


def test_cutoff():
    assert ranking([3, 2, 1], [1], 2) == (0, 0)
    assert overlap([1, 2, 3], [3, 2, 1], 2) == 0.5


def test_no_hits():
    assert ranking([1, 2], [3, 4], 2) == (0, 0)


def test_invalid_input():
    with pytest.raises(ValueError, match="positive"):
        ranking([], [], 0)
    with pytest.raises(ValueError, match="positive"):
        overlap([], [], -1)
    with pytest.raises(ValueError, match="unique"):
        ranking([1, 1], [1])


def test_average_precision():
    assert average_precision([1, 3, 2], [1, 2]) == pytest.approx((1 + 2 / 3) / 2)
    assert average_precision([1], [1, 2]) == 0.5
    assert average_precision([], [1]) == 0
    assert average_precision([1], []) == 0
    with pytest.raises(ValueError, match="unique"):
        average_precision([1, 1], [1])


def test_best_cluster():
    levels = [np.array([0, 0, 0, 1]), np.array([0, 0, 1, 2])]
    assert best_cluster([0, 1], levels) == (1, 1, 0)
    assert best_cluster([], levels) == (0, -1, -1)
    assert best_cluster([0], []) == (0, -1, -1)
    with pytest.raises(IndexError):
        best_cluster([10], levels)


def test_name_agreement():
    assert name_agreement("IDM", "idm") == (1, 1)
    assert name_agreement("dream-pop", "dream pop") == (1, 1)
    assert name_agreement("dream pop", "pop") == (0, 0.5)
    assert name_agreement("", "") == (0, 0)
