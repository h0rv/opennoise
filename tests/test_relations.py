import json

import numpy as np
import polars as pl
import pytest
from scipy import sparse

from opennoise import reference
from opennoise.genres import graph_matrix
from opennoise.relations import blend_relations, ingest_relations


def test_blend_symmetric_binary_edges_and_filter(tmp_path):
    path = tmp_path / "relations.parquet"
    pl.DataFrame(
        {
            "item": [0, 0, 1, 1, 2],
            "neighbor": [1, 1, 0, 2, 2],
            "type": ["member", "member", "member", "teacher", "member"],
        }
    ).write_parquet(path)
    graph = sparse.csr_matrix(np.array([[0, 0.2, 0], [0.2, 0, 0], [0, 0, 0]]))
    result = blend_relations(graph, {"path": path, "weight": 0.3, "types": ["member"]})
    np.testing.assert_allclose(result.toarray(), [[0, 0.5, 0], [0.5, 0, 0], [0, 0, 0]])
    assert graph[0, 1] == 0.2


@pytest.mark.parametrize("types", [None, []])
def test_empty_relations(tmp_path, types):
    path = tmp_path / "empty.parquet"
    pl.DataFrame(schema={"item": pl.Int64, "neighbor": pl.Int64, "type": pl.String}).write_parquet(
        path
    )
    config = {"path": path, "weight": 1}
    if types is not None:
        config["types"] = types
    graph = sparse.eye(3, format="csr")
    np.testing.assert_array_equal(blend_relations(graph, config).toarray(), graph.toarray())


def test_disabled_does_not_read_cache():
    graph = sparse.eye(3, format="csr")
    assert blend_relations(graph, {"weight": 0, "path": "missing.parquet"}) is graph
    assert blend_relations(graph, {}) is graph


@pytest.mark.parametrize("weight", [-1, float("inf"), float("nan")])
def test_invalid_weight(weight):
    with pytest.raises(ValueError, match="finite and nonnegative"):
        blend_relations(sparse.eye(3, format="csr"), {"weight": weight})


def test_invalid_item(tmp_path):
    path = tmp_path / "invalid.parquet"
    pl.DataFrame({"item": [0], "neighbor": [3], "type": ["member"]}).write_parquet(path)
    with pytest.raises(ValueError, match="outside M1"):
        blend_relations(sparse.eye(3, format="csr"), {"path": path, "weight": 1})


def test_graph_matrix_normalizes_after_blending(tmp_path):
    pl.DataFrame({"item": [0, 1, 2]}).write_parquet(tmp_path / "artists.parquet")
    pl.DataFrame({"neighbor": np.repeat([1, 0, 0], 50), "score": np.ones(150)}).write_parquet(
        tmp_path / "tfidf.parquet"
    )
    path = tmp_path / "relations.parquet"
    pl.DataFrame({"item": [1], "neighbor": [2], "type": ["member"]}).write_parquet(path)
    config = {"m1": tmp_path, "relations": {"path": path, "weight": 0.3}}
    graph, transition = graph_matrix(config, {"k": 1})
    assert graph[1, 2] == graph[2, 1] == 0.3
    np.testing.assert_allclose(np.asarray(transition.sum(axis=1)).ravel(), 1)
    baseline, _ = graph_matrix({"m1": tmp_path}, {"k": 1})
    disabled, _ = graph_matrix({"m1": tmp_path, "relations": {"weight": 0}}, {"k": 1})
    np.testing.assert_array_equal(baseline.toarray(), disabled.toarray())


@pytest.mark.parametrize("mbids, expected", [(["a", "b"], 1), (["z"], 0)])
def test_ingest_maps_both_endpoints_and_counts(tmp_path, monkeypatch, mbids, expected):
    tables = {
        "artist": pl.DataFrame({"mb_artist": ["1", "2", "3"], "artist_mbid": ["a", "b", "c"]}),
        "link_type": pl.DataFrame(
            {
                "type_id": ["10"],
                "type_mbid": ["type-a"],
                "entity0": ["artist"],
                "entity1": ["artist"],
                "type": ["member"],
            }
        ),
        "link": pl.DataFrame({"link": ["4"], "type_id": ["10"]}),
        "l_artist_artist": pl.DataFrame(
            {
                "link": ["4"] * 5,
                "artist0": ["1", "1", "1", "2", "1"],
                "artist1": ["2", "2", "3", "2", "9"],
            }
        ),
    }
    monkeypatch.setattr(reference, "table", lambda name, columns, names: tables[name])
    pl.DataFrame({"artist_mbid": mbids, "item": list(range(len(mbids)))}).write_parquet(
        tmp_path / "artists.parquet"
    )
    target = tmp_path / "relations.parquet"
    config = {"m1": str(tmp_path), "relations": {"path": str(target)}}
    ingest_relations(config, reference.table)
    assert pl.read_parquet(target).select("item", "neighbor").rows() == (
        [(0, 1)] if expected else []
    )
    summary = json.loads(target.with_suffix(".json").read_text())
    assert summary["coverage"] == expected
    assert summary["types"][0]["dump_rows"] == 5
    assert summary["types"][0]["mapped_pairs"] == expected
    monkeypatch.setattr(reference, "table", lambda *args: pytest.fail("cache was reread"))
    ingest_relations(config, reference.table)


def test_relation_extraction_uses_separate_marker(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "sources.toml").write_text('sources = [{}, {}, {}, {url = "core-dump"}]')
    root = tmp_path / "data/m2"
    root.mkdir(parents=True)
    (root / "coverage.json").write_text("{}")
    (root / "artist.done").touch()
    calls = []
    monkeypatch.setattr(
        reference.subprocess, "run", lambda command, **kwargs: calls.append(command)
    )
    monkeypatch.setattr(reference, "ingest_relations", lambda config, read_table: None)
    config = {"relations": {"path": "relations.parquet"}}
    reference.ingest_reference(config)
    assert len(calls) == 1
    command = calls[0][-1]
    assert "mbdump/l_artist_artist mbdump/link mbdump/link_type" in command
    assert "mbdump/artist " not in command
    assert (root / "relations.done").exists()
    reference.ingest_reference(config)
    reference.ingest_reference({})
    assert len(calls) == 1


def test_failed_relation_extraction_does_not_mark_complete(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "sources.toml").write_text('sources = [{}, {}, {}, {url = "core-dump"}]')

    def fail(*args, **kwargs):
        raise RuntimeError("download failed")

    monkeypatch.setattr(reference.subprocess, "run", fail)
    with pytest.raises(RuntimeError, match="download failed"):
        reference.ingest_reference({"relations": {}})
    assert not (tmp_path / "data/m2/artist.done").exists()
    assert not (tmp_path / "data/m2/relations.done").exists()


def test_existing_reference_without_relations_needs_no_raw_dump(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    root = tmp_path / "data/m2"
    root.mkdir(parents=True)
    (root / "coverage.json").write_text("{}")
    reference.ingest_reference({})
