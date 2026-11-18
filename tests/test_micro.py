import numpy as np
import polars as pl
from scipy import sparse

from opennoise.micro import (
    capped,
    jaccard,
    learned_words,
    modifier_sources,
    overlay,
    release,
    split_name,
)


def test_split_name_prefers_longest_place_and_known_style():
    words = {"new": 1, "new zealand": 2, "polish": 3}
    assert split_name("New Zealand Indie", words) == (2, "new zealand", "indie")
    assert split_name("polish black metal", words, {"black metal"}) == (3, "polish", "black metal")
    assert split_name("polish zzz", words, {"black metal"}) is None
    assert split_name("polish", words) is None


def test_learned_words_finds_unlisted_place_and_rejects_false_one():
    depth = sparse.csr_matrix((np.ones(10), (np.arange(10), [0] * 5 + [1] * 5)), shape=(100, 2))
    train = {
        "kiwi rock": np.array([0, 1, 2]),
        "kiwi pop": np.array([2, 3, 4]),
        "deep rock": np.array([5, 20, 21, 22]),
        "deep pop": np.array([23, 24, 25, 26]),
    }
    learned, rejected = learned_words(train, depth, {"deep": 1}, {"rock", "pop"})
    assert learned == {"kiwi": 0}
    assert rejected == {"deep"}


def test_jaccard():
    assert jaccard(np.array([1, 2, 3]), np.array([2, 3, 4])) == 0.5


def test_modifier_sources_require_multiple_styles_and_skip_places():
    train = ["deep house", "deep techno", "polish house", "polish techno", "minimal techno"]
    order = {name: i for i, name in enumerate(train)}
    found = modifier_sources(train, {"house": 0, "techno": 1}, order, {"polish": 3}, 2)
    assert {prefix: ids.tolist() for prefix, ids in found.items()} == {"deep": [0, 1]}


def test_overlay_limits_new_names_and_keeps_the_first_baseline_match(tmp_path):
    pl.DataFrame(
        {
            "id": [0, 1, 2],
            "name": ["Deep Pop", "deep pop", "Rock"],
            "place": ["1", "1", None],
            "style": ["pop", "pop", "rock"],
            "real": [0.9, 0.8, 0.7],
        }
    ).write_parquet(tmp_path / "genres.parquet")
    pl.DataFrame(
        {"genre": [0, 1, 2], "artist_mbid": ["a", "b", "b"], "score": [0.7, 0.6, 0.5]}
    ).write_parquet(tmp_path / "memberships.parquet")
    base = {"artists": pl.DataFrame({"item": [0, 1], "artist_mbid": ["a", "b"]}), "areas": ["1"]}
    proposals = [
        (name, -1, 0, np.array([0, 1]), np.array([0.6, 0.8]))
        for name in ["deep pop", "indie pop", "art pop"]
    ]
    combined, real, styles = overlay(
        {"baseline": str(tmp_path), "additions": 1},
        base,
        proposals,
        np.array([0.85, 0.8, 0.7]),
        ["pop"],
    )
    assert [p[0] for p in combined] == ["indie pop", "Deep Pop", "Rock"]
    assert capped(combined[0], 1)[3].tolist() == [1]
    assert combined[1][3].tolist() == [0]
    assert real.tolist() == [0.8, 0.9, 0.7]
    assert styles == ["pop", "rock"]


def test_release_appends_micro_genres(tmp_path):
    genres = pl.DataFrame(
        {
            "id": [0, 1],
            "name": ["Punk", "unnamed 1"],
            "level": [-1, 0],
            "parent": [None, None],
            "size": [1, 1],
        },
        schema_overrides={"parent": pl.Int64},
    )
    memberships = pl.DataFrame({"artist": ["a"], "genre": [0], "score": [0.5]})
    pl.DataFrame(
        {
            "id": [0, 1, 2, 3, 4],
            "name": ["punk", "swedish punk", "swedish zydeco", "sweden zydeco", "swedish punk"],
            "style": ["punk", "punk", "zydeco", "zydeco", "swedish punk"],
            "size": [1, 1, 1, 1, 1],
        }
    ).write_parquet(tmp_path / "genres.parquet")
    pl.DataFrame(
        {
            "genre": [0, 1, 2, 3, 4],
            "artist_mbid": ["a", "b", "c", "c", "d"],
            "score": [0.9, 0.8, 0.7, 0.6, 0.5],
        }
    ).write_parquet(tmp_path / "memberships.parquet")
    genres, memberships = release(tmp_path, genres, memberships)
    assert genres.select("id", "name", "level", "parent").rows()[2:] == [
        (3, "swedish punk", 1, None),
        (4, "swedish zydeco", 1, None),
    ]
    assert memberships.rows() == [("a", 0, 0.5), ("b", 3, 0.8), ("c", 4, 0.7)]


def test_release_adds_micro_genres_without_replacing_published_memberships(tmp_path):
    base = pl.DataFrame(
        {"id": [7], "name": ["Punk"], "level": [-1], "parent": [None], "size": [1]},
        schema_overrides={"parent": pl.Int64},
    )
    members = pl.DataFrame({"artist": ["a"], "genre": [7], "score": [0.9]})
    previous, extra = tmp_path / "previous", tmp_path / "extra"
    for path, names, artists in [
        (previous, ["swedish punk"], ["b"]),
        (extra, ["swedish punk", "punk from sweden", "indie punk"], ["c", "b", "d"]),
    ]:
        path.mkdir()
        ids = list(range(len(names)))
        pl.DataFrame({"id": ids, "name": names, "size": [1] * len(ids)}).write_parquet(
            path / "genres.parquet"
        )
        pl.DataFrame(
            {"genre": ids, "artist_mbid": artists, "score": [0.8] * len(ids)}
        ).write_parquet(path / "memberships.parquet")
    genres, edges = release(previous, base, members, additions=extra)
    assert genres.select("id", "name", "level").rows() == [
        (7, "Punk", -1),
        (8, "swedish punk", 0),
        (11, "indie punk", 0),
    ]
    assert edges.rows() == [("a", 7, 0.9), ("b", 8, 0.8), ("d", 11, 0.8)]
