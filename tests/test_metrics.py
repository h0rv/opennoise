import math

import pytest

from opennoise.metrics import overlap, ranking


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
