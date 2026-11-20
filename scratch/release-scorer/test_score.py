import json

import numpy as np
import pytest
from scipy import sparse
from score import Scorer, nearest, shared


def test_nearest_excludes_self_and_preserves_tie_order():
    neighbors = nearest(np.zeros((12, 2)))
    for index, row in enumerate(neighbors):
        assert row.tolist() == [other for other in range(12) if other != index][:10]
    np.testing.assert_array_equal(shared(neighbors, neighbors), np.ones(12))


@pytest.mark.parametrize("points", [[], np.empty((0, 2)), np.zeros((10, 2)), [[np.nan]] * 11])
def test_nearest_rejects_empty_short_and_invalid_inputs(points):
    with pytest.raises(ValueError, match="finite vectors"):
        nearest(points)


def test_release_uses_stable_ids_not_names_or_record_order(tmp_path):
    scorer = Scorer.__new__(Scorer)
    scorer.ids = [f"id-{i}" for i in range(11)]
    points = np.arange(22).reshape(11, 2)
    scorer.raw = scorer.enao = nearest(points)
    scorer.wd = sparse.eye(11, format="csr")
    scorer.wrandom = np.zeros(11)
    scorer.heldout = np.arange(11) % 2 == 0
    rows = [
        {"id": identifier, "name": "renamed", "positions": {"axes": {"x": x, "y": y}}}
        for identifier, (x, y) in zip(scorer.ids, points.tolist(), strict=True)
    ]
    (tmp_path / "genres.json").write_text(json.dumps(rows[::-1]))
    (tmp_path / "manifest.json").write_text(json.dumps({"release_id": "fixture"}))
    result = scorer.score_release(tmp_path)
    assert result["enao"] == result["retention"] == 1.0
    assert result["wikidata"] == 0.0
    assert result["pool"] == 11
    assert result["heldout"]["n"] == 6
    (tmp_path / "genres.json").write_text("[]")
    with pytest.raises(ValueError, match="missing 11 frozen IDs"):
        scorer.score_release(tmp_path)
    with pytest.raises(ValueError, match="shape"):
        scorer.score(np.zeros((11, 3)))
