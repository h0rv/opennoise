import concurrent.futures
import datetime
import json
import subprocess
import time
import urllib.parse
import urllib.request
from pathlib import Path

import numpy as np
import polars as pl
from scipy import sparse

from opennoise.metrics import overlap, ranking

ALGORITHM = (
    "session_based_days_1800_session_300_contribution_3_threshold_10_limit_100_filter_True_skip_30"
)
PROBES = [
    "Aphex Twin",
    "Boards of Canada",
    "Four Tet",
    "Radiohead",
    "Burial",
    "Slowdive",
    "My Bloody Valentine",
    "Kendrick Lamar",
    "Taylor Swift",
    "Miles Davis",
    "Metallica",
    "Björk",
    "Autechre",
    "Grouper",
    "Basic Channel",
    "Skee Mask",
    "Ichiko Aoba",
]


def labs_reference(artists, config):
    cache = Path("data/labs")
    cache.mkdir(exist_ok=True)
    rng = np.random.default_rng(config["seed"])
    strata = np.array_split(np.arange(len(artists)), 3)
    sample = np.concatenate(
        [rng.choice(s, min(len(s), config["labs_sample"] // 3), replace=False) for s in strata]
    )
    mbids = artists["artist_mbid"].to_list()

    def fetch(index):
        mbid = mbids[index]
        path = cache / f"{mbid}.json"
        try:
            if path.exists():
                response = json.loads(path.read_text())
            else:
                query = urllib.parse.urlencode({"artist_mbids": mbid, "algorithm": ALGORITHM})
                with urllib.request.urlopen(
                    f"https://labs.api.listenbrainz.org/similar-artists/json?{query}", timeout=60
                ) as result:
                    response = json.load(result)
                path.write_text(json.dumps(response))
            return (
                int(index),
                [row["artist_mbid"] for row in sorted(response, key=lambda row: -row["score"])],
                None,
            )
        except Exception as error:
            return int(index), [], str(error)

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(fetch, sample))
    return results


def heldout_sets(run, seed):
    data = pl.read_parquet(run / "heldout.parquet")
    rng = np.random.default_rng(seed)
    sets = []
    for group in data.partition_by("user", maintain_order=True):
        items = rng.permutation(group["item"].to_numpy())
        cut = len(items) // 2
        sets.append((items[:cut], items[cut:]))
    return sets


def colistening(graph, sets):
    n = graph.shape[0]
    recalls, ndcgs = [], []
    for visible, hidden in sets:
        scores = np.asarray(graph[visible].sum(axis=0)).ravel()
        scores[visible] = -np.inf
        k = min(50, n - len(visible))
        candidates = np.flatnonzero(scores > 0)
        if len(candidates) > k:
            candidates = candidates[np.argpartition(-scores[candidates], k - 1)[:k]]
        predicted = candidates[np.argsort(-scores[candidates], kind="stable")]
        recall, ndcg = ranking(predicted, hidden, 50)
        recalls.append(recall)
        ndcgs.append(ndcg)
    return {
        "recall@50": float(np.mean(recalls)) if recalls else None,
        "ndcg@50": float(np.mean(ndcgs)) if ndcgs else None,
        "eval_users": len(sets),
    }


def evaluate(config, run):
    output = run / "metrics.json"
    if output.exists() and output.stat().st_mtime >= (run / "build.json").stat().st_mtime:
        print(output.read_text())
        return
    artists = pl.read_parquet(run / "artists.parquet")
    mbids = artists["artist_mbid"].to_list()
    names = artists["artist_name"].to_list()
    references = labs_reference(artists, config)
    (run / "labs.json").write_text(json.dumps(references))
    sets = heldout_sets(run, config["seed"])
    timings = json.loads((run / "build.json").read_text())
    results = {}
    probes = []
    for method, timing in timings.items():
        start = time.monotonic()
        if timing["status"] != "ok":
            results[method] = timing
            continue
        data = pl.read_parquet(run / f"{method}.parquet")
        graph = sparse.csr_matrix(
            (
                np.maximum(data["score"].to_numpy(), 0),
                (data["item"].to_numpy(), data["neighbor"].to_numpy()),
            ),
            shape=(len(artists), len(artists)),
        )
        neighbors = data["neighbor"].to_numpy().reshape(len(artists), -1)
        metrics = colistening(graph, sets)
        for k in [10, 50]:
            values = [
                overlap([mbids[i] for i in neighbors[index]], reference, k)
                for index, reference, error in references
                if reference and not error
            ]
            metrics[f"overlap@{k}"] = float(np.mean(values)) if values else None
        metrics["labs_requested"] = len(references)
        metrics["labs_nonempty"] = sum(bool(r) for _, r, _ in references)
        metrics["labs_errors"] = sum(e is not None for _, _, e in references)
        metrics["artists"] = len(artists)
        metrics["build_seconds"] = timing["seconds"]
        metrics["eval_seconds"] = time.monotonic() - start
        results[method] = metrics
        probes.append(method)
        for probe in PROBES:
            matches = [i for i, name in enumerate(names) if name.casefold() == probe.casefold()]
            top = ", ".join(names[i] for i in neighbors[matches[0], :10]) if matches else "absent"
            probes.append(f"{probe}: {top}")
        print(method, json.dumps(metrics), flush=True)
    valid = {m: r for m, r in results.items() if r.get("ndcg@50") is not None}
    if not valid:
        raise ValueError("No evaluated models")
    best = max(valid, key=lambda m: valid[m]["ndcg@50"])
    (run / "best.json").write_text(json.dumps({"method": best, "metrics": valid[best]}, indent=2))
    (run / "probes.txt").write_text("\n".join(probes) + "\n")
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    with Path("experiments/results.tsv").open("a") as stream:
        for method, metrics in results.items():
            row = [
                datetime.datetime.now(datetime.UTC).isoformat(),
                commit,
                run.name,
                method,
                json.dumps(metrics, separators=(",", ":")),
                "kept" if method == best else "discarded",
                "train-only catalog; 10% users held out; unweighted visible-item voting",
            ]
            stream.write("\t".join(row) + "\n")
    output.write_text(json.dumps(results, indent=2))
