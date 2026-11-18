import hashlib
import json
import pickle

import numpy as np
import polars as pl
import pytest

from opennoise import placement
from opennoise.placement import bounds


class Projection:
    def transform(self, vectors):
        return vectors[:, :2]


def test_bounds_finite_and_constant():
    a, b = bounds([np.array([[1.0, 3.0], [5.0, 3.0]]), np.empty((0, 2))])
    np.testing.assert_array_equal(a, [[0, 0], [1, 0]])
    assert b.shape == (0, 2)


def test_export_uses_audio_not_reference_coordinates(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    m1, source, evaluated, run = [tmp_path / name for name in ["m1", "catalog", "eval", "out"]]
    for folder in [m1, source, evaluated, run]:
        folder.mkdir()
    artists = pl.DataFrame(
        {"item": [0, 1, 2], "artist_mbid": ["a", "b", "c"], "listeners": [2, 4, 8]}
    )
    artists.write_parquet(m1 / "artists.parquet")
    features = pl.DataFrame(
        {
            "item": [0, 1],
            "danceability": [0.0, 1.0],
            "onset_rate": [0.0, 1.0],
            "dynamic_complexity": [1.0, 0.0],
            "mood_acoustic_acoustic": [1.0, 0.0],
            "mood_electronic_electronic": [0.0, 1.0],
        }
    )
    feature_path = m1 / "features.parquet"
    features.write_parquet(feature_path)
    for name in ["als_2", "audio_ab_all"]:
        np.save(m1 / f"{name}.npy", np.eye(3))
    (source / "config.toml").write_text(f'm1 = "{m1}"\n')
    (source / "genre_ids.json").write_text(json.dumps({0: "g0", 1: "g1", 2: "g2"}))
    (source / "release-summary.json").write_text("{}")
    settings = tmp_path / "layout.toml"
    settings.write_text(
        f'audio_features = "{feature_path}"\nmin_members = 1\nworkers = 1\n'
        "seed = 42\numap_min_dist = 0.1\numap_epochs = 10\n"
    )
    winners = {"axes": "sonic_umap_ranked", "islands": "islands_2_spectral"}
    (evaluated / "layout_best.json").write_text(json.dumps(winners))
    (evaluated / "layout_metrics.json").write_text(
        json.dumps({name: {} for name in winners.values()})
    )
    (evaluated / "layout_models.json").write_text(
        json.dumps(
            {
                "captions": {
                    "x_min": "Low component 1",
                    "x_max": "High component 1",
                    "y_min": "Low component 2",
                    "y_max": "High component 2",
                },
                "audio_sha256": hashlib.sha256(feature_path.read_bytes()).hexdigest(),
                "embedding": "als_2+audio_ab_all",
                "neighbors": 2,
            }
        )
    )
    np.save(evaluated / "islands_genre_vectors.npy", np.eye(3))
    with (evaluated / "sonic_model.pkl").open("wb") as stream:
        pickle.dump(
            {
                "model": Projection(),
                "center": np.zeros(2),
                "rotation": np.eye(2),
                "reference": np.array([[0, 0], [1 / np.sqrt(2), 1 / np.sqrt(2)]]),
            },
            stream,
        )
    np.save(evaluated / "islands_2_spectral_coords.npy", np.array([[0, 1], [1, 0], [2, 2]]))

    class Islands:
        def fit_transform(self, vectors):
            return np.array([[0, 1], [1, 0], [2, 2]])

        def transform(self, vectors):
            return np.column_stack([np.arange(len(vectors)), np.arange(len(vectors))])

    genres = pl.DataFrame({"id": [0, 1, 2], "parent": [None, None, None], "name": ["A", "B", "C"]})
    members = pl.DataFrame({"genre": [0, 1, 2], "artist": ["a", "b", "c"], "score": [1.0] * 3})
    monkeypatch.setattr(placement, "tables", lambda config: (genres, members))
    monkeypatch.setattr(placement.layout, "islands_model", lambda *args: Islands())
    monkeypatch.setattr(placement.tags, "log", lambda *args: None)
    config = {
        "evaluation_run": str(evaluated),
        "layout_config": str(settings),
        "catalog_run": str(source),
    }
    placement.export(config, run)
    positions = pl.read_parquet(run / "positions.parquet")
    assert positions.filter(pl.col("x").is_not_null()).height == 6
    assert positions.filter(pl.col("id") == "g0").select("x", "y").row(0) == pytest.approx((1, 0))
    assert positions.filter(pl.col("id") == "a").select("x", "y").row(0) == pytest.approx((1, 0))
    assert positions.filter(pl.col("id") == "c")["x"][0] == 0
    placement.export(config, run)
    features.with_columns(pl.col("danceability") + 1).write_parquet(feature_path)
    with pytest.raises(ValueError, match="Immutable"):
        placement.export(config, run)
