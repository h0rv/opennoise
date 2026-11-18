import numpy as np
import polars as pl
import pytest
from scipy import sparse

from opennoise import deezer, deezer_eval


def test_cached_sample_deduplicates_names_and_builds_signals(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    path = tmp_path / "artists.parquet"
    pl.DataFrame(
        {
            "item": [0, 1, 2, 3],
            "artist_name": ["Alpha", "ALPHA", "Bravo", "Charlie"],
            "listeners": [9, 7, 5, 3],
        }
    ).write_parquet(path)
    responses = {
        deezer.search("Alpha"): [{"id": 1, "name": "Others"}, {"id": 2, "name": "alpha"}],
        deezer.search("Bravo"): [{"id": 3, "name": "Bravo"}],
        deezer.search("Charlie"): [],
        "genre": [{"id": 0}, {"id": 106}],
        deezer.albums(2): [{"genre_id": 106}, {"genre_id": 0}],
        deezer.albums(3): [{"genre_id": -1}],
        deezer.related(2): [
            {"id": 2, "name": "Alpha"},
            {"id": 3, "name": "Bravo"},
            {"id": 4, "name": "CHARLIE"},
            {"id": 4, "name": "Charlie"},
        ],
        deezer.related(3): [],
    }
    monkeypatch.setattr(deezer.time, "sleep", lambda _: None)
    monkeypatch.setattr(deezer, "fetch", lambda path: {"data": responses.pop(path)})
    deezer.ingest(path, 3, 0)
    assert responses == {}
    deezer.ingest(path, 3, 0)

    edges, genres, coverage = deezer_eval.signals(path, 4, 3, 0)
    assert coverage["seeds"] == 3
    assert coverage["matched"] == 2
    assert coverage["artists_in_graph"] == 3
    assert edges.nnz == 2
    np.testing.assert_allclose(edges.toarray()[0], [0, 0, 1 / np.log2(3), 0.5])
    np.testing.assert_array_equal(genres, [106, 0, 0, 0])
    with pytest.raises(ValueError, match="sample differs"):
        deezer_eval.signals(path, 4, 2, 0)


def test_blend_normalizes_related_weights_and_only_boosts_known_shared_genres():
    listening = sparse.csr_matrix([[0.0, 2.0, 2.0], [2.0, 0.0, 1.0], [2.0, 1.0, 0.0]])
    related = sparse.csr_matrix([[0.0, 3.0, 1.0], [0.0, 0.0, 0.0], [0.0, 0.0, 0.0]])
    mixed = listening + 0.25 * deezer_eval.normalize_blend(listening, related)
    assert mixed[0, 1] == mixed[1, 0] == 2.375
    assert mixed[0, 2] == mixed[2, 0] == 2.125
    assert mixed[1, 2] == 1
    boosted = deezer_eval.boost_genres(mixed, np.array([106, 106, 0]))
    assert boosted[0, 1] == boosted[1, 0] == 2.375 * 1.25
    assert boosted[0, 2] == 2.125
    assert mixed[0, 1] == 2.375
