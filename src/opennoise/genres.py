import datetime
import json
import subprocess
import time
from pathlib import Path

import igraph as ig
import leidenalg as la
import numpy as np
import polars as pl
from scipy import sparse

from opennoise.metrics import average_precision, best_cluster, name_agreement, ranking


def eligible_genres(config, labels):
    final = pl.read_parquet("data/m2/map.parquet")["genre"].to_list()
    return (
        labels.group_by("genre")
        .len()
        .filter((pl.col("len") >= config["min_artists"]) & pl.col("genre").is_in(final))["genre"]
        .sort()
        .to_list()
    )


def heldout_genres(config, eligible=None, rng=None):
    if eligible is None:
        eligible = eligible_genres(config, pl.read_parquet("data/m2/labels.parquet"))
    if rng is None:
        rng = np.random.default_rng(config["seed"])
    return set(rng.choice(eligible, int(len(eligible) * config["genre_holdout"]), replace=False))


def split_labels(config):
    labels = pl.read_parquet("data/m2/labels.parquet")
    eligible = eligible_genres(config, labels)
    rng = np.random.default_rng(config["seed"])
    heldout = heldout_genres(config, eligible, rng)
    train, hidden, truth = {}, {}, {}
    for group in labels.partition_by("genre"):
        name = group["genre"][0]
        if name not in eligible:
            continue
        items = np.sort(group["item"].to_numpy())
        truth[name] = items
        if name not in heldout:
            items = rng.permutation(items)
            cut = max(1, int(len(items) * config["artist_holdout"]))
            hidden[name], train[name] = items[:cut], items[cut:]
    return train, hidden, {name: truth[name] for name in sorted(heldout)}, truth


def graph_matrix(config, variant):
    data = pl.read_parquet(Path(config["m1"]) / "tfidf.parquet")
    n = pl.read_parquet(Path(config["m1"]) / "artists.parquet").height
    k = variant["k"]
    indices = data["neighbor"].to_numpy().reshape(n, 50)[:, :k]
    scores = data["score"].to_numpy().reshape(n, 50)[:, :k]
    graph = sparse.csr_matrix(
        (np.maximum(scores.ravel(), 0), (np.repeat(np.arange(n), k), indices.ravel())), shape=(n, n)
    )
    graph.eliminate_zeros()
    graph = ((graph + graph.T) * 0.5).tocsr()
    total = np.asarray(graph.sum(axis=1)).ravel()
    transition = sparse.diags(1 / np.maximum(total, 1e-12)) @ graph
    return graph, transition


def update_top(indices, values, scores, offset):
    candidates = np.concatenate([values, scores], axis=1)
    ids = np.concatenate(
        [indices, np.broadcast_to(np.arange(scores.shape[1]) + offset, scores.shape)], axis=1
    )
    keep = np.argpartition(-candidates, values.shape[1] - 1, axis=1)[:, : values.shape[1]]
    return np.take_along_axis(ids, keep, axis=1), np.take_along_axis(candidates, keep, axis=1)


