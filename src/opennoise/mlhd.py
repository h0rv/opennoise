import argparse
import concurrent.futures
import hashlib
import json
import subprocess
import time
from array import array
from collections import Counter
from collections.abc import Iterable
from pathlib import Path

import numpy as np
import polars as pl
from scipy import sparse

from opennoise.evaluate import colistening, heldout_sets
from opennoise.tags import log

URL = "https://data.metabrainz.org/pub/musicbrainz/listenbrainz/mlhd/"
MEMBER_COMMAND = 'printf "@mlhd-user\\t%s\\n" "$TAR_FILENAME"; zstd -dc || exit; printf "\\n"'


def aggregate(stream: Iterable[bytes], artists: dict[bytes, int]):
    indices = array("i")
    values = array("f")
    indptr = array("q", [0])
    users = []
    seen = set()
    counts = Counter()
    stats = {"users_processed": 0, "listens_processed": 0, "matched_listens": 0}
    user = None

    def finish():
        if user is not None and counts:
            users.append(user)
            indices.extend(counts)
            values.extend(counts.values())
            indptr.append(len(indices))
        counts.clear()

    for line in stream:
        if line.startswith(b"@mlhd-user\t"):
            finish()
            user = Path(line.decode().strip().split("\t", 1)[1]).name.removesuffix(".txt.zst")
            if user in seen:
                raise ValueError(f"Duplicate MLHD user: {user}")
            seen.add(user)
            stats["users_processed"] += 1
            if stats["users_processed"] % 1000 == 0:
                print(json.dumps(stats), flush=True)
        elif line.strip():
            fields = line.rstrip(b"\n").split(b"\t")
            if user is None or len(fields) != 4 or not fields[0].isdigit():
                raise ValueError("Expected a user marker followed by four-column MLHD TSV")
            stats["listens_processed"] += 1
            item = artists.get(fields[1].lower())
            if item is not None:
                counts[item] += 1
                stats["matched_listens"] += 1
    finish()
    matrix = sparse.csr_matrix(
        (np.asarray(values), np.asarray(indices), np.asarray(indptr)),
        shape=(len(users), len(artists)),
    )
    matrix.sort_indices()
    stats.update(users_retained=len(users), interactions=matrix.nnz)
    return matrix, users, stats


def ingest(base, run, shard):
    frame = pl.read_parquet(base / "artists.parquet").sort("item")
    artists = {mbid.encode(): item for item, mbid in frame.select("item", "artist_mbid").rows()}
    name = f"mlhdplus-partial-{shard}.tar"
    with subprocess.Popen(["curl", "-fL", URL + name], stdout=subprocess.PIPE) as download:
        with subprocess.Popen(
            ["tar", "-xf", "-", "--to-command", MEMBER_COMMAND],
            stdin=download.stdout,
            stdout=subprocess.PIPE,
        ) as archive:
            if download.stdout is None or archive.stdout is None:
                raise RuntimeError("Missing archive pipe")
            download.stdout.close()
            matrix, users, stats = aggregate(archive.stdout, artists)
            if archive.wait() or download.wait():
                raise RuntimeError("MLHD download or decompression failed")
    if not stats["users_processed"] or not matrix.nnz:
        raise ValueError("Empty MLHD shard")
    sparse.save_npz(run / f"mlhd-{shard}.npz", matrix)
    (run / f"mlhd-{shard}-users.json").write_text(json.dumps(users))
    (run / f"mlhd-{shard}.json").write_text(json.dumps(stats | {"url": URL + name}, indent=2))
    print(json.dumps(stats), flush=True)


def weighted_rows(matrix):
    weighted = matrix.copy()
    weighted.data = np.log1p(weighted.data)
    idf = np.log1p(matrix.shape[1] / np.maximum(np.diff(matrix.indptr), 1))
    return (sparse.diags(idf) @ weighted).astype(np.float32).tocsr()


