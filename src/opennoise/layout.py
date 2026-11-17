import concurrent.futures
import datetime
import json
import multiprocessing
import subprocess
import time
import tomllib
from pathlib import Path

import numpy as np
import polars as pl
from scipy import sparse
from scipy.spatial import KDTree
from sklearn.decomposition import TruncatedSVD
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import Ridge
from sklearn.multioutput import MultiOutputRegressor
from sklearn.neighbors import KNeighborsRegressor
from sklearn.preprocessing import StandardScaler, normalize
from threadpoolctl import threadpool_limits
from umap import UMAP

from opennoise.genres import heldout_genres
from opennoise.layout_metrics import evaluation_scores


def inputs(config, run):
    root = Path(config["reference"])
    m2 = tomllib.loads(Path(config["m2_config"]).read_text())
    config["input_run"] = m2["m1"]
    heldout = heldout_genres(m2)
    genres = pl.read_parquet(root / "map.parquet").sort("genre").with_row_index("index")
    test = np.array([g in heldout for g in genres["genre"]])
    folds = np.full(len(genres), -1)
    train = np.flatnonzero(~test)
    folds[np.random.default_rng(config["seed"]).permutation(train)] = np.arange(len(train)) % 5
    genres = genres.with_columns(
        pl.Series("split", np.where(test, "test", "train")),
        pl.Series("fold", folds),
    )
    genres.select("genre", "split", "fold").write_parquet(run / "genre_split.parquet")
    artists = pl.read_parquet(Path(config["input_run"]) / "artists.parquet")
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
    counts = np.diff(membership.indptr)
    genres = genres.with_columns(pl.Series("members", counts))
    return genres, membership


def artist_vectors(config, run, source):
    input_run = Path(config["input_run"])
    if source == "concat":
        return np.concatenate(
            [
                normalize(artist_vectors(config, run, "tfidf")),
                normalize(artist_vectors(config, run, config["concat_als"])),
            ],
            axis=1,
        )
    if "+" in source:
        return np.concatenate(
            [normalize(artist_vectors(config, run, part)) for part in source.split("+")], axis=1
        )
    if source != "tfidf":
        return np.load(input_run / f"{source}.npy")
    path = run / "tfidf_svd.npy"
    if path.exists():
        return np.load(path)
    matrix = sparse.load_npz(input_run / "train.npz")
    matrix.data = np.log1p(matrix.data)
    idf = np.log1p(matrix.shape[1] / np.maximum(np.diff(matrix.indptr), 1))
    vectors = normalize((sparse.diags(idf) @ matrix).T.tocsr())
    with threadpool_limits(limits=config["workers"]):
        vectors = TruncatedSVD(
            n_components=config["dimensions"], random_state=config["seed"]
        ).fit_transform(vectors)
    vectors = normalize(vectors).astype(np.float32)
    np.save(path, vectors)
    print(f"{source} artist vectors {vectors.shape}", flush=True)
    return vectors


def estimator(kind, parameter, config):
    if kind in {"ridge", "shuffle"}:
        return Ridge(alpha=parameter)
    if kind == "knn":
        return KNeighborsRegressor(n_neighbors=parameter, metric="cosine", weights="distance")
    if kind == "boost":
        return MultiOutputRegressor(
            HistGradientBoostingRegressor(
                max_depth=parameter,
                max_iter=config["boost_iterations"],
                random_state=config["seed"],
                early_stopping=False,
            )
        )
    raise ValueError(f"Unknown regressor: {kind}")


def predict(kind, parameter, config, vectors, coordinates, train, target):
    if kind == "ensemble":
        return (
            predict("knn", 5, config, vectors, coordinates, train, target)
            + predict("ridge", parameter, config, vectors, coordinates, train, target)
        ) / 2
    scaler = StandardScaler().fit(coordinates[train])
    y = scaler.transform(coordinates[train])
    if kind == "shuffle":
        y = np.random.default_rng(config["seed"]).permutation(y)
    model = estimator(kind, parameter, config)
    model.fit(vectors[train], y)
    return scaler.inverse_transform(model.predict(vectors[target]))


def axes_job(job):
    name, kind, parameter, config, vectors, coordinates, test, folds, totals, run = job
    start = time.monotonic()
    try:
        with threadpool_limits(limits=1):
            points = crossfit(kind, parameter, config, vectors, coordinates, test, folds)
            scores = evaluation_scores(points, coordinates, vectors, test, folds, *totals)
            np.save(run / f"{name}_coords.npy", points)
        return name, {
            "family": "axes",
            "status": "ok",
            **scores,
            "seconds": time.monotonic() - start,
        }
    except Exception as error:
        return name, {
            "family": "axes",
            "status": "failed",
            "error": str(error),
            "seconds": time.monotonic() - start,
        }


def crossfit(kind, parameter, config, vectors, coordinates, test, folds):
    points = np.empty((len(vectors), 2))
    with threadpool_limits(limits=1):
        points[test] = predict(kind, parameter, config, vectors, coordinates, ~test, test)
        for fold in range(5):
            target = (~test) & (folds == fold)
            if target.any():
                train = (~test) & (folds != fold)
                points[target] = predict(
                    kind, parameter, config, vectors, coordinates, train, target
                )
    return points