def membership(transition, train, hidden, truth, variant, run):
    names = sorted(train)
    n = transition.shape[0]
    top_ids = np.full((n, 10), -1, dtype=np.int32)
    top_values = np.zeros((n, 10), dtype=np.float32)
    eval_ids = np.full((n, 5), -1, dtype=np.int32)
    eval_values = np.zeros((n, 5), dtype=np.float32)
    recalls, aps, probe_members = [], [], {}
    for start in range(0, len(names), 32):
        batch = names[start : start + 32]
        seeds = np.zeros((n, len(batch)), dtype=np.float32)
        for j, name in enumerate(batch):
            seeds[train[name], j] = 1
        scores = transition @ seeds
        if variant["hops"] == 2:
            scores = 0.5 * scores + 0.5 * (transition @ scores)
        top_ids, top_values = update_top(top_ids, top_values, scores, start)
        for j, name in enumerate(batch):
            if name in ["shoegaze", "intelligent dance music", "drill"]:
                probe_members[name] = np.argsort(-scores[:, j])[:15].tolist()
            scores[train[name], j] = 0
            candidates = np.flatnonzero(scores[:, j] > 0)
            predicted = candidates[np.argsort(-scores[candidates, j], kind="stable")]
            recalls.append(ranking(predicted, hidden[name], len(truth[name]))[0])
            aps.append(average_precision(predicted, hidden[name]))
        eval_ids, eval_values = update_top(eval_ids, eval_values, scores, start)
    hits, artist_truth = {}, {}
    for j, name in enumerate(names):
        for item in hidden[name]:
            artist_truth.setdefault(int(item), set()).add(j)
    for item, relevant in artist_truth.items():
        hits[item] = bool(set(eval_ids[item][eval_values[item] > 0]) & relevant)
    order = np.argsort(-top_values, axis=1)
    top_ids = np.take_along_axis(top_ids, order, axis=1)
    top_values = np.take_along_axis(top_values, order, axis=1)
    np.savez_compressed(run / "predictions.npz", ids=top_ids, scores=top_values)
    (run / "member_probes.json").write_text(json.dumps(probe_members))
    return (
        names,
        {
            "member_recall": float(np.mean(recalls)),
            "member_ap": float(np.mean(aps)),
            "artist_hit@5": float(np.mean(list(hits.values()))),
            "train_genres": len(names),
            "eval_artists": len(hits),
        },
        top_ids,
    )


def tag_matrix(n):
    data = pl.read_parquet("data/m2/tags.parquet")
    names = data.select("tag").unique().sort("tag").with_row_index("tag_id")
    data = data.join(names, on="tag")
    matrix = sparse.csr_matrix(
        (
            np.ones(len(data), dtype=np.float32),
            (data["item"].to_numpy(), data["tag_id"].to_numpy()),
        ),
        shape=(n, len(names)),
    )
    return matrix, names["tag"].to_list()


def name_clusters(labels, previous, tags, tag_names, config, offset, parent_offset):
    n_clusters = int(labels.max()) + 1
    sizes = np.bincount(labels)
    indicator = sparse.csr_matrix(
        (np.ones(len(labels)), (labels, np.arange(len(labels)))), shape=(n_clusters, len(labels))
    )
    counts = (indicator @ tags).tocsr()
    if previous is None:
        parent_counts = sparse.csr_matrix(tags.sum(axis=0))
        parents = np.zeros(n_clusters, dtype=int)
        parent_sizes = np.array([len(labels)])
    else:
        pairs = sparse.csr_matrix(
            (np.ones(len(labels)), (labels, previous)), shape=(n_clusters, int(previous.max()) + 1)
        )
        parents = np.asarray(pairs.argmax(axis=1)).ravel()
        parent_indicator = sparse.csr_matrix(
            (np.ones(len(labels)), (previous, np.arange(len(labels))))
        )
        parent_counts = (parent_indicator @ tags).tocsr()
        parent_sizes = np.bincount(previous)
    rows = []
    for cluster in range(n_clusters):
        row = counts.getrow(cluster)
        select = row.data >= config["min_tag_support"]
        candidates, support = row.indices[select], row.data[select]
        name = f"unnamed {offset + cluster}"
        parent = int(parents[cluster])
        if len(candidates):
            denominator = parent_counts[parent, candidates].toarray().ravel()
            context_size = parent_sizes[parent]
            if previous is not None:
                outside = np.flatnonzero((labels == cluster) & (previous != parent))
                if len(outside):
                    denominator += np.asarray(tags[outside][:, candidates].sum(axis=0)).ravel()
                    context_size += len(outside)
            lift = (support / sizes[cluster]) / np.maximum(denominator / context_size, 1e-12)
            best = np.lexsort((candidates, -support, -lift))[0]
            name = tag_names[candidates[best]]
        rows.append(
            (
                offset + cluster,
                name,
                int(sizes[cluster]),
                None if previous is None else parent_offset + parent,
            )
        )
    return rows


