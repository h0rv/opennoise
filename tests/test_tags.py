import gzip
import io
import json
import tarfile

import numpy as np
import polars as pl
import pytest

from opennoise import tags as pipeline
from opennoise.tags import agreement, discogs, discogs_id, musicbrainz, tag_name, vectors


def test_discogs_identity():
    assert discogs_id("http://www.discogs.com/artist/123-Foo") == 123
    assert discogs_id("https://discogs.com/de/artist/123?anv=bar") == 123
    for url in [
        "https://discogs.com/release/123",
        "https://discogs.com.evil.org/artist/123",
        "https://discogs.com/artist/123x",
    ]:
        assert discogs_id(url) is None
    assert tag_name("  ＡMBIENT\tHouse ") == "ambient house"


def test_tags_follow_exact_identity_and_main_release_credits(tmp_path):
    artists = pl.DataFrame({"artist_mbid": ["a", "b"], "item": [1, 0]})
    records = [
        {
            "id": "a",
            "tags": [{"name": "Ambient", "count": 2}, {"name": "bad", "count": -1}],
            "relations": [{"url": {"resource": "https://discogs.com/artist/123"}}],
        },
        {
            "id": "b",
            "tags": [],
            "relations": [{"url": {"resource": "https://discogs.com/artist/456"}}],
        },
        {"id": "absent", "tags": [{"name": "wrong", "count": 2}]},
    ]
    payload = "\n".join(json.dumps(row) for row in records).encode()
    path = tmp_path / "artist.tar.xz"
    with tarfile.open(path, "w:xz") as archive:
        member = tarfile.TarInfo("mbdump/artist")
        member.size = len(payload)
        archive.addfile(member, io.BytesIO(payload))
    musicbrainz(path, tmp_path)
    mb_tags = pl.read_parquet(tmp_path / "musicbrainz.parquet")
    matrix, vocabulary = vectors(mb_tags, artists)
    assert vocabulary["tag"].to_list() == ["ambient"]
    assert matrix.getnnz(axis=1).tolist() == [0, 1]
    releases = b"""<releases><release><artists><artist><id>123</id></artist>
    <artist><id>123</id></artist></artists><extraartists><artist><id>456</id></artist>
    </extraartists><styles><style>Deep House</style></styles></release>
    <release><artists><artist><id>123</id></artist></artists>
    <styles><style>Deep House</style><style>Ambient</style></styles></release></releases>"""
    release_path = tmp_path / "releases.xml.gz"
    release_path.write_bytes(gzip.compress(releases))
    assert discogs(release_path, tmp_path) == 2
    tags = pl.read_parquet(tmp_path / "discogs.parquet").sort("tag")
    assert tags["artist_mbid"].to_list() == ["a", "a"]
    assert tags["weight"].to_list() == [1, 2]
    matrix, _ = vectors(tags, artists)
    assert matrix.getnnz(axis=1).tolist() == [0, 2]
    np.testing.assert_allclose(agreement(matrix, np.array([0, 1]), np.array([1, 1])), [0, 1])


def test_discogs_only_cache(tmp_path, monkeypatch):
    cache = tmp_path / "cache"
    cache.mkdir()
    run = tmp_path / "run"
    run.mkdir()
    for name in ["identity.parquet", "discogs.parquet"]:
        (cache / name).touch()
    monkeypatch.setattr(pipeline, "normalized_cache", lambda config: cache)

    def download(*args):
        raise AssertionError("Cached inputs must not be downloaded")

    monkeypatch.setattr(pipeline, "download", download)
    pipeline.ingest({"tags": {"cache": str(tmp_path), "sources": ["discogs"]}}, run)
    assert sorted(path.name for path in run.iterdir()) == ["discogs.parquet", "identity.parquet"]


@pytest.mark.parametrize("empty", [False, True])
def test_discogs_only_build_and_evaluate(tmp_path, monkeypatch, empty):
    base = tmp_path / "base"
    base.mkdir()
    run = tmp_path / "run"
    run.mkdir()
    pl.DataFrame(
        {"artist_mbid": ["a", "b"], "artist_name": ["A", "B"], "item": [0, 1]}
    ).write_parquet(base / "artists.parquet")
    pl.DataFrame({"item": [0, 1], "neighbor": [1, 0], "score": [0.2, 0.2]}).write_parquet(
        base / "tfidf.parquet"
    )
    (base / "labs.json").write_text("[]")
    tags = pl.DataFrame({"artist_mbid": ["a", "b"], "tag": ["rock", "rock"], "weight": [1.0, 1.0]})
    (tags.head(0) if empty else tags).write_parquet(run / "discogs.parquet")
    config = {
        "seed": 42,
        "tags": {
            "base_run": str(base),
            "sources": ["discogs"],
            "weights": [0.1],
            "validation_fraction": 0.5,
        },
    }
    pipeline.build(config, run)
    coverage = json.loads((run / "coverage.json").read_text())
    assert set(coverage) == {"discogs"}
    coverage["musicbrainz"] = {}
    (run / "coverage.json").write_text(json.dumps(coverage))
    monkeypatch.setattr(pipeline, "heldout_sets", lambda *args: ["one", "two"])
    monkeypatch.setattr(
        pipeline,
        "colistening",
        lambda graph, users: {"ndcg@50": 1 - float(graph.sum()), "recall@50": 1.0},
    )
    monkeypatch.setattr(pipeline, "log", lambda *args, **kwargs: None)
    pipeline.evaluate(config, run)
    results = json.loads((run / "metrics.json").read_text())
    assert set(results) == {"tfidf", "tags_discogs_0.1"}
    assert json.loads((run / "best.json").read_text())["method"] == "tags_discogs_0.1"
    graph = pl.read_parquet(run / "similar.parquet")
    assert graph.select("item", "neighbor").rows() == [(0, 1), (1, 0)]
    np.testing.assert_allclose(graph["score"], [0.2, 0.2] if empty else [0.22, 0.22])
    (run / "discogs.parquet").unlink()
    with pytest.raises(FileNotFoundError):
        pipeline.build(config, run)
