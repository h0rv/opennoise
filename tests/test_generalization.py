import json
import urllib.error
import urllib.parse
import urllib.request
from email.message import Message
from io import StringIO

import polars as pl
import pytest

from opennoise import generalization as gen


def test_query_cache_and_error(tmp_path, monkeypatch):
    calls = []

    def request(req, timeout):
        assert req.get_method() == "POST"
        assert b"query=" in req.data
        assert req.get_header("User-agent") == "opennoise/0.1 (https://github.com/h0rv/opennoise)"
        calls.append(req)
        return StringIO(json.dumps({"results": {"bindings": [{"qid": {"value": "wd/Q1"}}]}}))

    monkeypatch.setattr(urllib.request, "urlopen", request)
    assert gen.query("https://endpoint", "music", tmp_path) == [{"qid": "wd/Q1"}]
    assert gen.query("https://endpoint", "music", tmp_path) == [{"qid": "wd/Q1"}]
    assert len(calls) == 1
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **kw: StringIO('{"exception":"bad"}'))
    with pytest.raises(ValueError, match="bad"):
        gen.query("https://endpoint", "linked", tmp_path)


@pytest.mark.parametrize("bindings", [[], [{"qid": {"value": "wd/Q1"}}]])
def test_query_rate_limit_fallback(tmp_path, monkeypatch, bindings):
    calls = []

    def request(req, timeout):
        calls.append(req)
        assert req.get_header("User-agent") == "opennoise/0.1 (https://github.com/h0rv/opennoise)"
        if len(calls) == 1:
            raise urllib.error.HTTPError(req.full_url, 429, "limited", Message(), None)
        assert req.get_method() == "GET"
        assert req.full_url.startswith("https://query.wikidata.org/sparql?")
        assert urllib.parse.parse_qs(urllib.parse.urlparse(req.full_url).query)["query"] == [
            gen.PREFIX + gen.QUERIES["linked"]
        ]
        return StringIO(json.dumps({"results": {"bindings": bindings}}))

    monkeypatch.setattr(urllib.request, "urlopen", request)
    expected = [{key: value["value"] for key, value in row.items()} for row in bindings]
    assert gen.query("https://qlever.dev/api/wikidata", "linked", tmp_path) == expected
    assert gen.query("https://qlever.dev/api/wikidata", "linked", tmp_path) == expected
    assert len(calls) == 2


@pytest.mark.parametrize(
    "endpoint,code", [("https://qlever.dev/api/wikidata", 500), ("https://other", 429)]
)
def test_query_does_not_fallback_on_other_errors(tmp_path, monkeypatch, endpoint, code):
    calls = []

    def request(req, timeout):
        calls.append(req)
        raise urllib.error.HTTPError(req.full_url, code, "failed", Message(), None)

    monkeypatch.setattr(urllib.request, "urlopen", request)
    with pytest.raises(urllib.error.HTTPError):
        gen.query(endpoint, "linked", tmp_path)
    assert len(calls) == 1
    assert not list(tmp_path.iterdir())


def test_query_fallback_failure_not_cached(tmp_path, monkeypatch):
    calls = []

    def request(req, timeout):
        calls.append(req)
        raise urllib.error.HTTPError(
            req.full_url, 429 if len(calls) == 1 else 403, "failed", Message(), None
        )

    monkeypatch.setattr(urllib.request, "urlopen", request)
    with pytest.raises(urllib.error.HTTPError, match="403"):
        gen.query("https://qlever.dev/api/wikidata", "linked", tmp_path)
    assert len(calls) == 2
    assert not list(tmp_path.iterdir())


@pytest.fixture
def reference():
    return pl.DataFrame(
        {
            "artist_mbid": [f"a{i}" for i in range(12)],
            "genre_qid": ["Q1"] * 6 + ["Q2"] * 6,
            "genre": ["rock"] * 6 + ["jazz"] * 6,
            "enao_linked": [True] * 6 + [False] * 6,
        }
    )


@pytest.fixture
def clusters():
    memberships = pl.DataFrame(
        {
            "artist": [f"a{i}" for i in range(12)],
            "genre": [0] * 6 + [1] * 6,
            "score": [1.0] * 12,
        }
    )
    genres = pl.DataFrame({"id": [0, 1], "name": ["rock", "jazz"], "level": [0, 0]})
    return memberships, genres