def discover(graph, variant, config, run, initial, train_count):
    edges = sparse.triu(graph, k=1).tocoo()
    network = ig.Graph(n=graph.shape[0], edges=np.column_stack([edges.row, edges.col]))
    weights = edges.data
    tags, tag_names = tag_matrix(graph.shape[0])
    assignments, rows, offsets = [], [], []
    offset, parent_offset = train_count, 0
    for level, resolution in enumerate(variant["resolutions"]):
        partition = la.find_partition(
            network,
            la.RBConfigurationVertexPartition,
            weights=weights,
            resolution_parameter=resolution,
            seed=config["seed"],
            n_iterations=2,
            initial_membership=initial if variant["guided"] else None,
        )
        labels = np.array(partition.membership, dtype=np.int32)
        named = name_clusters(
            labels,
            assignments[-1] if assignments else None,
            tags,
            tag_names,
            config,
            offset,
            parent_offset,
        )
        rows.extend([(id_, name, level, parent, size) for id_, name, size, parent in named])
        assignments.append(labels)
        offsets.append(offset)
        parent_offset, offset = offset, offset + len(partition)
        print(run.name, "resolution", resolution, "clusters", len(partition), flush=True)
    np.savez_compressed(run / "clusters.npz", **{str(i): x for i, x in enumerate(assignments)})
    return rows, assignments, offsets


def build_variant(config, variant, run):
    start = time.monotonic()
    train, hidden, heldout, truth = split_labels(config)
    graph, transition = graph_matrix(config, variant)
    names, metrics, initial = membership(transition, train, hidden, truth, variant, run)
    initial = initial[:, 0]
    initial[initial < 0] = len(names)
    _, initial = np.unique(initial, return_inverse=True)
    rows, assignments, offsets = discover(graph, variant, config, run, initial, len(names))
    predictions = np.load(run / "predictions.npz")
    ids, scores = predictions["ids"], predictions["scores"]
    artist = np.repeat(np.arange(graph.shape[0]), ids.shape[1])
    keep = (scores.ravel() > 0) & (ids.ravel() >= 0)
    memberships = pl.DataFrame(
        {"item": artist[keep], "genre": ids.ravel()[keep], "score": scores.ravel()[keep]}
    )
    sizes = memberships.group_by("genre").len()
    size_map = dict(sizes.iter_rows())
    rows = [(i, name, -1, None, size_map.get(i, 0)) for i, name in enumerate(names)] + rows
    genres = pl.DataFrame(
        rows,
        schema=[
            ("id", pl.Int64),
            ("name", pl.String),
            ("level", pl.Int64),
            ("parent", pl.Int64),
            ("size", pl.Int64),
        ],
        orient="row",
    )
    discovered = []
    for labels, offset in zip(assignments, offsets, strict=True):
        discovered.append(
            pl.DataFrame(
                {
                    "item": np.arange(len(labels)),
                    "genre": labels.astype(np.int64) + offset,
                    "score": np.ones(len(labels), dtype=np.float32),
                }
            )
        )
    memberships = pl.concat([memberships, *discovered], how="vertical_relaxed")
    artists = pl.read_parquet(Path(config["m1"]) / "artists.parquet")
    memberships = (
        memberships.join(artists.select("item", "artist_mbid"), on="item")
        .rename({"artist_mbid": "artist"})
        .select("artist", "genre", "score")
    )
    memberships.write_parquet(run / "memberships.parquet")
    genres.write_parquet(run / "genres.parquet")
    matches = {}
    genre_names = dict(genres.select("id", "name").iter_rows())
    for name, items in heldout.items():
        value, level, cluster = best_cluster(items, assignments)
        genre_id = offsets[level] + cluster
        matches[name] = {
            "jaccard": value,
            "cluster": genre_id,
            "name": genre_names[genre_id],
            "level": level,
        }
    matched = [(name, match) for name, match in matches.items() if match["jaccard"] >= 0.2]
    agreement = [name_agreement(name, match["name"]) for name, match in matched]
    metrics.update(
        {
            "genre_match": len(matched) / len(heldout),
            "median_jaccard": float(np.median([m["jaccard"] for m in matches.values()])),
            "name_exact": float(np.mean([a[0] for a in agreement])) if agreement else 0,
            "name_token_jaccard": float(np.mean([a[1] for a in agreement])) if agreement else 0,
            "heldout_genres": len(heldout),
            "matched_genres": len(matched),
            "clusters": len(genres) - len(names),
            "seconds": time.monotonic() - start,
        }
    )
    (run / "matches.json").write_text(json.dumps(matches, indent=2))
    write_probes(run, artists, genres, ids, scores, names, matches, assignments, offsets, truth)
    (run / "metrics.json").write_text(json.dumps(metrics, indent=2))


