import polars as pl
import pytest

from opennoise.catalog import group_coordinates
from opennoise.grouping import global_names, readable


def test_global_names_preserves_existing_members_and_anchors():
    rows = [
        {"id": 0, "name": "shoegaze", "level": -1},
        {"id": 1, "name": "alternative rock", "level": -1},
        {"id": 2, "name": "alternative rock", "level": 1},
        {"id": 3, "name": "dream pop", "level": 2},
    ]
    parents = {0: None, 1: None, 2: 0, 3: 2}
    members = pl.DataFrame({"genre": [0, 1, 2, 3], "artist": ["a"] * 4, "score": [0.8] * 4})
    after, records, keys, report = global_names(
        rows, parents, members, {i: str(i) for i in parents}
    )
    assert parents == {0: None, 1: None, 2: 1, 3: 4, 4: None}
    assert after.filter(pl.col("genre") < 4).equals(members)
    assert keys == {4: "group:global:dream pop"}
    assert len(records) == 1
    assert report["top_level_nodes_per_name"] == {"1": 3}
    artists = pl.DataFrame({"artist_mbid": ["a"], "artist_name": ["Artist"], "listeners": [10]})
    readable(rows, parents, after, artists, {i: str(i) for i in parents})
    assert rows[2]["name"] == "alternative rock · Artist"
    assert rows[3]["name"] == "dream pop · Artist"


def test_global_names_empty_and_cycle():
    members = pl.DataFrame(schema={"genre": pl.Int64, "artist": pl.String, "score": pl.Float64})
    assert global_names([], {}, members, {})[3]["roots"] == 0
    with pytest.raises(ValueError, match="hierarchy"):
        global_names([], {0: 1, 1: 0}, members, {})


def test_group_coordinates_use_scores_without_modifying_existing_positions():
    placed = {
        ("artist", "a"): {"axes": {"x": 0.0, "y": 1.0}, "islands": None},
        ("artist", "b"): {"axes": {"x": 1.0, "y": 0.0}, "islands": None},
        ("genre", "existing"): {"axes": {"x": 0.1, "y": 0.2}, "islands": None},
    }
    members = pl.DataFrame({"genre": [2, 2], "artist": ["a", "b"], "score": [0.25, 0.75]})
    group_coordinates([2], members, {2: "new"}, placed)
    assert placed["genre", "new"] == {"axes": {"x": 0.75, "y": 0.25}, "islands": None}
    assert placed["genre", "existing"]["axes"] == {"x": 0.1, "y": 0.2}
    group_coordinates([], members, {}, placed)