def test_clean_reference():
    statements = [
        {"statement": "s1", "mbid": "a", "qid": "http://wd/Q1", "genre": "rock"},
        {"statement": "s2", "mbid": "b", "qid": "http://wd/Q2", "genre": "jazz"},
        {"statement": "s3", "mbid": "c", "qid": "http://wd/Q3", "genre": "fiction"},
        {"statement": "s4", "mbid": "d", "qid": "http://wd/Q1", "genre": "rock"},
        {"statement": "s5", "mbid": "e", "qid": "http://wd/Q1"},
    ]
    clean = gen.clean_reference(
        statements,
        [{"statement": "s1"}],
        [{"statement": "s2"}],
        [{"qid": "http://wd/Q1"}],
        {"http://wd/Q1", "http://wd/Q2"},
    )
    assert clean.rows() == [("d", "Q1", "rock", True)]
    assert gen.clean_reference([], [], [], [], set()).schema == gen.SCHEMA


def test_fallback_requires_five_distinct_artists():
    statements = [
        {"statement": str(i), "mbid": str(i), "qid": "wd/Q1", "genre": "rock"} for i in range(5)
    ]
    assert len(gen.clean_reference(statements, [], [], [])) == 5
    assert gen.clean_reference(statements[:4] * 2, [], [], []).is_empty()


def test_similarity(reference):
    artists = pl.DataFrame({"item": range(12), "artist_mbid": [f"a{i}" for i in range(12)]})
    edges = pl.DataFrame(
        {"item": range(12), "neighbor": [1, 2, 3, 4, 5, 0, 7, 8, 9, 10, 11, 6], "score": [1.0] * 12}
    )
    score = gen.similarity_score(reference, artists, edges)
    assert score["agreement@10"] == 1
    assert 0 <= score["random"] < 1
    assert score["artists"] == score["pairs"] == 12
    assert score == gen.similarity_score(reference, artists, edges)
    assert gen.similarity_score(reference.clear(), artists, edges)["agreement@10"] is None
    assert gen.similarity_score(reference, artists, edges.clear())["random"] is None
    with pytest.raises(ValueError, match="positive"):
        gen.similarity_score(reference, artists, edges, k=0)


def test_similarity_top_k_and_self(reference):
    artists = pl.DataFrame({"item": [0, 1, 6], "artist_mbid": ["a0", "a1", "a6"]})
    edges = pl.DataFrame({"item": [0, 0, 0], "neighbor": [0, 6, 1], "score": [3.0, 1.0, 2.0]})
    score = gen.similarity_score(reference, artists, edges, k=1)
    assert score["agreement@10"] == 1
    assert score["pairs"] == 1


def test_cluster_scores(reference, clusters):
    members, genres = clusters
    score = gen.cluster_scores(reference, members, genres)
    assert score["genre_match"] == score["median_jaccard"] == 1
    assert score["genres"] == 2
    assert score["random_median_jaccard"] < 1
    assert score == gen.cluster_scores(reference, members, genres)
    assert gen.cluster_scores(reference.clear(), members, genres)["median_jaccard"] is None
    assert gen.cluster_scores(reference.head(4), members, genres)["genres"] == 0
    with pytest.raises(ValueError, match="positive"):
        gen.cluster_scores(reference, members, genres, minimum=0)
    broken = pl.concat(
        [members, members.head(1).with_columns(pl.lit(1).alias("genre"))], how="vertical_relaxed"
    )
    with pytest.raises(ValueError, match="partition"):
        gen.cluster_scores(reference, broken, genres)


def test_naming(reference, clusters):
    members, genres = clusters
    score = gen.naming_score(reference, members, genres)
    assert score["token_match_share"] == score["token_jaccard"] == 1
    assert score["random"] < 1
    assert score["clusters"] == 2
    assert gen.naming_score(reference.clear(), members, genres)["token_match_share"] is None
    assert gen.naming_score(reference, members.clear(), genres)["random"] is None
    unnamed = genres.with_columns(pl.lit("unnamed 0").alias("name"))
    assert gen.naming_score(reference, members, unnamed)["clusters"] == 0
    with pytest.raises(pl.exceptions.ColumnNotFoundError):
        gen.naming_score(reference, members, genres.drop("name"))


