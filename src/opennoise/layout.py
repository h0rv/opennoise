import datetime
import hashlib
import json
import pickle
import subprocess
import time
import tomllib
from pathlib import Path

import numpy as np
import polars as pl
from scipy import sparse
from scipy.stats import spearmanr
from sklearn.preprocessing import normalize
from threadpoolctl import threadpool_limits
from umap import UMAP

from opennoise import sonic
from opennoise.genres import heldout_genres
from opennoise.layout_metrics import evaluation_scores


def inputs(config, run):
    root = Path(config["reference"])
    m2 = tomllib.loads(Path(config["m2_config"]).read_text())
    config["input_run"] = m2["m1"]
    heldout = heldout_genres(m2)
    genres = pl.read_parquet(root / "map.parquet", columns=["genre"]).sort("genre")
    genres = genres.with_row_index("index")
    test = np.array([g in heldout for g in genres["genre"]])
    folds = np.full(len(genres), -1)
    train = np.flatnonzero(~test)
    folds[np.random.default_rng(config["seed"]).permutation(train)] = np.arange(len(train)) % 5
    genres = genres.with_columns(
        pl.Series("split", np.where(test, "test", "train")), pl.Series("fold", folds)
    )
    genres.select("genre", "split", "fold").write_parquet(run / "genre_split.parquet")
    artists = pl.read_parquet(Path(config["input_run"]) / "artists.parquet").sort("item")
    members = (
        pl.read_parquet(root / "labels.parquet")
        .join(genres.select("genre", "index"), on="genre")
        .select("index", "item")
        .unique()
    )
    membership = sparse.csr_matrix(
        (
            np.ones(len(members), dtype=np.float32),
            (members["index"].to_numpy(), members["item"].to_numpy()),
        ),
        shape=(len(genres), len(artists)),
    )
    return genres, artists, membership


def artist_vectors(config, source):
    if "+" in source:
        return np.concatenate(
            [normalize(artist_vectors(config, part)) for part in source.split("+")], axis=1
        )
    return np.load(Path(config["input_run"]) / f"{source}.npy")


def evaluate(config, genres, placed, points, vectors, axes=True):
    reference = pl.read_parquet(Path(config["reference"]) / "map.parquet")
    frame = genres.filter(placed).join(reference, on="genre", maintain_order="left")
    return evaluation_scores(
        points,
        frame.select("x", "y").to_numpy().astype(float),
        vectors,
        frame["split"].to_numpy() == "test",
        frame["fold"].to_numpy(),
        int((genres["split"] == "test").sum()),
        [
            genres.filter((pl.col("split") == "train") & (pl.col("fold") == f)).height
            for f in range(5)
        ],
        axes=axes,
    )


def best_islands(results):
    return max(
        (name for name, metrics in results.items() if metrics["family"] == "islands"),
        key=lambda name: results[name]["cv_vector_overlap@10"],
    )


