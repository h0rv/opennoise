import polars as pl
import pytest
from scipy import sparse

from opennoise import wikidata
from opennoise.metrics import sealed


def test_sealed():
    assert sealed("a1")
    assert not sealed("a0")


@pytest.mark.parametrize("mbids", [["a1", "a0"], ["a1"], []])
def test_evidence_excludes_sealed_cached_artists(tmp_path, monkeypatch, mbids):
    links = pl.DataFrame(
        {"artist_mbid": mbids, "qid": ["Q1"] * len(mbids)},
        schema={"artist_mbid": pl.String, "qid": pl.String},
    )
    links.write_parquet(tmp_path / "artist_genres.parquet")
    pl.DataFrame(
        {"qid": ["Q1"], "name": ["rock"], "normalized": ["rock"], "kind": ["label"]}
    ).write_parquet(tmp_path / "vocabulary.parquet")
    artists = pl.DataFrame({"artist_mbid": ["a1", "a0"], "item": [0, 1]})
    monkeypatch.setattr(
        wikidata.naming, "discogs_matrix", lambda *args: (sparse.csr_matrix((2, 1)), ["rock"])
    )
    matrix, *_ = wikidata.evidence({"cache": str(tmp_path)}, artists)
    assert matrix[0].getnnz() == 0
    assert matrix[1].getnnz() == int("a0" in mbids)
    assert pl.read_parquet(tmp_path / "artist_genres.parquet").height == len(mbids)
    links.drop("artist_mbid").write_parquet(tmp_path / "artist_genres.parquet")
    with pytest.raises(pl.exceptions.ColumnNotFoundError):
        wikidata.evidence({"cache": str(tmp_path)}, artists)


@pytest.mark.parametrize("mbids", [["a0", "a1"], ["a1"], []])
def test_ingest_excludes_sealed_artists(tmp_path, monkeypatch, mbids):
    data = {
        "artist_genres": [{"mbid": {"value": mbid}, "genre": {"value": "wd/Q1"}} for mbid in mbids],
        "vocabulary": [{"genre": {"value": "wd/Q1"}, "label": {"value": "rock"}}],
    }
    for name in data:
        (tmp_path / f"{name}.json").write_text("{}")
    monkeypatch.setattr(wikidata, "fetch", lambda config, name: data[name])
    monkeypatch.setattr(wikidata, "split_labels", lambda config: ({}, {}, {"rock": []}, {}))
    monkeypatch.setattr(wikidata.naming, "settings", lambda config: {})
    monkeypatch.setattr(wikidata.tags, "log", lambda *args, **kwargs: None)
    pl.DataFrame({"artist_mbid": ["a0", "a1"], "item": [0, 1]}).write_parquet(
        tmp_path / "artists.parquet"
    )
    wikidata.ingest({"cache": str(tmp_path), "m1": str(tmp_path)}, tmp_path)
    assert pl.read_parquet(tmp_path / "artist_genres.parquet")["artist_mbid"].to_list() == (
        ["a0"] if "a0" in mbids else []
    )
