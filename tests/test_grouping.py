import polars as pl

from opennoise.grouping import siblings


def test_siblings_existing_anchor_and_max_union():
    rows = [{"id": i, "name": "Shoegaze", "level": i - 1} for i in range(3)]
    parents = dict.fromkeys(range(3))
    memberships = pl.DataFrame(
        {"artist": ["a", "a", "b"], "genre": [0, 1, 2], "score": [0.2, 0.8, 1.0]}
    )
    result, records, keys, report = siblings(rows, parents, memberships, {0: "root"})
    assert parents == {0: None, 1: 0, 2: 0}
    assert result.filter(pl.col("genre") == 0).sort("artist")["score"].to_list() == [0.8, 1.0]
    assert result.filter(pl.col("genre") != 0).equals(memberships.filter(pl.col("genre") != 0))
    assert records == [] and keys == {}
    assert report["roots_before"] == 3 and report["roots_after"] == 1


def test_siblings_mints_per_parent_and_keeps_empty_children():
    rows = [{"id": i, "name": "Same", "level": 0} for i in range(4)]
    parents = {0: None, 1: None, 2: 0, 3: 0}
    memberships = pl.DataFrame(schema={"artist": pl.String, "genre": pl.Int64, "score": pl.Float64})
    result, records, keys, report = siblings(rows, parents, memberships, {0: "p0"})
    assert result.is_empty()
    assert len(rows) == 6 and report["minted"] == 2
    assert {r["key"] for r in records} == {"group:root:same", "group:p0:same"}
    assert set(keys) == {4, 5}
    assert parents[0] == parents[1] and parents[2] == parents[3]


def test_siblings_empty():
    memberships = pl.DataFrame(schema={"artist": pl.String, "genre": pl.Int64, "score": pl.Float64})
    result, records, keys, report = siblings([], {}, memberships, {})
    assert result.equals(memberships)
    assert records == [] and keys == {} and report["roots_after"] == 0
