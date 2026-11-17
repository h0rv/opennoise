import json

import polars as pl

from opennoise import wikidata


def test_music_genre_filter(tmp_path, monkeypatch):
    def rows(name):
        if name == "music_genres":
            return [{"genre": {"value": "http://www.wikidata.org/entity/Q1"}}]
        if name == "artist_genres":
            return [
                {"mbid": {"value": "a"}, "genre": {"value": f"http://www.wikidata.org/entity/Q{i}"}}
                for i in [1, 2]
            ]
        return [
            {"genre": {"value": f"http://www.wikidata.org/entity/Q{i}"}, "label": {"value": label}}
            for i, label in [(1, "shoegaze"), (2, "Shakespearean comedy")]
        ]

    for name in wikidata.QUERIES:
        (tmp_path / f"{name}.json").write_text("{}")
    pl.DataFrame({"artist_mbid": ["a"], "item": [0]}).write_parquet(tmp_path / "artists.parquet")
    monkeypatch.setattr(wikidata, "fetch", lambda config, name: rows(name))
    monkeypatch.setattr(wikidata.naming, "settings", lambda config: {})
    monkeypatch.setattr(wikidata, "split_labels", lambda config: (None, None, ["shoegaze"], None))
    monkeypatch.setattr(wikidata.tags, "log", lambda *a, **kw: None)
    wikidata.ingest({"cache": str(tmp_path), "m1": str(tmp_path)}, tmp_path)
    assert pl.read_parquet(tmp_path / "vocabulary.parquet")["name"].to_list() == ["shoegaze"]
    assert pl.read_parquet(tmp_path / "artist_genres.parquet").height == 1
    report = json.loads((tmp_path / "coverage.json").read_text())
    assert report["p136_pairs_dropped"] == report["vocabulary_items_dropped"] == 1
