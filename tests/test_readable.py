import polars as pl

from opennoise.grouping import readable


def test_readable_lifts_and_preserves_ids_members(tmp_path):
    rows = [
        {"id": i, "name": name} for i, name in enumerate(["Rock", "rock", "rock", "pop", "pop"])
    ]
    parents = {0: None, 1: 0, 2: 1, 3: 2, 4: 2}
    members = pl.DataFrame({"genre": [0, 1, 2, 3, 4], "artist": ["a"] * 5, "score": [1.0] * 5})
    before = members.clone()
    artists = pl.DataFrame({"artist_mbid": ["a"], "artist_name": ["Artist"], "listeners": [10]})
    report = readable(rows, parents, members, artists, {i: str(i) for i in parents})
    assert parents == {0: None, 1: 0, 2: 0, 3: 0, 4: 0}
    assert [r["id"] for r in rows] == list(range(5))
    assert members.equals(before)
    assert report["after"] == {
        "roots": 1,
        "same_name_parent_edges": 0,
        "same_name_sibling_extras": 0,
    }
    assert rows[1]["name"] == "rock · Artist"
    assert rows[2]["name"] == "rock · Artist (2)"


def test_readable_empty():
    report = readable(
        [],
        {},
        pl.DataFrame(schema={"genre": pl.Int64, "artist": pl.String, "score": pl.Float64}),
        pl.DataFrame(
            schema={"artist_mbid": pl.String, "artist_name": pl.String, "listeners": pl.Int64}
        ),
        {},
    )
    assert report["renamed"] == report["lifted"] == 0


def test_readable_renamed_parent_cannot_match_child():
    rows = [{"id": i, "name": name} for i, name in enumerate(["Root", "rock", "rock", "rock"])]
    parents = {0: None, 1: 0, 2: 0, 3: 1}
    members = pl.DataFrame({"genre": [0, 1, 2, 3], "artist": ["a"] * 4, "score": [1.0] * 4})
    artists = pl.DataFrame({"artist_mbid": ["a"], "artist_name": ["Artist"], "listeners": [10]})
    report = readable(rows, parents, members, artists, {i: str(i) for i in parents})
    assert report["after"]["same_name_parent_edges"] == 0
