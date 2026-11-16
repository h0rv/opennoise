import concurrent.futures
import json
import time

import numpy as np
import polars as pl
from implicit.als import AlternatingLeastSquares
from scipy import sparse
from threadpoolctl import threadpool_limits


def normalize(matrix):
    norms = np.sqrt(np.asarray(matrix.multiply(matrix).sum(axis=1)).ravel())
    return sparse.diags(1 / np.maximum(norms, 1e-12)) @ matrix


def prepare(config, run):
    if (run / "train.npz").exists():
        return sparse.load_npz(run / "train.npz")
    data = pl.scan_parquet("data/listens.parquet")
    data = (
        data.group_by("user", "artist_mbid")
        .agg(pl.col("count").sum(), pl.col("artist_name").first())
        .collect(engine="streaming")
    )
    users = data.select("user").unique().sort("user")
    rng = np.random.default_rng(config["seed"])
    test_ids = rng.choice(
        users["user"].to_numpy(), size=int(len(users) * config["test_fraction"]), replace=False
    )
    test = data.filter(pl.col("user").is_in(test_ids))
    data = data.filter(~pl.col("user").is_in(test_ids))
    artists = (
        data.group_by("artist_mbid")
        .agg(pl.len().alias("listeners"), pl.col("artist_name").first())
        .filter(pl.col("listeners") >= config["min_listeners"])
        .sort(["listeners", "artist_mbid"], descending=[True, False])
        .with_row_index("item")
    )
    artists.write_parquet(run / "artists.parquet")
    data = data.join(artists.select("artist_mbid", "item"), on="artist_mbid")
    counts = data.group_by("user").len().filter(pl.col("len") >= config["min_artists"])
    users = counts.select("user").sort("user").with_row_index("row")
    data = data.join(users, on="user")
    matrix = sparse.csr_matrix(
        (
            data["count"].to_numpy().astype(np.float32),
            (data["row"].to_numpy(), data["item"].to_numpy()),
        ),
        shape=(len(users), len(artists)),
    )
    test = test.join(artists.select("artist_mbid", "item"), on="artist_mbid")
    eligible = test.group_by("user").len().filter(pl.col("len") >= config["min_artists"])
    test.join(eligible.select("user"), on="user").select("user", "item").sort(
        ["user", "item"]
    ).write_parquet(run / "heldout.parquet")
    sparse.save_npz(run / "train.npz", matrix)
    print(
        json.dumps(
            {"users": matrix.shape[0], "artists": matrix.shape[1], "interactions": matrix.nnz}
        ),
        flush=True,
    )
    return matrix


def neighbors(vectors, k):
    n = vectors.shape[0]
    transpose = vectors.T.tocsr() if sparse.issparse(vectors) else vectors.T
    ids = np.empty((n, k), dtype=np.int32)
    weights = np.empty((n, k), dtype=np.float32)

    def batch(start):
        stop = min(start + 128, n)
        scores = vectors[start:stop] @ transpose
        if sparse.issparse(scores):
            scores = scores.toarray()
        scores[np.arange(stop - start), np.arange(start, stop)] = -np.inf
        selected = np.argpartition(-scores, k - 1, axis=1)[:, :k]
        values = np.take_along_axis(scores, selected, axis=1)
        order = np.argsort(-values, axis=1, kind="stable")
        return (
            start,
            stop,
            np.take_along_axis(selected, order, axis=1),
            np.take_along_axis(values, order, axis=1),
        )

    if sparse.issparse(vectors):
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            for start, stop, indices, values in pool.map(batch, range(0, n, 128)):
                ids[start:stop] = indices
                weights[start:stop] = values
    else:
        for start in range(0, n, 128):
            _, stop, indices, values = batch(start)
            ids[start:stop] = indices
            weights[start:stop] = values
    return ids, weights


def save_graph(run, name, vectors, k):
    ids, weights = neighbors(vectors, k)
    pl.DataFrame(
        {
            "item": np.repeat(np.arange(len(ids), dtype=np.int32), k),
            "neighbor": ids.ravel(),
            "score": weights.ravel(),
        }
    ).write_parquet(run / f"{name}.parquet")


def build(config, run):
    matrix = prepare(config, run)
    timings = {}
    timing_path = run / "build.json"
    if timing_path.exists():
        timings = json.loads(timing_path.read_text())
    variants = [("tfidf", None)] + [(f"als_{i}", p) for i, p in enumerate(config["als"])]
    for name, params in variants:
        if (run / f"{name}.parquet").exists():
            continue
        start = time.monotonic()
        try:
            weighted = matrix.copy()
            weighted.data = np.log1p(weighted.data)
            if params is None:
                idf = np.log1p(matrix.shape[1] / np.maximum(np.diff(matrix.indptr), 1))
                vectors = normalize((sparse.diags(idf) @ weighted).T.tocsr())
            else:
                with threadpool_limits(limits=1, user_api="blas"):
                    model = AlternatingLeastSquares(
                        **params, random_state=config["seed"], num_threads=8
                    )
                    model.fit(weighted, show_progress=False)
                vectors = model.item_factors
                vectors /= np.maximum(np.linalg.norm(vectors, axis=1, keepdims=True), 1e-12)
                np.save(run / f"{name}.npy", vectors)
            save_graph(run, name, vectors, config["neighbors"])
            timings[name] = {"seconds": time.monotonic() - start, "status": "ok"}
        except Exception as error:
            timings[name] = {
                "seconds": time.monotonic() - start,
                "status": "failed",
                "error": str(error),
            }
        timing_path.write_text(json.dumps(timings, indent=2))
        print(name, timings[name], flush=True)