def layout(config, run):
    if "catalog_run" in config:
        from opennoise.placement import export

        export(config, run)
        return
    genres, artists, membership = inputs(config, run)
    features = pl.read_parquet(config["audio_features"])
    embedding = config["islands_representation"]
    vectors = normalize(artist_vectors(config, embedding))
    genre_vectors = normalize(membership @ vectors)
    start = time.monotonic()
    artist_points, audio = sonic.artist_axes(features, artists)
    with threadpool_limits(limits=config["workers"]):
        artist_points, audio = sonic.fill_artists(
            artist_points, audio, artist_vectors(config, "als_2")
        )
    audio_points, placed, counts = sonic.genre_axes(
        membership, artist_points, audio, artists["listeners"].to_numpy(), config["min_members"]
    )
    train = genres.filter(placed)["split"].to_numpy() == "train"
    audio_points = sonic.rank_transform(audio_points[placed], audio_points[placed])
    with threadpool_limits(limits=config["workers"]):
        state, points = sonic.fit(genre_vectors[placed], audio_points, train, config)
    with (run / "sonic_model.pkl").open("wb") as stream:
        pickle.dump(state, stream)
    captions, correlations = audio_captions(features, artists, membership[placed], points, ~train)
    (run / "audio_correlations.json").write_text(json.dumps(correlations, indent=2))
    axes = "sonic_umap_ranked"
    np.save(run / f"{axes}_coords.npy", points)
    frame = (
        genres.filter(placed)
        .select("genre", "split")
        .with_columns(pl.Series("members", counts[placed]))
    )
    frame.write_parquet(run / f"{axes}_placed.parquet")
    results = {
        axes: {
            "family": "axes",
            "status": "ok",
            "audio_correlations": correlations,
            **evaluate(config, genres, placed, points, genre_vectors[placed]),
            "seconds": time.monotonic() - start,
        }
    }
    print(axes, json.dumps(results[axes]), flush=True)
    reference_vectors = genre_vectors[placed]
    np.save(run / "islands_genre_vectors.npy", reference_vectors)
    for neighbors in config["umap_neighbors"]:
        start = time.monotonic()
        name = f"islands_{neighbors}_spectral"
        with threadpool_limits(limits=config["workers"]):
            points = islands_model(config, neighbors).fit_transform(reference_vectors)
        np.save(run / f"{name}_coords.npy", points)
        results[name] = {
            "family": "islands",
            "status": "ok",
            "neighbors": neighbors,
            **evaluate(config, genres, placed, points, reference_vectors, axes=False),
            "seconds": time.monotonic() - start,
        }
        print(name, json.dumps(results[name]), flush=True)
    islands = best_islands(results)
    winners = {"axes": axes, "islands": islands}
    output = frame
    for family, name in winners.items():
        points = np.load(run / f"{name}_coords.npy")
        columns = ["x", "y"] if family == "axes" else ["island_x", "island_y"]
        output = output.with_columns(
            pl.Series(columns[0], points[:, 0]), pl.Series(columns[1], points[:, 1])
        )
    output.write_parquet(run / "genre_layout.parquet")
    (run / "layout_metrics.json").write_text(json.dumps(results, indent=2, allow_nan=False))
    (run / "layout_best.json").write_text(json.dumps(winners, indent=2))
    (run / "layout_models.json").write_text(
        json.dumps(
            {
                "captions": captions,
                "audio_sha256": hashlib.sha256(
                    Path(config["audio_features"]).read_bytes()
                ).hexdigest(),
                "embedding": embedding,
                "neighbors": results[islands]["neighbors"],
            },
            indent=2,
        )
    )
    print("Best", json.dumps(winners), flush=True)
    if not (run / "layout_logged").exists():
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
        with Path("experiments/results.tsv").open("a") as stream:
            for name, metrics in results.items():
                stream.write(
                    "\t".join(
                        [
                            datetime.datetime.now(datetime.UTC).isoformat(),
                            commit,
                            run.name,
                            name,
                            json.dumps(metrics, separators=(",", ":")),
                            "kept" if name in winners.values() else "discarded",
                            "ALS+audio UMAP; audio orientation, ranks, repulsion; spectral islands",
                        ]
                    )
                    + "\n"
                )
        (run / "layout_logged").touch()


def islands_model(config, neighbors):
    return UMAP(
        n_neighbors=neighbors,
        min_dist=config["umap_min_dist"],
        n_epochs=config["umap_epochs"],
        metric="cosine",
        init="spectral",
        random_state=config["seed"],
        n_jobs=1,
        compatibility_layout=True,
    )


def audio_captions(features, artists, membership, points, heldout):
    columns = [c for c in features.columns if c not in {"item", "artist_mbid", "recordings"}]
    values = (
        artists.select("item")
        .join(features.select("item", *columns), on="item", how="left", maintain_order="left")
        .select(columns)
        .to_numpy()
        .astype(float)
    )
    finite = np.isfinite(values)
    weighted = membership @ sparse.diags(np.log(np.maximum(artists["listeners"].to_numpy(), 2)))
    totals = weighted @ finite.astype(float)
    means = (weighted @ np.where(finite, values, 0)) / np.maximum(totals, 1e-12)
    correlations, captions = {}, {}
    for axis, name in enumerate(["x", "y"]):
        scores = {}
        for i, column in enumerate(columns):
            mask = heldout & (totals[:, i] > 0)
            if mask.sum() > 2 and np.ptp(means[mask, i]) > 0:
                scores[column] = {
                    "rho": float(spearmanr(points[mask, axis], means[mask, i]).statistic),
                    "genres": int(mask.sum()),
                }
        correlations[name] = scores
        feature = max(scores, key=lambda c: abs(scores[c]["rho"]), default=None)
        rho = scores[feature]["rho"] if feature is not None else 0
        if feature is not None and abs(rho) >= 0.4:
            label = {
                "genre_dortmund_funksoulrnb": "funk/soul/R&B audio score",
                "genre_rosamerica_roc": "rock audio score",
            }.get(feature, feature.replace("_", " "))
            low, high = f"Lower {label}", f"Higher {label}"
            captions[f"{name}_min"], captions[f"{name}_max"] = (
                (low, high) if rho > 0 else (high, low)
            )
        else:
            captions[f"{name}_min"] = f"Listening component {axis + 1} (low)"
            captions[f"{name}_max"] = f"Listening component {axis + 1} (high)"
    return captions, correlations