def test_layout(reference):
    layout = pl.DataFrame(
        {"genre": ["g0", "g1", "g2", "g3"], "x": [0.0, 0.1, 10.0, 10.1], "y": [0.0] * 4}
    )
    members = pl.DataFrame(
        {"genre": ["g0", "g1", "g2", "g3"], "artist_mbid": ["a0", "a1", "a6", "a7"]}
    )
    score = gen.layout_score(reference, layout, members, layout, k=1)
    assert score["neighbor_cosine@10"] == score["enao_ceiling"] == 1
    assert score["random"] < 1
    assert score["genres"] == 4
    assert gen.layout_score(reference.clear(), layout, members, layout)["random"] is None
    assert gen.layout_score(reference, layout.clear(), members, layout)["genres"] == 0
    with pytest.raises(ValueError, match="positive"):
        gen.layout_score(reference, layout, members, layout, k=0)
    with pytest.raises(pl.exceptions.ColumnNotFoundError):
        gen.layout_score(reference, layout.drop("x"), members, layout)


def test_evaluate_slices_and_missing(reference, clusters, tmp_path, monkeypatch):
    reference.write_parquet(tmp_path / "wikidata.parquet")
    pl.DataFrame({"artist_mbid": ["a0"]}).write_parquet(tmp_path / "crosswalk.parquet")
    members, genres = clusters
    members.write_parquet(tmp_path / "members.parquet")
    genres.write_parquet(tmp_path / "genres.parquet")
    config = {
        "reference": str(tmp_path),
        "crosswalk": str(tmp_path / "crosswalk.parquet"),
        "seed": 42,
        "m1": {"artists": str(tmp_path / "missing")},
        "m2": {
            "memberships": str(tmp_path / "members.parquet"),
            "genres": str(tmp_path / "genres.parquet"),
        },
        "naming": {
            "memberships": str(tmp_path / "members.parquet"),
            "genres": str(tmp_path / "genres.parquet"),
        },
        "layout": {"layout": str(tmp_path / "missing")},
    }
    logged = []
    monkeypatch.setattr(gen, "log", lambda *args: logged.append(args))
    gen.evaluate(config, tmp_path)
    result = json.loads((tmp_path / "metrics.json").read_text())
    assert result["slices"]["independent"]["genres"] == 1
    assert result["slices"]["artists_absent_enao"]["artists"] == 11
    assert result["slices"]["sealed"]["artists"] == 2
    assert result["slices"]["sealed_independent"]["artists"] == 1
    assert result["slices"]["sealed"]["m2"]["genres"] == 0
    assert result["slices"]["sealed"]["naming"]["token_match_share"] == 1
    for name in ["all", "independent", "artists_absent_enao"]:
        assert "m2" not in result["slices"][name]
        assert "naming" not in result["slices"][name]
    assert set(result["unavailable"]) == {"m1", "layout"}
    assert logged[0][1] == "generalization"
    config["crosswalk"] = str(tmp_path / "missing")
    gen.evaluate(config, tmp_path)
    result = json.loads((tmp_path / "metrics.json").read_text())
    assert "artists_absent_enao" in result["unavailable"]
    assert "artists_absent_enao" not in result["slices"]


def test_ingest_sealed_cache(tmp_path, monkeypatch, capsys):
    data = {
        "statements": [{"statement": "s", "mbid": "a", "qid": "wd/Q1", "genre": "rock"}],
        "url_references": [],
        "stated_in": [],
        "linked": [],
        "music": [{"qid": "wd/Q1"}],
    }
    calls = []

    def query(endpoint, name, root):
        calls.append(name)
        return data[name]

    monkeypatch.setattr(gen, "query", query)
    config = {"reference": str(tmp_path), "endpoint": "unused"}
    gen.ingest(config)
    assert len(calls) == 5
    summary = json.loads(capsys.readouterr().out)
    assert summary["rows"] == summary["artists"] == summary["genres"] == 1
    assert summary["dropped_statements"] == 0
    assert len(summary["sha256"]) == 64
    gen.ingest(config)
    assert len(calls) == 5
    assert json.loads(capsys.readouterr().out)["sha256"] == summary["sha256"]


