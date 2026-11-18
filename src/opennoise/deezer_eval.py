import hashlib
import json
import tomllib
from collections import Counter
from pathlib import Path

import numpy as np
import polars as pl
from scipy import sparse

from opennoise.deezer import ROOT, albums, cached, catalog, ingest, name_key, related, seeds
from opennoise.generalization import cluster_scores
from opennoise.genres import graph_matrix, partitions, split_labels
from opennoise.metrics import best_cluster, sealed


def signals(path: Path, n: int, top: int, mid: int) -> tuple[sparse.csr_matrix, np.ndarray, dict]:
    sample = json.loads((ROOT / "sample.json").read_text())
    if (sample["top"], sample["mid"]) != (top, mid) or sample["artists_sha256"] != hashlib.sha256(
        path.read_bytes()
    ).hexdigest():
        raise ValueError("Deezer sample differs from config; run ingest first")
    matched = {int(id_): item for id_, item in sample["matched"].items()}
    responses = cached()
    artists = catalog(path)
    eligible_ids = {record["id"] for record in responses["genre"]["data"]} - {0}
    rows, cols, weights = [], [], []
    genres = np.zeros(n, dtype=np.int32)
    for id_, item in matched.items():
        seen = {item}
        for rank, record in enumerate(responses[related(id_)]["data"]):
            target = matched.get(record["id"])
            if target is None and (entry := artists.get(name_key(record["name"]))) is not None:
                target = entry.item
            if target is not None and target not in seen:
                rows.append(item)
                cols.append(target)
                weights.append(1 / np.log2(rank + 2))
                seen.add(target)
        counts = Counter(
            record["genre_id"]
            for record in responses[albums(id_)]["data"]
            if record["genre_id"] in eligible_ids
        )
        if counts:
            genres[item] = counts.most_common(1)[0][0]
    directed = sparse.csr_matrix((weights, (rows, cols)), shape=(n, n))
    sources = {a.item for a in seeds(artists, top, mid)[:top]}
    coverage = {
        "seeds": sample["seeds"],
        "matched": len(matched),
        "top_matched": len(sources & set(matched.values())),
        "mid_matched": len(matched) - len(sources & set(matched.values())),
        "directed_edges": directed.nnz,
        "sources_with_edges": len(set(rows)),
        "artists_in_graph": len(set(rows) | set(cols)),
        "artists_with_genres": int(np.count_nonzero(genres)),
        "genres_observed": len(set(genres) - {0}),
    }
    return directed, genres, coverage


def wikidata_reference(path):
    frame = pl.read_parquet(path).filter(
        pl.col("artist_mbid").map_elements(sealed, return_dtype=pl.Boolean)
    )
    return hashlib.sha256(path.read_bytes()).hexdigest(), {
        "sealed": frame,
        "sealed_independent": frame.filter(~pl.col("enao_linked")),
    }


def grade(assignments, artists, heldout, reference):
    overlaps = [best_cluster(items, assignments)[0] for items in heldout.values()]
    offset = 0
    memberships, levels = [], []
    for i, labels in enumerate(assignments):
        labels = labels + offset
        levels.append(pl.DataFrame({"id": np.unique(labels), "level": i}))
        memberships.append(
            artists.select(pl.col("artist_mbid").alias("artist")).with_columns(
                pl.Series("genre", labels), pl.lit(1.0).alias("score")
            )
        )
        offset = int(labels.max()) + 1
    genres = pl.concat(levels)
    members = pl.concat(memberships)
    return {
        "every_noise": {
            "matched": sum(value >= 0.2 for value in overlaps),
            "genres": len(overlaps),
            "median_jaccard": float(np.median(overlaps)),
        },
        **{name: cluster_scores(frame, members, genres) for name, frame in reference.items()},
    }


def genre_partition(genres):
    _, labels = np.unique(
        np.where(genres > 0, genres, genres.max() + 1 + np.arange(len(genres))),
        return_inverse=True,
    )
    return labels


def normalize_blend(listening, directed):
    total = np.asarray(directed.sum(axis=1)).ravel()
    listen_total = np.asarray(listening.sum(axis=1)).ravel()
    scaled = sparse.diags(listen_total / np.maximum(total, 1e-12)) @ directed
    return ((scaled + scaled.T) * 0.5).tocsr()


def boost_genres(graph, genres):
    edges = graph.tocoo(copy=True)
    shared = (genres[edges.row] > 0) & (genres[edges.row] == genres[edges.col])
    edges.data[shared] *= 1.25
    return edges.tocsr()


def evaluate(study, config, path, run):
    fine = next(v for v in config["variants"] if v["name"] == "fine_k20")
    artists = pl.read_parquet(path).sort("item")
    _, _, heldout, _ = split_labels(config)
    digest, reference = wikidata_reference(Path(study["wikidata"]))
    listening, _ = graph_matrix(config, fine)

    directed, genres, coverage = signals(path, len(artists), study["top"], study["mid"])
    related_graph = ((directed + directed.T) * 0.5).tocsr()
    blended = listening + 0.25 * normalize_blend(listening, directed)
    signal = (related_graph.getnnz(axis=1) > 0) | (genres > 0)
    heldout_artists = np.unique(np.concatenate(list(heldout.values())))
    coverage["every_noise_heldout_artists"] = len(heldout_artists)
    coverage["every_noise_heldout_artists_with_signal"] = int(signal[heldout_artists].sum())
    for name, frame in reference.items():
        covered = artists.join(frame.select("artist_mbid").unique(), on="artist_mbid")["item"]
        coverage[f"{name}_artists"] = len(covered)
        coverage[f"{name}_artists_with_signal"] = int(signal[covered.to_numpy()].sum())
    result = {
        "reference_sha256": digest,
        "coverage": coverage,
        "deezer_genres": grade([genre_partition(genres)], artists, heldout, reference),
    }
    for name, graph in {
        "listening": listening,
        "deezer_related": related_graph,
        "deezer_related_and_genres": boost_genres(related_graph, genres),
        "listening_and_deezer_genres": boost_genres(listening, genres),
        "listening_and_deezer_related": blended,
        "listening_and_deezer_related_and_genres": boost_genres(blended, genres),
    }.items():
        assignments = [
            np.array(part.membership, dtype=np.int32)
            for _, part in partitions(graph, fine, config["seed"])
        ]
        result[name] = grade(assignments, artists, heldout, reference)
        print(name, json.dumps(result[name]), flush=True)
    (run / "metrics.json").write_text(json.dumps(result, indent=2))


def execute(stage, config, run):
    m2 = tomllib.loads(Path(config["m2_config"]).read_text())
    path = Path(m2["m1"]) / "artists.parquet"
    if stage == "ingest":
        ingest(path, config["top"], config["mid"])
    elif stage == "eval":
        evaluate(config, m2, path, run)
    else:
        raise ValueError("Deezer research supports ingest and eval only")
