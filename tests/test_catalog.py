import json

import numpy as np
import polars as pl
import pytest

from opennoise.catalog import coordinates, export, hierarchy, related_genres
from opennoise.contract import validate_release


def inputs(tmp_path):
    a, b = "00000000-0000-0000-0000-000000000001", "00000000-0000-0000-0000-000000000002"
    source, m1, run = [tmp_path / p for p in ["source", "m1", "run"]]
    for path in [source, m1, run]:
        path.mkdir()
    pl.DataFrame(
        {"item": [0, 1], "artist_mbid": [a, b], "listeners": [10, 5], "artist_name": ["A", "B"]}
    ).write_parquet(m1 / "artists.parquet")
    pl.DataFrame({"item": [0], "neighbor": [1], "score": [0.5]}).write_parquet(m1 / "tfidf.parquet")
    genres = pl.DataFrame(
        {
            "id": [0, 1, 2],
            "name": ["Root", "unnamed 1", "Micro"],
            "level": [-1, 0, 1],
            "parent": [None, 0, 1],
            "size": [2, 1, 1],
        }
    )
    genres.write_parquet(source / "genres.parquet")
    edges = pl.DataFrame(
        {"artist": [a, b, b, a], "genre": [0, 0, 1, 2], "score": [0.6, 0.2, 1.0, 1.0]}
    )
    edges.write_parquet(source / "memberships.parquet")
    return (
        {
            "export": str(source),
            "m1": str(m1),
            "registry": str(tmp_path / "registry.json"),
            "levels": ["broad", "fine"],
            "identity_jaccard": 0.8,
        },
        run,
        a,
        b,
    )


def test_adapter_contract_and_rerun(tmp_path, monkeypatch):
    monkeypatch.setattr("opennoise.catalog.tags.log", lambda *a, **kw: None)
    config, run, a, b = inputs(tmp_path)
    old = "00000000-0000-0000-0000-000000000003"
    (tmp_path / "m1/artist_redirects.json").write_text(json.dumps({old: a}))
    (tmp_path / "m1/artist_aliases.json").write_text(json.dumps({a: ["Old name"]}))
    artists_path = tmp_path / "m1/artists.parquet"
    pl.read_parquet(artists_path).with_columns(
        pl.lit("Comment").alias("disambiguation")
    ).write_parquet(artists_path)
    export(config, run)
    assert validate_release(run / "release")["layouts"] == {"axes": None, "islands": None}
    assert validate_release(run / "release")["artist_redirects"] == {old: a}
    search = json.loads((run / "release/search.json").read_text())
    artist = next(e for e in search if e["id"] == a)
    assert artist["aliases"] == ["Old name"]
    assert artist["disambiguation"] == "Comment"
    genres = {g["name"]: g for g in json.loads((run / "release/genres.json").read_text())}
    assert set(genres) == {"Root", "Micro"}
    assert genres["Micro"]["parent_id"] == genres["Root"]["id"]
    assert json.loads((run / "release/artists" / f"{b}.json").read_text())["similar"] is None
    snapshot = (run / "genre_ids.json").read_bytes()
    registry = (tmp_path / "registry.json").read_bytes()
    export(config, run)
    assert (run / "genre_ids.json").read_bytes() == snapshot
    assert (tmp_path / "registry.json").read_bytes() == registry
    summary = json.loads((run / "release-summary.json").read_text())
    assert set(summary) == {
        "genres",
        "artists",
        "memberships",
        "similarities",
        "files",
        "bytes",
        "grouping",
        "global_grouping",
        "readability",
        "placement",
        "seconds",
    }


def test_related_genres_cosine_targets_and_ties():
    artists = pl.DataFrame({"artist_mbid": ["a", "b", "c"], "item": [0, 1, 2]})
    catalog = {
        i: {"id": f"g-{i:02}", "name": "pop · Artist" if i == 0 else f"genre {i}"}
        for i in range(15)
    }
    memberships = pl.DataFrame(
        {
            "genre": list(catalog) + [14],
            "artist": ["a"] * 13 + ["c", "a", "b"],
            "score": [1.0] * 15 + [0.5],
        }
    )
    graph = related_genres(
        catalog, memberships, artists, np.array([[1.0, 0.0], [0.0, 1.0], [0.0, 0.0]])
    )
    assert graph[13] == []
    assert [n["id"] for n in graph[0]] == [f"g-{i:02}" for i in range(1, 11)]
    assert [n["id"] for n in graph[1]] == [f"g-{i:02}" for i in range(2, 12)]
    assert graph[14][0]["score"] == pytest.approx(1 / np.sqrt(1.25))
    for i, neighbors in graph.items():
        ids = [n["id"] for n in neighbors]
        assert len(ids) == len(set(ids)) <= 10
        assert catalog[i]["id"] not in ids
        assert "g-00" not in ids
        assert neighbors == sorted(neighbors, key=lambda n: (-n["score"], n["id"]))


