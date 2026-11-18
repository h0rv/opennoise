from pathlib import Path

import numpy as np
import polars as pl
from playlist_signal import playlist_edges, tracklists


def test_same_artist_set_is_not_counted_twice(tmp_path: Path) -> None:
    credits = tuple((item, 0, item) for item in range(1, 5))
    rows = {
        "release_group_secondary_type": [(1, "Compilation"), (2, "DJ-mix")],
        "release_group_secondary_type_join": [(10, 1), (10, 2), (20, 2)],
        "release": [(10, "", "", "", 10, 1), (11, "", "", "", 10, 1), (20, "", "", "", 20, 1)],
        "release_status": [(1, "Official")],
        "medium": [(10, 10), (11, 11), (20, 20)],
        "artist": [(item, f"mbid-{item}") for item in range(1, 5)],
        "artist_credit_name": credits,
        "track": [
            (i, "", "", medium, "", "", "", credit, "", "", "", "f")
            for i, (medium, credit) in enumerate(
                [(10, 1), (10, 2), (10, 3), (10, 3), (11, 4), (20, 1), (20, 2), (20, 3)]
            )
        ],
    }
    for table, records in rows.items():
        (tmp_path / table).write_text(
            "".join("\t".join(map(str, record)) + "\n" for record in records)
        )
    artists = pl.DataFrame(
        {
            "item": range(4),
            "artist_mbid": [f"mbid-{i}" for i in range(1, 5)],
            "artist_name": ["A", "B", "C", "D"],
        }
    )
    assert tracklists(tmp_path, artists).rows() == [("DJ-mix", [0, 1, 2])]


def test_only_repeated_co_occurrence_boosts_neighbors() -> None:
    n = 51
    neighbors = (np.arange(n)[:, None] + np.arange(1, 51)) % n
    base = pl.DataFrame(
        {
            "item": np.repeat(np.arange(n), 50),
            "neighbor": neighbors.ravel(),
            "score": np.ones(n * 50),
        }
    )
    boosted = playlist_edges(pl.DataFrame({"item": [[0, 1, 2], [0, 1, 3]]}), base, n)
    row = boosted.filter(pl.col("item") == 0)
    assert row.filter(pl.col("score") > 1).select("neighbor", "score").rows() == [(1, 1.25)]
    assert boosted.filter(pl.col("item") >= 2).equals(base.filter(pl.col("item") >= 2))
