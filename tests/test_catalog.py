import json

import polars as pl
import pytest

from opennoise.catalog import coordinates, export, hierarchy
from opennoise.contract import validate_release


def inputs(tmp_path):
    a, b = "00000000-0000-0000-0000-000000000001", "00000000-0000-0000-0000-000000000002"
    source, model, m1, run = [tmp_path / p for p in ["source", "model", "m1", "run"]]
    for path in [source, model, m1, run]:
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
    genres.filter(pl.col("level") == -1).write_parquet(model / "genres.parquet")
    edges = pl.DataFrame(
        {"artist": [a, b, b, a], "genre": [0, 0, 1, 2], "score": [0.6, 0.2, 1.0, 1.0]}
    )
    edges.write_parquet(source / "memberships.parquet")
    edges.filter(pl.col("genre") == 0).write_parquet(model / "memberships.parquet")
    labels = tmp_path / "labels.parquet"
    pl.DataFrame({"genre": ["Root"], "item": [0]}).write_parquet(labels)
    return (
        {
            "export": str(source),
            "refit": str(model),
            "m1": str(m1),
            "labels": str(labels),
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
    export(config, run)
    assert validate_release(run / "release")["layouts"] == {"axes": None, "islands": None}
    genres = {g["name"]: g for g in json.loads((run / "release/genres.json").read_text())}
    assert set(genres) == {"Root", "Micro"}
    assert genres["Micro"]["parent_id"] == genres["Root"]["id"]
    assert json.loads((run / "release/artists" / f"{b}.json").read_text())["similar"] is None
    snapshot = (run / "genre_ids.json").read_bytes()
    registry = (tmp_path / "registry.json").read_bytes()
    export(config, run)
    assert (run / "genre_ids.json").read_bytes() == snapshot
    assert (tmp_path / "registry.json").read_bytes() == registry


def test_adapter_rejects_training_strength_injection(tmp_path):
    config, run, _, _ = inputs(tmp_path)
    path = tmp_path / "source/memberships.parquet"
    pl.read_parquet(path).with_columns(
        pl.when(pl.col("genre") == 0).then(1.0).otherwise(pl.col("score")).alias("score")
    ).write_parquet(path)
    with pytest.raises(ValueError, match="cached model predictions"):
        export(config, run)
    assert not (run / "release").exists()


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
    summary = json.loads((run / "release-summary.json").read_text())
    assert str(vocabulary) in summary["inputs"]


def test_hierarchy_empty_and_cycles():
    assert hierarchy([], set()) == {}
    with pytest.raises(ValueError, match="Cyclic"):
        hierarchy([{"id": 0, "parent": 1}, {"id": 1, "parent": 0}], {0, 1})


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
