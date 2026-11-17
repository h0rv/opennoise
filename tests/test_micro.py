import numpy as np
import polars as pl
from scipy import sparse

from opennoise.micro import jaccard, learned_words, release, split_name


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