def repel(points, config):
    center = points.mean(axis=0)
    scale = np.maximum(points.std(axis=0), 1)
    points = (points - center) / scale
    radius = config["repulsion_radius"]
    for _ in range(config["repulsion_iterations"]):
        pairs = KDTree(points).query_pairs(radius, output_type="ndarray")
        if not len(pairs):
            break
        delta = points[pairs[:, 0]] - points[pairs[:, 1]]
        distance = np.linalg.norm(delta, axis=1, keepdims=True)
        coincident = distance[:, 0] == 0
        delta[coincident] = [1e-6, 0]
        distance[coincident] = 1e-6
        force = delta / distance * (radius - distance) * 0.1
        shifts = np.zeros_like(points)
        degree = np.zeros(len(points))
        np.add.at(shifts, pairs[:, 0], force)
        np.add.at(shifts, pairs[:, 1], -force)
        np.add.at(degree, pairs[:, 0], 1)
        np.add.at(degree, pairs[:, 1], 1)
        points += shifts / np.maximum(degree[:, None], 1)
    return points * scale + center


def best(results, family, prefix=""):
    valid = [
        name
        for name, metrics in results.items()
        if name.startswith(prefix)
        and metrics["family"] == family
        and metrics["status"] == "ok"
        and metrics.get("cv_neighbor_overlap@10") is not None
    ]
    return max(valid, key=lambda name: results[name]["cv_neighbor_overlap@10"]) if valid else None


def representation(config, run, embedding, weighting, genres, membership, results):
    source = embedding if weighting == "uniform" else f"{embedding}_{weighting}"
    print(f"Starting {source}", flush=True)
    vectors = artist_vectors(config, run, embedding)
    if len(vectors) != membership.shape[1]:
        raise ValueError("Artist vector and catalog sizes differ")
    vectors = normalize(vectors)
    if weighting == "log_listeners":
        artists = pl.read_parquet(Path(config["input_run"]) / "artists.parquet").sort("item")
        weights = np.log(np.maximum(artists["listeners"].to_numpy(), 2))
        membership = membership @ sparse.diags(weights)
    elif weighting != "uniform":
        raise ValueError(f"Unknown member weighting: {weighting}")
    vectors = normalize(membership @ vectors)
    placed = (genres["members"].to_numpy() >= config.get("min_members", 3)) & (
        np.linalg.norm(vectors, axis=1) > 0
    )
    frame = genres.filter(placed)
    vectors = vectors[placed]
    np.save(run / f"{source}_genre_vectors.npy", vectors)
    coordinates = frame.select("x", "y").to_numpy().astype(float)
    test = frame["split"].to_numpy() == "test"
    folds = frame["fold"].to_numpy()
    totals = (
        (genres["split"] == "test").sum(),
        [
            genres.filter((pl.col("split") == "train") & (pl.col("fold") == f)).height
            for f in range(5)
        ],
    )
    jobs = []
    specs = {}
    for kind, parameters in [
        ("ridge", config["ridge_alpha"]),
        ("knn", config["knn_k"]),
        ("boost", config["boost_depth"]),
        ("ensemble", config["ensemble_alpha"]),
        ("shuffle", [1.0]),
    ]:
        for parameter in parameters:
            name = f"{source}_{kind}_{parameter}"
            specs[name] = (kind, parameter)
            if name not in results:
                jobs.append(
                    (name, kind, parameter, config, vectors, coordinates, test, folds, totals, run)
                )
    context = multiprocessing.get_context("spawn")
    with concurrent.futures.ProcessPoolExecutor(
        max_workers=config["workers"], mp_context=context
    ) as pool:
        for name, metrics in pool.map(axes_job, jobs):
            results[name] = {
                **metrics,
                "source": source,
                "embedding": embedding,
                "weighting": weighting,
                "placed": len(frame),
            }
            print(name, json.dumps(results[name]), flush=True)
            save_metrics(run, results)
    winner = best({name: results[name] for name in specs}, "axes")
    if winner is None:
        raise ValueError(f"No successful axes models for {source}")
    points = np.load(run / f"{winner}_coords.npy")
    repulsed = f"{winner}_repulsion"
    if config["repulsion_iterations"]:
        start = time.monotonic()
        try:
            shifted = repel(points.copy(), config)
            scores = evaluation_scores(shifted, coordinates, vectors, test, folds, *totals)
            results[repulsed] = {
                "family": "axes",
                "status": "ok",
                "source": source,
                "embedding": embedding,
                "weighting": weighting,
                "placed": len(frame),
                **scores,
                "seconds": time.monotonic() - start,
            }
            np.save(run / f"{repulsed}_coords.npy", shifted)
            print(repulsed, json.dumps(results[repulsed]), flush=True)
            if scores["cv_neighbor_overlap@10"] > results[winner]["cv_neighbor_overlap@10"]:
                winner, points = repulsed, shifted
        except Exception as error:
            results[repulsed] = {
                "family": "axes",
                "status": "failed",
                "source": source,
                "error": str(error),
            }
    for neighbors in config["umap_neighbors"]:
        for initialization in ["spectral", "axes"]:
            name = f"{source}_umap_{neighbors}_{initialization}"
            if name in results:
                continue
            start = time.monotonic()
            try:
                init = initialization
                if initialization == "axes":
                    init = StandardScaler().fit_transform(points).astype(np.float32)
                with threadpool_limits(limits=1):
                    islands = UMAP(
                        n_neighbors=neighbors,
                        min_dist=config["umap_min_dist"],
                        n_epochs=config["umap_epochs"],
                        metric="cosine",
                        init=init,
                        random_state=config["seed"],
                        n_jobs=1,
                        compatibility_layout=True,
                    ).fit_transform(vectors)
                scores = evaluation_scores(
                    islands, coordinates, vectors, test, folds, *totals, axes=False
                )
                results[name] = {
                    "family": "islands",
                    "status": "ok",
                    "source": source,
                    "embedding": embedding,
                    "weighting": weighting,
                    "placed": len(frame),
                    **scores,
                    "seconds": time.monotonic() - start,
                }
                np.save(run / f"{name}_coords.npy", islands)
            except Exception as error:
                results[name] = {
                    "family": "islands",
                    "status": "failed",
                    "source": source,
                    "error": str(error),
                    "seconds": time.monotonic() - start,
                }
            print(name, json.dumps(results[name]), flush=True)
            save_metrics(run, results)
    frame.select("genre", "split", "members").write_parquet(run / f"{source}_placed.parquet")