def similarities(lb, mlhd, weights, k):
    if any(not np.isfinite(weight) or weight < 0 for weight in weights):
        raise ValueError("MLHD weights must be finite and nonnegative")
    if lb.shape[1] != mlhd.shape[1] or not 0 < k < lb.shape[1]:
        raise ValueError("Expected aligned artist columns and 0 < k < artists")
    left, extra = weighted_rows(lb).T.tocsr(), weighted_rows(mlhd).T.tocsr()
    right, extra_right = left.T.tocsr(), extra.T.tocsr()
    n = left.shape[0]
    lb_norm = np.asarray(left.multiply(left).sum(axis=1)).ravel()
    mlhd_norm = np.asarray(extra.multiply(extra).sum(axis=1)).ravel()
    norms = {weight: np.sqrt(lb_norm + weight * mlhd_norm) for weight in weights}
    outputs = {
        weight: (np.empty((n, k), dtype=np.int32), np.empty((n, k), dtype=np.float32))
        for weight in weights
    }

    def batch(start):
        stop = min(start + 128, n)
        base = (left[start:stop] @ right).toarray()
        added = (extra[start:stop] @ extra_right).toarray()
        results = {}
        for weight in weights:
            norm = norms[weight]
            scores = base + weight * added
            scores /= np.maximum(norm[start:stop, None] * norm[None, :], 1e-24)
            scores[np.arange(stop - start), np.arange(start, stop)] = -np.inf
            selected = np.argpartition(-scores, k - 1, axis=1)[:, :k]
            values = np.take_along_axis(scores, selected, axis=1)
            order = np.argsort(-values, axis=1, kind="stable")
            results[weight] = (
                np.take_along_axis(selected, order, axis=1),
                np.take_along_axis(values, order, axis=1),
            )
        return start, stop, results

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        for start, stop, results in pool.map(batch, range(0, n, 128)):
            for weight, (ids, scores) in results.items():
                outputs[weight][0][start:stop] = ids
                outputs[weight][1][start:stop] = scores
            if start % 12800 == 0:
                print(f"neighbors {stop}/{n}", flush=True)
    return outputs


def partition_users(size, seed):
    if size < 2:
        raise ValueError("Need at least two held-out users")
    order = np.random.default_rng(seed).permutation(size)
    cut = size // 2
    return order[:cut], order[cut:]


def load_graph(path, n):
    frame = pl.read_parquet(path)
    return sparse.csr_matrix(
        (frame["score"].to_numpy().clip(0), (frame["item"], frame["neighbor"])), shape=(n, n)
    )


