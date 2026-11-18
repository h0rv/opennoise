import numpy as np
import polars as pl
import pytest

from opennoise.lb_sessions import fuse


def test_fuse():
    artists = pl.DataFrame({"item": [0, 1, 2, 3], "artist_mbid": ["a", "b", "c", "d"]})
    edges = pl.DataFrame(
        {
            "item": [0, 0, 1, 1, 2, 2, 3, 3],
            "neighbor": [1, 2, 0, 2, 0, 1, 0, 1],
            "score": [0.8, 0.6, 0.8, 0.4, 0.6, 0.4, 0.2, 0.1],
        }
    )
    similar = pl.DataFrame(
        {
            "reference_mbid": ["a", "a", "a", "a", "a"],
            "artist_mbid": ["b", "d", "d", "outside", "a"],
            "score": [20.0, 80.0, 80.0, 100.0, 10.0],
        }
    )
    result = fuse(artists, edges, similar, 0.5, k=2)
    assert result.group_by("item").len()["len"].to_list() == [2] * 4
    first = result.filter(pl.col("item") == 0)
    assert first["neighbor"].to_list() == [1, 3]
    np.testing.assert_allclose(first["score"], [0.5, 0.4])
    pure = fuse(artists, edges, similar, 1.0, k=2)
    assert pure.filter(pl.col("item") == 0)["neighbor"].to_list() == [3, 1]
    assert pure.filter(pl.col("item") == 3)["neighbor"].to_list() == [0, 1]
    empty = similar.head(0)
    baseline = fuse(artists, edges, empty, 0.0, k=2)
    np.testing.assert_allclose(baseline["score"], edges["score"])
    zero = fuse(artists, edges, similar.with_columns(pl.lit(0.0).alias("score")), 0.5, k=2)
    np.testing.assert_allclose(zero["score"], edges["score"] * 0.5)
    with pytest.raises(ValueError, match="Weight"):
        fuse(artists, edges, similar, 1.1, k=2)
    with pytest.raises(ValueError, match="padding"):
        fuse(artists, edges.head(1), similar, 0.5, k=2)
