import numpy as np
import polars as pl

from opennoise.genres import heldout_genres, split_labels


def test_shared_holdout_preserves_member_split(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    root = tmp_path / "data/m2"
    root.mkdir(parents=True)
    names = [f"genre {i}" for i in range(12)]
    labels = pl.DataFrame(
        {
            "genre": np.repeat(names, 10),
            "item": np.arange(120, dtype=np.uint32),
        }
    )
    labels.write_parquet(root / "labels.parquet")
    pl.DataFrame({"genre": names[:-1]}).write_parquet(root / "map.parquet")
    config = {"seed": 42, "min_artists": 5, "genre_holdout": 0.2, "artist_holdout": 0.2}
    eligible = sorted(names[:-1])
    rng = np.random.default_rng(config["seed"])
    expected = set(
        rng.choice(eligible, int(len(eligible) * config["genre_holdout"]), replace=False)
    )
    assert heldout_genres(config) == expected
    train, hidden, heldout, truth = split_labels(config)
    assert set(heldout) == expected
    assert set(truth) == set(eligible)
    for group in labels.partition_by("genre"):
        name = group["genre"][0]
        if name not in eligible or name in expected:
            continue
        items = rng.permutation(np.sort(group["item"].to_numpy()))
        cut = max(1, int(len(items) * config["artist_holdout"]))
        np.testing.assert_array_equal(hidden[name], items[:cut])
        np.testing.assert_array_equal(train[name], items[cut:])