def test_related_genres_empty_and_invalid_vectors():
    artists = pl.DataFrame({"artist_mbid": ["a"], "item": [0]})
    edges = pl.DataFrame({"genre": [0], "artist": ["a"], "score": [1.0]})
    catalog = {0: {"id": "g", "name": "pop · Artist"}}
    assert related_genres(catalog, edges, artists, np.ones((1, 2))) == {0: []}
    assert related_genres({}, edges.head(0), artists, np.ones((1, 2))) == {}
    with pytest.raises(ValueError, match="NaN"):
        related_genres(catalog, edges, artists, np.array([[float("nan"), 0.0]]))


def test_adapter_related_genres_and_rerun(tmp_path, monkeypatch):
    monkeypatch.setattr("opennoise.catalog.tags.log", lambda *a, **kw: None)
    config, run, _, _ = inputs(tmp_path)
    root = tmp_path / "layout"
    root.mkdir()
    config.update(layout=str(root), related_genres=True)
    (root / "layouts.json").write_text(json.dumps({"axes": None, "islands": None}))
    pl.DataFrame(
        schema={
            "kind": pl.String,
            "id": pl.String,
            "x": pl.Float64,
            "y": pl.Float64,
            "island_x": pl.Float64,
            "island_y": pl.Float64,
        }
    ).write_parquet(root / "positions.parquet")
    np.savez(root / "sonic_state.npz", vectors=np.array([[1.0, 0.0], [0.0, 1.0]]))
    export(config, run)
    assert validate_release(run / "release")["genre_similarity"] == "ALS+audio cosine top-10"
    genres = json.loads((run / "release/genres.json").read_text())
    for genre in genres:
        detail = json.loads((run / "release/genres" / f"{genre['id']}.json").read_text())
        assert detail["related"] == [
            {
                "id": next(g["id"] for g in genres if g != genre),
                "score": pytest.approx(0.6 / np.sqrt(0.4)),
            }
        ]
    snapshot = (tmp_path / "registry.json").read_bytes()
    export(config, run)
    assert (tmp_path / "registry.json").read_bytes() == snapshot
    np.savez(root / "sonic_state.npz", vectors=np.ones((2, 2)))
    export(config, run)


@pytest.mark.parametrize("empty", [False, True])
def test_configured_similarity_graph(tmp_path, monkeypatch, empty):
    monkeypatch.setattr("opennoise.catalog.tags.log", lambda *a, **kw: None)
    config, run, a, b = inputs(tmp_path)
    path = tmp_path / "similar.parquet"
    graph = pl.DataFrame({"item": [0, 1], "neighbor": [1, 0], "score": [1.1, 0.55]})
    (graph.head(0) if empty else graph).write_parquet(path)
    config["similarity"] = str(path)
    export(config, run)
    validate_release(run / "release")
    detail = json.loads((run / "release/artists" / f"{a}.json").read_text())
    if empty:
        assert detail["similar"] is None
    else:
        assert detail["similar"][0]["artist"]["id"] == b
        assert detail["similar"][0]["score"] == 1.0
        other = json.loads((run / "release/artists" / f"{b}.json").read_text())
        assert other["similar"][0]["score"] == 0.5


@pytest.mark.parametrize("score", [-0.1, float("nan"), float("inf")])
def test_invalid_configured_similarity_graph(tmp_path, score):
    config, run, _, _ = inputs(tmp_path)
    path = tmp_path / "similar.parquet"
    pl.DataFrame({"item": [0], "neighbor": [1], "score": [score]}).write_parquet(path)
    config["similarity"] = str(path)
    with pytest.raises(ValueError, match="Invalid M1 similarity graph"):
        export(config, run)


def test_global_adapter_contract_and_rerun(tmp_path, monkeypatch):
    monkeypatch.setattr("opennoise.catalog.tags.log", lambda *a, **kw: None)
    config, run, _, _ = inputs(tmp_path)
    config.update(group_globally=True, readable_names=True)
    export(config, run)
    validate_release(run / "release")
    genres = json.loads((run / "release/genres.json").read_text())
    root = next(g for g in genres if g["name"] == "Micro")
    child = next(g for g in genres if g["name"] == "Micro · A")
    assert root["parent_id"] is None
    assert child["parent_id"] == root["id"]
    mapping = (run / "genre_ids.json").read_bytes()
    registry = (tmp_path / "registry.json").read_bytes()
    export(config, run)
    assert (run / "genre_ids.json").read_bytes() == mapping
    assert (tmp_path / "registry.json").read_bytes() == registry