def experiment(base, run, shards, weights, seed):
    output = run / "experiment.json"
    if output.exists():
        raise ValueError("Experiment already evaluated; use a fresh run directory")
    if len(set(shards)) != len(shards) or not shards:
        raise ValueError("Expected distinct MLHD shards")
    if len(set(weights)) != len(weights) or not weights or min(weights) <= 0:
        raise ValueError("Expected distinct positive MLHD weights")
    lb = sparse.load_npz(base / "train.npz")
    mlhd = sparse.vstack([sparse.load_npz(run / f"mlhd-{shard}.npz") for shard in shards]).tocsr()
    users = [
        user
        for shard in shards
        for user in json.loads((run / f"mlhd-{shard}-users.json").read_text())
    ]
    if len(users) != len(set(users)) or len(users) != mlhd.shape[0]:
        raise ValueError("Duplicate or misaligned MLHD users")
    n = lb.shape[1]
    sets = heldout_sets(base, seed)
    validation_ids, test_ids = partition_users(len(sets), seed)
    validation = [sets[i] for i in validation_ids]
    baseline = load_graph(base / "tfidf.parquet", n)
    reproduction = colistening(baseline, sets)
    print("baseline_reproduction", json.dumps(reproduction), flush=True)
    expected = json.loads((base / "metrics.json").read_text())["tfidf"]
    for metric in ["recall@50", "ndcg@50"]:
        if not np.isclose(reproduction[metric], expected[metric], atol=1e-12, rtol=0):
            raise ValueError(f"Baseline mismatch: {metric}")
    coverage: dict[str, int | float] = {
        "artists": n,
        "lb_users": lb.shape[0],
        "mlhd_users": mlhd.shape[0],
    }
    for source, matrix in [("lb", lb), ("mlhd", mlhd)]:
        listeners = matrix.getnnz(axis=0)
        for threshold in [1, 5]:
            count = int(np.sum(listeners >= threshold))
            coverage[f"{source}_artists_ge{threshold}"] = count
            coverage[f"{source}_share_ge{threshold}"] = count / n
    shard_stats = [json.loads((run / f"mlhd-{shard}.json").read_text()) for shard in shards]
    for key in ["users_processed", "listens_processed", "matched_listens"]:
        coverage[key] = sum(stats[key] for stats in shard_stats)
    validation_metrics = {"0": colistening(baseline, validation)}
    start = time.monotonic()
    outputs = similarities(lb, mlhd, weights, 50)
    build_seconds = time.monotonic() - start
    for weight, (ids, scores) in outputs.items():
        frame = pl.DataFrame(
            {
                "item": np.repeat(np.arange(n, dtype=np.int32), 50),
                "neighbor": ids.ravel(),
                "score": scores.ravel(),
            }
        )
        frame.write_parquet(run / f"weight-{weight:g}.parquet")
        graph = sparse.csr_matrix(
            (scores.clip(0).ravel(), ids.ravel(), np.arange(n + 1) * 50), shape=(n, n)
        )
        validation_metrics[f"{weight:g}"] = colistening(graph, validation)
        print("validation", weight, json.dumps(validation_metrics[f"{weight:g}"]), flush=True)
    selected = max(validation_metrics, key=lambda key: validation_metrics[key]["ndcg@50"])
    (run / "selection.json").write_text(
        json.dumps(
            {
                "selected_weight": selected,
                "validation": validation_metrics,
                "validation_users": validation_ids.tolist(),
                "test_users": test_ids.tolist(),
            },
            indent=2,
        )
    )
    test = [sets[i] for i in test_ids]
    test_metrics = {"0": colistening(baseline, test)}
    if selected != "0":
        graph = load_graph(run / f"weight-{selected}.parquet", n)
        test_metrics[selected] = colistening(graph, test)
    hashes = {}
    for name in ["train.npz", "artists.parquet", "heldout.parquet", "tfidf.parquet"]:
        with (base / name).open("rb") as stream:
            hashes[name] = hashlib.file_digest(stream, "sha256").hexdigest()
    result = {
        "base": str(base),
        "seed": seed,
        "shards": shard_stats,
        "weights": weights,
        "weight_semantics": "MLHD Gram contribution; extra TF-IDF user rows scaled by sqrt(weight)",
        "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "baseline_sha256": hashes,
        "baseline_reproduction": reproduction,
        "coverage": coverage,
        "validation": validation_metrics,
        "selected_weight": selected,
        "test": test_metrics,
        "build_seconds": build_seconds,
    }
    output.write_text(json.dumps(result, indent=2))
    for split, metrics in [("validation", validation_metrics), ("test", test_metrics)]:
        for weight, values in metrics.items():
            log(
                run,
                f"mlhd_weight_{weight}_{split}",
                values | {"weight": float(weight)},
                weight == selected,
                note=f"two streamed MLHD+ partial shards {','.join(shards)}; seed {seed}; "
                "50% LB heldout users validation; select nDCG@50; test baseline+selected only",
            )
    log(run, "mlhd_coverage", coverage, note="M1-aligned distinct training-user listeners")
    print(json.dumps(result, indent=2), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=["ingest", "experiment"])
    parser.add_argument("--enable", action="store_true")
    parser.add_argument("--base", type=Path, default=Path("runs/1f242e47ed38"))
    parser.add_argument("--run", type=Path, default=Path("runs/mlhd"))
    parser.add_argument("--shard", choices=list("0123456789abcdef"), default="0")
    parser.add_argument("--shards", nargs="+", default=["0", "1"])
    parser.add_argument("--weights", type=float, nargs="+", default=[0.1, 0.3, 1.0, 3.0])
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    if not args.enable:
        parser.error("MLHD is optional and disabled by default; pass --enable to opt in")
    args.run.mkdir(parents=True, exist_ok=True)
    if args.stage == "ingest":
        ingest(args.base, args.run, args.shard)
    else:
        experiment(args.base, args.run, args.shards, args.weights, args.seed)


if __name__ == "__main__":
    main()
