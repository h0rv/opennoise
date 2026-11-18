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
    assert pl.read_parquet(tmp_path / "labels.parquet").is_empty()
    credits = pl.read_parquet(tmp_path / "credits.parquet").sort("artist_mbid")
    assert credits["artist_mbid"].to_list() == ["a", "b"]
    assert credits["tag"].to_list() == ["artist:456", "artist:123"]
    assert credits["weight"].to_list() == [1, 1]
    matrix, _ = vectors(tags, artists)
    assert matrix.getnnz(axis=1).tolist() == [0, 2]
    np.testing.assert_allclose(agreement(matrix, np.array([0, 1]), np.array([1, 1])), [0, 1])


def test_discogs_labels_and_credits(tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline, "DISCOGS_CHUNK_SIZE", 1)
    pl.DataFrame({"artist_mbid": ["a"], "discogs_id": [123]}).write_parquet(
        tmp_path / "identity.parquet"
    )
    release = b"""<release><artists><artist><id>123</id></artist>
    <artist><id>456</id></artist><artist><id>194</id></artist></artists>
    <labels><label id="7"/><label id="7"/><label id="0"/><label id="bad"/></labels>
    <extraartists><artist><id>789</id></artist></extraartists><tracklist><track>
    <extraartists><artist><id>789</id></artist><artist><id>999</id></artist>
    </extraartists></track></tracklist></release>"""
    path = tmp_path / "releases.xml.gz"
    path.write_bytes(gzip.compress(b"<releases>" + release * 2 + b"</releases>"))
    assert discogs(path, tmp_path) == 2
    labels = pl.read_parquet(tmp_path / "labels.parquet")
    assert labels.rows() == [("a", "label:7", 2, "labels")]
    credits = pl.read_parquet(tmp_path / "credits.parquet").sort("tag")
    assert credits["tag"].to_list() == ["artist:456", "artist:789", "artist:999"]
    assert credits["weight"].to_list() == [2, 2, 2]
    assert pl.read_parquet(tmp_path / "discogs.parquet").is_empty()


@pytest.mark.parametrize("missing", [None, "labels.parquet", "credits.parquet"])
def test_ingest_requires_all_discogs_outputs(tmp_path, monkeypatch, missing):
    normalized = tmp_path / "normalized"
    normalized.mkdir()
    run = tmp_path / "run"
    run.mkdir()
    outputs = [
        "musicbrainz.parquet",
        "identity.parquet",
        "discogs.parquet",
        "labels.parquet",
        "credits.parquet",
    ]
    for name in outputs:
        if name != missing:
            (normalized / name).touch()
    calls = []

    def collect(path, root):
        calls.append(path.name)
        for name in outputs[2:]:
            (root / name).touch()
        return 0

    monkeypatch.setattr(pipeline, "normalized_cache", lambda config: normalized)
    monkeypatch.setattr(pipeline, "download", lambda *args: None)
    monkeypatch.setattr(pipeline, "discogs", collect)
    monkeypatch.setattr(pipeline, "log", lambda *args, **kwargs: None)
    pipeline.ingest({"tags": {"cache": str(tmp_path)}}, run)
    assert calls == ([] if missing is None else ["discogs_releases.xml.gz"])
    assert sorted(path.name for path in run.iterdir()) == sorted(outputs)


def test_discogs_invalid_dump(tmp_path):
    pl.DataFrame({"artist_mbid": ["a"], "discogs_id": [123]}).write_parquet(
        tmp_path / "identity.parquet"
    )
    path = tmp_path / "releases.xml.gz"
    path.write_bytes(b"not gzip")
    with pytest.raises(gzip.BadGzipFile):
        discogs(path, tmp_path)
    assert not (tmp_path / "labels.parquet").exists()
    assert not (tmp_path / "credits.parquet").exists()


@pytest.mark.parametrize("weights", [[], [0.1, 0.5]])
def test_evaluate_exports_each_validation_selected_source(tmp_path, monkeypatch, weights):
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
    (run / "coverage.json").write_text(json.dumps({"labels": {}, "credits": {}}))
    for source in ["labels", "credits"]:
        np.save(run / f"{source}_agreement.npy", np.ones(2))
        np.save(run / f"{source}_covered.npy", np.ones(2, dtype=bool))
    monkeypatch.setattr(pipeline, "heldout_sets", lambda *args: ["one", "two"])
    monkeypatch.setattr(
        pipeline,
        "colistening",
        lambda matrix, users: {"ndcg@50": float(matrix.sum()), "recall@50": 1.0},
    )
    monkeypatch.setattr(pipeline, "log", lambda *args, **kwargs: None)
    config = {
        "seed": 42,
        "tags": {"base_run": str(base), "validation_fraction": 0.5, "weights": weights},
    }
    pipeline.evaluate(config, run)
    results = json.loads((run / "metrics.json").read_text())
    expected = ["tfidf"] + (
        [f"tags_{source}_0.5" for source in ["labels", "credits", "combined"]] if weights else []
    )
    assert [name for name, metrics in results.items() if "test" in metrics] == expected
    for name in expected:
        assert pl.read_parquet(run / f"{name}.parquet")["neighbor"].to_list() == [1, 0]
    assert (run / "similar.parquet").exists()
    config["tags"]["validation_fraction"] = 0
    with pytest.raises(ValueError, match="Validation and test"):
        pipeline.evaluate(config, run)


def test_genre_agreement_counts_unlabeled_neighbors():
    labels = pl.DataFrame({"item": [0, 1], "genre": ["rock", "rock"]})
    edges = pl.DataFrame(
        {"item": [0, 0, 0, 1, 2], "neighbor": [0, 1, 2, 2, 0], "score": [1.0, 0.9, 0.8, 1.0, 1.0]}
    )
    metrics = pipeline.genre_agreement(edges, labels, 3)
    assert metrics["agreement@10"] == 0.25
    assert metrics["artists"] == 2
    assert metrics["pairs"] == 3
    assert metrics == pipeline.genre_agreement(edges, labels, 3)
    assert pipeline.genre_agreement(edges, labels.head(0), 3)["agreement@10"] is None
    assert pipeline.genre_agreement(edges.head(0), labels, 3)["artists"] == 0
    with pytest.raises(ValueError, match="Positive k"):
        pipeline.genre_agreement(edges, labels, 3, k=0)