def test_global_adapter_exports_folded_aliases(tmp_path, monkeypatch):
    monkeypatch.setattr("opennoise.catalog.tags.log", lambda *a, **kw: None)
    config, run, _, _ = inputs(tmp_path)
    source = tmp_path / "source/genres.parquet"
    pl.read_parquet(source).with_columns(
        pl.when(pl.col("id") == 2).then(pl.lit("R")).otherwise(pl.col("name")).alias("name"),
        pl.when(pl.col("id") == 2).then(None).otherwise(pl.col("parent")).alias("parent"),
    ).write_parquet(source)
    vocabulary = tmp_path / "vocabulary.parquet"
    pl.DataFrame(
        {
            "qid": ["Q1", "Q1"],
            "name": ["Root", "R"],
            "normalized": ["root", "r"],
            "kind": ["label", "alias"],
        }
    ).write_parquet(vocabulary)
    config.update(group_globally=True, vocabulary=str(vocabulary))
    export(config, run)
    genres = {g["name"]: g for g in json.loads((run / "release/genres.json").read_text())}
    assert genres["Root"]["aliases"] == ["R"]
    assert genres["R"]["parent_id"] == genres["Root"]["id"]
    search = json.loads((run / "release/search.json").read_text())
    assert next(g for g in search if g["id"] == genres["Root"]["id"])["aliases"] == ["R"]


def test_hierarchy_empty_and_cycles():
    assert hierarchy([], set()) == {}
    with pytest.raises(ValueError, match="Cyclic"):
        hierarchy([{"id": 0, "parent": 1}, {"id": 1, "parent": 0}], {0, 1})


def test_aliases_keep_existing_group_ids_and_readable_names(tmp_path, monkeypatch):
    monkeypatch.setattr("opennoise.catalog.tags.log", lambda *a, **kw: None)
    config, run, _, _ = inputs(tmp_path)
    path = tmp_path / "source/genres.parquet"
    pl.read_parquet(path).with_columns(
        pl.when(pl.col("id") == 2).then(pl.lit("R")).otherwise(pl.col("name")).alias("name")
    ).write_parquet(path)
    config.update(group_globally=True, readable_names=True)
    export(config, run)
    before = json.loads((run / "release/genres.json").read_text())
    vocabulary = tmp_path / "vocabulary.parquet"
    pl.DataFrame(
        {
            "qid": ["Q1", "Q1"],
            "name": ["Root", "R"],
            "normalized": ["root", "r"],
            "kind": ["label", "alias"],
        }
    ).write_parquet(vocabulary)
    config["vocabulary"] = str(vocabulary)
    aliased = tmp_path / "aliased"
    aliased.mkdir()
    export(config, aliased)
    after = json.loads((aliased / "release/genres.json").read_text())
    assert {g["id"]: g["name"] for g in before} == {g["id"]: g["name"] for g in after}
    validate_release(aliased / "release")


def test_grouped_adapter_rerun(tmp_path, monkeypatch):
    monkeypatch.setattr("opennoise.catalog.tags.log", lambda *a, **kw: None)
    config, run, _, _ = inputs(tmp_path)
    path = tmp_path / "source/genres.parquet"
    pl.read_parquet(path).with_columns(
        pl.when(pl.col("id") == 0).then(pl.lit("Root")).otherwise(pl.lit("Micro")).alias("name"),
        pl.when(pl.col("id") == 0).then(-1).otherwise(0).alias("level"),
        pl.lit(None, dtype=pl.Int64).alias("parent"),
    ).write_parquet(path)
    config["group_siblings"] = True
    export(config, run)
    validate_release(run / "release")
    mapping = (run / "genre_ids.json").read_bytes()
    registry = (tmp_path / "registry.json").read_bytes()
    export(config, run)
    assert (run / "genre_ids.json").read_bytes() == mapping
    assert (tmp_path / "registry.json").read_bytes() == registry


def test_adapter_coordinates_and_missing_points(tmp_path, monkeypatch):
    monkeypatch.setattr("opennoise.catalog.tags.log", lambda *a, **kw: None)
    config, run, a, _ = inputs(tmp_path)
    config["layout"] = str(tmp_path / "layout")
    root = tmp_path / "layout"
    root.mkdir()
    layouts = {
        "axes": {"x_min": "Left", "x_max": "Right", "y_min": "Top", "y_max": "Bottom"},
        "islands": None,
    }
    (root / "layouts.json").write_text(json.dumps(layouts))
    pl.DataFrame(
        {
            "kind": ["artist"],
            "id": [a],
            "x": [0.0],
            "y": [1.0],
            "island_x": [None],
            "island_y": [None],
        }
    ).write_parquet(root / "positions.parquet")
    export(config, run)
    assert validate_release(run / "release")["layouts"] == layouts
    detail = json.loads((run / "release/artists" / f"{a}.json").read_text())
    assert detail["artist"]["positions"] == {"axes": {"x": 0.0, "y": 1.0}, "islands": None}
    assert json.loads((run / "release/genres.json").read_text())[0]["positions"]["axes"] is None


@pytest.mark.parametrize("x,y", [(float("nan"), 0), (1.1, 0), (None, 0)])
def test_coordinates_reject_bad_points(tmp_path, x, y):
    pl.DataFrame(
        {"kind": ["genre"], "id": ["g"], "x": [x], "y": [y], "island_x": [None], "island_y": [None]}
    ).write_parquet(tmp_path / "positions.parquet")
    with pytest.raises(ValueError, match="Invalid layout"):
        coordinates({"layout": str(tmp_path)})
