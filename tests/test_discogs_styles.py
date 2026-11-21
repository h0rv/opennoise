import polars as pl
import pytest

from opennoise.discogs_styles import candidates, label_key


def test_new_styles_require_repeated_credits_and_distinct_eligible_artists():
    credits = pl.DataFrame(
        [
            (1, "hill country blues", 2),
            (1, "speech", 3),
            (1, "hip hop", 4),
            (2, "hill country blues", 2),
            (3, "hill country blues", 2),
            (4, "hill country blues", 6),
            (5, "hill country blues", 1),
            (6, "hill country blues", 1),
            (7, "hill country blues", 2),
            (7, "speech", 3),
            (7, "hip hop", 4),
            (7, "free funk", 3),
        ],
        schema=["discogs_id", "tag", "weight"],
        orient="row",
    )
    identity = pl.DataFrame(
        {"discogs_id": [1, 2, 3, 3, 4, 5, 6, 7], "artist_mbid": list("abacdefg")}
    )
    accepted = candidates(
        credits,
        identity,
        {"b": "a", "f": "e"},
        {"a", "c", "e", "g"},
        {label_key("Speech"), label_key("Hip-Hop")},
        2,
    )
    assert accepted.select("tag", "artist").rows() == [
        ("hill country blues", "a"),
        ("hill country blues", "g"),
    ]
    assert accepted["score"].to_list() == pytest.approx([2 / 3, 2 / 13])
