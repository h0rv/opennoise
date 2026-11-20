import polars as pl
import pytest

from opennoise.familiarity import evaluate, priority
from opennoise.names import write


def test_priority_handles_minimal_listeners_and_baseline():
    assert priority(0.8, None, 0.1) == 0.8
    assert priority(0.8, 0, 0.1) == 0.8
    assert priority(0.8, 10000, 0) == 0.8
    assert priority(0.8, 10000, 0.1) == 0.8 / 10000**0.1
    assert priority(0.8, 10, 0.1) > priority(0.8, 10000, 0.1)


def test_agreement_and_listener_median(tmp_path):
    (tmp_path / "artists").mkdir()
    write(
        tmp_path / "artists" / "a.json",
        {
            "similar": [
                {"artist": {"id": "b", "listeners": 100}, "score": 1},
                {"artist": {"id": "c", "listeners": None}, "score": 0.8},
            ]
        },
    )
    reference = pl.DataFrame({"artist_mbid": ["a", "b", "c"], "genre": ["pop", "pop", "rock"]})
    result = evaluate(tmp_path, {"everynoise": reference}, alphas=(0, 0.1))
    assert result["0"]["everynoise"] == {"agreement": 0.5, "artists": 1}
    assert result["0.1"]["median_listeners"] == 50.5
    write(tmp_path / "artists" / "a.json", {"similar": None})
    assert evaluate(tmp_path, {"everynoise": reference})["0"]["everynoise"] == {
        "agreement": None,
        "artists": 0,
    }


def test_invalid_artist_file(tmp_path):
    (tmp_path / "artists").mkdir()
    (tmp_path / "artists" / "a.json").write_text("not json")
    with pytest.raises(ValueError):
        evaluate(tmp_path, {"everynoise": pl.DataFrame({"artist_mbid": ["a"], "genre": ["pop"]})})