def save_metrics(run, results):
    (run / "layout_metrics.json").write_text(json.dumps(results, indent=2, allow_nan=False))


def export(run, genres, results, pending):
    winners = {family: best(results, family) for family in ["axes", "islands"]}
    if not all(winners.values()):
        raise ValueError("No successful layout for both families")
    output = genres.select("genre", "split", "members")
    for family, name in winners.items():
        frame = pl.read_parquet(run / f"{results[name]['source']}_placed.parquet")
        points = np.load(run / f"{name}_coords.npy")
        columns = ["x", "y"] if family == "axes" else ["island_x", "island_y"]
        frame = frame.select("genre").with_columns(
            pl.Series(columns[0], points[:, 0]), pl.Series(columns[1], points[:, 1])
        )
        output = output.join(frame, on="genre", how="left")
    output.filter(pl.col("x").is_not_null() | pl.col("island_x").is_not_null()).select(
        "genre", "split", "x", "y", "island_x", "island_y", "members"
    ).write_parquet(run / "genre_layout.parquet")
    (run / "layout_best.json").write_text(json.dumps(winners, indent=2))
    print("Best", json.dumps(winners), flush=True)
    if pending or (run / "layout_logged").exists():
        return
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    with Path("experiments/results.tsv").open("a") as stream:
        for name, metrics in results.items():
            row = [
                datetime.datetime.now(datetime.UTC).isoformat(),
                commit,
                run.name,
                name,
                json.dumps(metrics, separators=(",", ":")),
                "kept" if name in winners.values() else "discarded",
                "shared M2 holdout; selection on mean 5-fold train overlap",
            ]
            stream.write("\t".join(row) + "\n")
    (run / "layout_logged").touch()


def layout(config, run):
    genres, membership = inputs(config, run)
    path = run / "layout_metrics.json"
    results = json.loads(path.read_text()) if path.exists() else {}
    pending = []
    embeddings = list(config["representations"])
    if config.get("concat"):
        embeddings.append("concat")
    for embedding in embeddings:
        if embedding == "concat":
            candidates = {
                name: row
                for name, row in results.items()
                if row.get("embedding", "").startswith("als_")
            }
            winner = best(candidates, "axes")
            if winner is None:
                pending.append(embedding)
                continue
            config["concat_als"] = results[winner]["embedding"]
            (run / "layout_concat.json").write_text(
                json.dumps(
                    {
                        "als": config["concat_als"],
                        "selected_by": winner,
                        "cv_neighbor_overlap@10": results[winner]["cv_neighbor_overlap@10"],
                    },
                    indent=2,
                )
            )
        elif any(
            part != "tfidf" and not (Path(config["input_run"]) / f"{part}.npy").exists()
            for part in embedding.split("+")
        ):
            pending.append(embedding)
            continue
        for weighting in config["member_weighting"]:
            source = embedding if weighting == "uniform" else f"{embedding}_{weighting}"
            if (run / f"{source}_placed.parquet").exists():
                continue
            try:
                representation(config, run, embedding, weighting, genres, membership, results)
            except Exception as error:
                results[f"{source}_input"] = {
                    "family": "input",
                    "status": "failed",
                    "source": source,
                    "error": str(error),
                }
                print(source, str(error), flush=True)
            save_metrics(run, results)
    (run / "layout_pending.json").write_text(json.dumps(pending))
    export(run, genres, results, pending)