def test_evaluate_layout_item_join(reference, tmp_path, monkeypatch):
    reference.write_parquet(tmp_path / "wikidata.parquet")
    layout = pl.DataFrame(
        {"genre": ["g0", "g1", "g2", "g3"], "x": [0.0, 0.1, 10.0, 10.1], "y": [0.0] * 4}
    )
    layout.write_parquet(tmp_path / "layout.parquet")
    pl.DataFrame({"genre": ["g0", "g1", "g2", "g3"], "item": [9, 2, 4, 7]}).write_parquet(
        tmp_path / "labels.parquet"
    )
    pl.DataFrame({"item": [7, 9, 2, 4], "artist_mbid": ["a7", "a0", "a1", "a6"]}).write_parquet(
        tmp_path / "artists.parquet"
    )
    config = {
        "reference": str(tmp_path),
        "crosswalk": str(tmp_path / "missing"),
        "seed": 42,
        "layout": {
            "layout": str(tmp_path / "layout.parquet"),
            "labels": str(tmp_path / "labels.parquet"),
            "artists": str(tmp_path / "artists.parquet"),
            "ceiling": str(tmp_path / "layout.parquet"),
        },
    }
    config.update(
        {stage: {"missing": str(tmp_path / "missing")} for stage in ["m1", "m2", "naming"]}
    )
    monkeypatch.setattr(gen, "log", lambda *args: None)
    gen.evaluate(config, tmp_path)
    result = json.loads((tmp_path / "metrics.json").read_text())
    assert result["slices"]["all"]["layout"]["genres"] == 4
    assert result["slices"]["all"]["layout"]["neighbor_cosine@10"] == pytest.approx(1 / 3)
    assert result["slices"]["independent"]["layout"]["neighbor_cosine@10"] == 1
    assert result["slices"]["sealed"]["layout"]["genres"] == 1


def test_naming_uses_sealed_member_majority(reference, clusters, tmp_path, monkeypatch):
    reference = reference.with_columns(
        pl.when(pl.col("artist_mbid").is_in(["a1", "a11"]))
        .then(pl.lit("sealed label"))
        .otherwise(pl.col("genre"))
        .alias("genre")
    )
    reference.write_parquet(tmp_path / "wikidata.parquet")
    members, genres = clusters
    members.write_parquet(tmp_path / "members.parquet")
    genres.with_columns(pl.lit("sealed label").alias("name")).write_parquet(
        tmp_path / "genres.parquet"
    )
    config = {
        "reference": str(tmp_path),
        "crosswalk": str(tmp_path / "missing"),
        "seed": 42,
        "naming": {
            "memberships": str(tmp_path / "members.parquet"),
            "genres": str(tmp_path / "genres.parquet"),
        },
    }
    config.update(
        {stage: {"missing": str(tmp_path / "missing")} for stage in ["m1", "m2", "layout"]}
    )
    monkeypatch.setattr(gen, "log", lambda *args: None)
    gen.evaluate(config, tmp_path)
    result = json.loads((tmp_path / "metrics.json").read_text())
    assert result["slices"]["sealed"]["naming"]["token_match_share"] == 1
    assert result["slices"]["sealed_independent"]["naming"]["token_match_share"] == 1


def test_unsupported_stage(tmp_path):
    with pytest.raises(ValueError, match="ingest and eval"):
        gen.execute("build", {}, tmp_path)


def test_overlap_scores(reference):
    artists = reference.select("artist_mbid")
    members = pl.DataFrame(
        {"genre": [0] * 6 + [1] * 6 + [2] * 3, "artist_mbid": [*artists["artist_mbid"], *"xyz"]}
    )
    score = gen.overlap_scores(reference, members, artists)
    assert score["genre_match"] == score["median_jaccard"] == 1
    assert score["genres"] == 2
    assert score["random_median_jaccard"] < 1
    assert gen.overlap_scores(reference, members.clear(), artists)["genre_match"] == 0
    genres = pl.DataFrame({"id": [0, 1, 2], "name": ["Rock", "Pop", "Jazz"]})
    named = gen.overlap_scores(reference, members, artists, genres=genres)
    assert named["genre_match"] == 1
    assert named["named_genre_match"] == 0.5
