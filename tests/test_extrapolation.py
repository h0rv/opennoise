import json

import polars as pl
import pytest

from opennoise.extrapolation import (
    agreement,
    artist_tags,
    cohorts,
    evaluate,
    interval,
    map_neighbors,
    prepare,
    read_catalog,
)


def test_interval():
    assert interval([]) == {"mean": None, "ci95": None, "artists": 0}
    assert interval([1, 1]) == {"mean": 1.0, "ci95": [1.0, 1.0], "artists": 2}
    result = interval([0, 1])
    assert result["mean"] == 0.5
    assert result["ci95"] == [0.0, 1.0]


def test_agreement_filters_after_top_ten_and_excludes_self():
    labels = {"a": {"rock"}, "b": {"rock"}, "c": {"jazz"}}
    neighbors = {"a": ["b", "c", *["unknown"] * 8, "b"], "b": ["b"]}
    result = agreement(["a", "b", "missing"], neighbors, labels, labels)
    assert result["actual"] == {"mean": 0.5, "ci95": [0.5, 0.5], "artists": 1}
    assert result["pairs"] == 2
    assert result["random"] == agreement(["a"], neighbors, labels, labels)["random"]
    assert agreement([], {}, {}, [])["actual"]["mean"] is None
    assert agreement(["a"], neighbors, labels, ["a"])["pairs"] == 0


def test_map_neighbors():
    catalog = pl.DataFrame({"id": ["a", "b", "c", "d"], "x": [0.0, 0.1, 1.0, None], "y": [0.0] * 4})
    assert map_neighbors(catalog) == {"a": ["b", "c"], "b": ["a", "c"], "c": ["b", "a"]}
    assert map_neighbors(catalog.head(1)) == {}


def test_cohort_dates_credits_and_enao(tmp_path):
    root = tmp_path / "mbdump"
    root.mkdir()
    (tmp_path / "enao.json").write_text(json.dumps([{"artists": [{"artist_id": "A" * 22}]}]))
    (root / "artist").write_text("".join(f"{i}\tartist{i}\n" for i in range(1, 9)))
    (root / "artist_credit_name").write_text(
        "".join(f"{i}\t0\t{i}\n" for i in range(1, 9)) + "1\t1\t8\n"
    )
    (root / "release_group").write_text(
        "".join(f"{i}\tgid\tname\t{i}\n" for i in range(1, 8)) + "9\tgid\tname\t6\n"
    )
    (root / "release_group_meta").write_text(
        "1\t1\t2024\t\\N\t\\N\n"
        "2\t1\t2023\t11\t30\n"
        "3\t1\t2023\t12\t1\n"
        "4\t1\t2023\t\\N\t\\N\n"
        "5\t1\t2025\t1\t1\n"
        "6\t1\t2026\t1\t1\n"
        "7\t1\t2022\t\\N\t\\N\n"
        "9\t1\t\\N\t\\N\t\\N\n"
    )
    (root / "url").write_text(f"1\tgid\thttps://open.spotify.com/artist/{'A' * 22}\n")
    (root / "l_artist_url").write_text("1\t0\t5\t1\n")
    catalog = pl.DataFrame({"id": [f"artist{i}" for i in range(1, 9)]})
    new, old, summary = cohorts(root, catalog)
    assert set(new) == {"artist1", "artist8"}
    assert set(old) == {"artist2", "artist7"}
    assert summary["new_release_group_years"] == {"2024": 2, "2025": 0, "2026": 0}
    assert summary["with_undated_groups"] == 1
    assert summary["enao_members"] == 1


def test_read_catalog_empty(tmp_path):
    with pytest.raises(ValueError, match="no artist details"):
        read_catalog(tmp_path)


def test_catalog_coverage_and_empty_cohort(tmp_path):
    artists = tmp_path / "artists"
    artists.mkdir()
    for artist, point, genres, similar in (
        ("a", {"x": 0.0, "y": 0.0}, [{"id": "rock", "score": 1}], []),
        ("b", None, None, [{"artist": {"id": "a"}, "score": 1}]),
    ):
        (artists / f"{artist}.json").write_text(
            json.dumps(
                {
                    "artist": {
                        "id": artist,
                        "name": artist,
                        "listeners": 1,
                        "positions": {"axes": point},
                    },
                    "genres": genres,
                    "similar": similar,
                }
            )
        )
    catalog = read_catalog(tmp_path)
    reference = pl.DataFrame({"artist_mbid": ["a", "b"], "genre_qid": ["rock", "rock"]})
    result = evaluate(catalog, [], ["a", "b"], reference)
    assert result["new"]["coverage"]["position"]["mean"] is None
    assert result["old"]["coverage"]["position"]["mean"] == 0.5
    assert result["old"]["coverage"]["genres"]["mean"] == 0.5
    assert result["old"]["coverage"]["similar"]["mean"] == 0.5
    assert result["old"]["coverage"]["all_three"]["mean"] == 0.0
    assert result["old"]["similar"]["actual"]["mean"] == 1.0


def test_prepare_rejects_stale_release(tmp_path):
    release = tmp_path / "release"
    release.mkdir()
    (release / "manifest.json").write_text('{"release_id":"stale"}')
    with pytest.raises(ValueError, match="cached release differs"):
        prepare(tmp_path)


def test_evaluation_only_tags(tmp_path):
    dump = tmp_path / "mbdump"
    dump.mkdir()
    (tmp_path / "tags.done").touch()
    (dump / "artist").write_text("1\ta\n2\tb\n3\tc\n")
    (dump / "artist_tag").write_text("1\t1\t2\n2\t1\t0\n3\t1\t1\n")
    (dump / "tag").write_text("1\trock\n")
    tags = artist_tags(tmp_path, pl.DataFrame({"id": ["a", "b"]}))
    assert tags.to_dicts() == [{"artist_mbid": "a", "genre_qid": "rock"}]