def write_probes(run, artists, genres, ids, scores, names, matches, assignments, offsets, truth):
    artist_names = artists["artist_name"].to_list()
    genre_names = dict(genres.select("id", "name").iter_rows())
    lines = []
    for probe in [
        "Aphex Twin",
        "Boards of Canada",
        "Taylor Swift",
        "Burial",
        "Slowdive",
        "Kendrick Lamar",
    ]:
        item = next(
            (i for i, name in enumerate(artist_names) if name.casefold() == probe.casefold()), None
        )
        if item is None:
            lines.append(f"{probe}: absent")
            continue
        labels = [
            f"{names[g]} ({score:.3f})"
            for g, score in zip(ids[item, :5], scores[item, :5], strict=True)
            if g >= 0 and score > 0
        ]
        clusters = [
            genre_names[offset + level[item]]
            for offset, level in zip(offsets, assignments, strict=True)
        ]
        lines.append(f"{probe}: train: {'; '.join(labels)} | clusters: {'; '.join(clusters)}")
    member_probes = json.loads((run / "member_probes.json").read_text())
    for probe in ["shoegaze", "idm", "drill"]:
        genre = "intelligent dance music" if probe == "idm" else probe
        if genre in names:
            members, status = member_probes[genre], "train"
        elif genre in matches:
            match = matches[genre]
            label = assignments[match["level"]]
            members = np.flatnonzero(label == match["cluster"] - offsets[match["level"]])[:15]
            status = f"held-out; cluster {match['name']}; Jaccard {match['jaccard']:.3f}"
        else:
            members, status = [], "ineligible or absent"
        lines.append(f"{probe} ({genre}) [{status}]: {'; '.join(artist_names[i] for i in members)}")
    (run / "probes.txt").write_text("\n".join(lines) + "\n")


def build_genres(config, run):
    for variant in config["variants"]:
        path = run / variant["name"]
        path.mkdir(exist_ok=True)
        if (path / "metrics.json").exists():
            continue
        start = time.monotonic()
        try:
            build_variant(config, variant, path)
        except Exception as error:
            failure = {"status": "failed", "error": str(error), "seconds": time.monotonic() - start}
            (path / "failure.json").write_text(json.dumps(failure))
            commit = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
            now = datetime.datetime.now(datetime.UTC).isoformat()
            with Path("experiments/results.tsv").open("a") as stream:
                stream.write(
                    "\t".join(
                        [
                            now,
                            commit,
                            f"{run.name}/{path.name}/failed-{now}",
                            "m2",
                            json.dumps(failure),
                            "discarded",
                            "build failed",
                        ]
                    )
                    + "\n"
                )
            print(variant["name"], "failed", repr(error), flush=True)


def evaluate_genres(config, run):
    results = {}
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    table = Path("experiments/results.tsv")
    existing = table.read_text()
    for variant in config["variants"]:
        path = run / variant["name"]
        target = path / "metrics.json"
        metrics = json.loads((target if target.exists() else path / "failure.json").read_text())
        results[variant["name"]] = metrics
    valid = {name: metrics for name, metrics in results.items() if "genre_match" in metrics}
    best = (
        max(valid, key=lambda name: (valid[name]["genre_match"], valid[name]["member_ap"]))
        if valid
        else None
    )
    for name, metrics in results.items():
        key = f"{run.name}/{name}"
        if metrics.get("status") != "failed" and f"\t{key}\t" not in existing:
            with table.open("a") as stream:
                stream.write(
                    "\t".join(
                        [
                            datetime.datetime.now(datetime.UTC).isoformat(),
                            commit,
                            key,
                            "m2",
                            json.dumps(metrics, separators=(",", ":")),
                            "kept" if name == best else "discarded",
                            "20% genres unseen; 20% train members hidden; naming from MB tags",
                        ]
                    )
                    + "\n"
                )
    (run / "metrics.json").write_text(json.dumps(results, indent=2))
    (run / "best.json").write_text(json.dumps({"run": best}, indent=2))
    print(json.dumps(results, indent=2))
    if best:
        print((run / best / "probes.txt").read_text())
