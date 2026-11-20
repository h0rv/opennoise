import json
import shutil
from pathlib import Path

import polars as pl
import pytest

from opennoise.genre_order import evaluate, everynoise, priority
from opennoise.names import write


def test_priority_penalizes_tiny_and_huge_genres():
    assert priority(0.6, 10000, 10000) > priority(1, 800, 10000)
    assert priority(1, 10000, 10000) > priority(1, 1000000, 10000)
    assert priority(0.7, 0, None) == 0.7
    assert priority(1, 0, 10000) == 0


def test_evaluate_matches_aliases_and_counts_unmatchable_artists(tmp_path):
    root = tmp_path / "catalog"
    shutil.copytree(Path(__file__).parent / "fixtures" / "catalog", root)
    genres = json.loads((root / "genres.json").read_text())
    next(g for g in genres if g["id"] == "electronic")["aliases"] = ["électronic music"]
    write(root / "genres.json", genres)
    reference = pl.DataFrame(
        {
            "artist_mbid": [
                "00000000-0000-4000-8000-000000000001",
                "00000000-0000-4000-8000-000000000002",
                "absent",
            ],
            "genre": ["electronic music", "unmatched", "techno"],
        }
    )
    results = evaluate(root, {"reference": reference}, sizes=(None, 10000))
    assert results["None"]["reference"] == {
        "artists": 2,
        "matchable": 1,
        "top1": 0,
        "top3": 0.5,
    }
    assert results["10000"]["reference"]["top1"] == 0.5


def test_evaluate_empty_reference(tmp_path):
    root = tmp_path / "catalog"
    shutil.copytree(Path(__file__).parent / "fixtures" / "catalog", root)
    reference = pl.DataFrame(schema={"artist_mbid": pl.String, "genre": pl.String})
    assert evaluate(root, {"empty": reference})["None"]["empty"] == {
        "artists": 0,
        "matchable": 0,
        "top1": None,
        "top3": None,
    }


def test_evaluate_missing_release(tmp_path):
    with pytest.raises(FileNotFoundError):
        evaluate(tmp_path, {})


def test_everynoise_reuses_mbid_crosswalk_and_genre_holdout(tmp_path):
    release = tmp_path / "catalog"
    shutil.copytree(Path(__file__).parent / "fixtures" / "catalog", release)
    cache = tmp_path / "reference"
    dump = cache / "mbdump"
    dump.mkdir(parents=True)
    artist = "00000000-0000-4000-8000-000000000001"
    spotify = "a" * 22
    (dump / "artist").write_text(f"1\t{artist}\n")
    (dump / "url").write_text(f"1\tunused\thttps://open.spotify.com/artist/{spotify}\n")
    (dump / "l_artist_url").write_text("0\t0\t1\t1\n")
    write(
        cache / "enao.json",
        [{"genre": name, "artists": [{"artist_id": spotify}]} for name in ["pop", "rock"]],
    )
    (cache / "map.html").write_text(
        "".join(
            f'<div class="genre scanme" style="left: 1px; top: 2px">{name}</div>'
            for name in ["pop", "rock"]
        )
    )
    reference = everynoise(cache, release, {"seed": 42, "genre_holdout": 0.5, "min_artists": 1})
    assert reference.rows() == [(artist, "pop")]
    assert (cache / "crosswalk.parquet").exists()
