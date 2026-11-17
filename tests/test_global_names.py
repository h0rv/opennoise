import polars as pl
import pytest

from opennoise.catalog import group_coordinates
from opennoise.grouping import aliases, global_names, readable, spelling_variant
from opennoise.metrics import normalized_name


@pytest.mark.parametrize(
    ("alias", "label"),
    [
        ("idm", "intelligent dance music"),
        ("pop", "pop music"),
        ("drum n bass", "drum and bass"),
        ("drum & bass", "drum and bass"),
        ("drum 'n' bass", "drum and bass"),
        ("alt metal", "alternative metal"),
        ("afrobeat", "afro beat"),
    ],
)
def test_spelling_variant(alias, label):
    assert spelling_variant(alias, label)


@pytest.mark.parametrize(
    ("alias", "label"),
    [
        ("60s punk", "garage rock"),
        ("604", "goa trance"),
        ("alternative rap", "alternative hip-hop"),
        ("ambient metalcore", "progressive metalcore"),
        ("popular music", "pop music"),
        ("serial music", "serialism"),
        ("", "pop music"),
        ("music", ""),
    ],
)
def test_not_spelling_variant(alias, label):
    assert not spelling_variant(alias, label)


def test_aliases_require_unambiguous_qid_and_label():
    vocabulary = pl.DataFrame(
        [
            ("Q1", "intelligent dance music", "label"),
            ("Q1", "idm", "alias"),
            ("Q2", "pop music", "label"),
            ("Q2", "pop", "alias"),
            ("Q3", "pop", "label"),
            ("Q4", "alt metal", "alias"),
            ("Q5", "garage rock", "label"),
            ("Q5", "60s punk", "alias"),
            ("Q6", "alternative metal", "label"),
            ("Q6", "alt metal", "alias"),
            ("Q7", "missing label", "alias"),
        ],
        schema=["qid", "name", "kind"],
        orient="row",
    ).with_columns(
        pl.col("name").map_elements(normalized_name, return_dtype=pl.String).alias("normalized")
    )
    assert aliases(vocabulary) == {"idm": "intelligent dance music"}
    assert aliases(vocabulary.clear()) == {}


def test_global_names_folds_aliases_under_supervised_anchor():
    rows = [
        {"id": 0, "name": "idm", "level": 0},
        {"id": 1, "name": "intelligent dance music", "level": -1},
        {"id": 2, "name": "idm · Artist", "level": 1},
    ]
    parents = {0: None, 1: None, 2: 0}
    keys = {0: "cluster:idm", 1: "enao:intelligent dance music", 2: "cluster:child"}
    original_keys = keys.copy()
    members = pl.DataFrame({"genre": [0, 1, 2], "artist": ["a"] * 3, "score": [0.8] * 3})
    result, records, added_keys, report = global_names(
        rows, parents, members, keys, {"idm": "intelligent dance music"}
    )
    assert parents == {0: 1, 1: None, 2: 1}
    assert keys == original_keys
    assert [row["id"] for row in rows] == [0, 1, 2]
    assert rows[1]["aliases"] == ["idm"]
    assert result.equals(members)
    assert records == [] and added_keys == {}
    assert report["roots"] == 1


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
