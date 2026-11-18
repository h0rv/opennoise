import json
import math
from pathlib import Path

import numpy as np
import polars as pl
from scipy import sparse


def blend_relations(graph, config):
    weight = config.get("weight", 0)
    if not math.isfinite(weight) or weight < 0:
        raise ValueError("Relation weight must be finite and nonnegative")
    if weight == 0:
        return graph
    edges = pl.read_parquet(config["path"])
    if "types" in config:
        edges = edges.filter(pl.col("type").is_in(config["types"]))
    rows, cols = edges["item"].to_numpy(), edges["neighbor"].to_numpy()
    if edges.height and (
        min(rows.min(), cols.min()) < 0 or max(rows.max(), cols.max()) >= graph.shape[0]
    ):
        raise ValueError("Relation items outside M1 graph")
    adjacency = sparse.csr_matrix((np.ones(len(rows)), (rows, cols)), shape=graph.shape)
    adjacency = adjacency.maximum(adjacency.T)
    adjacency.setdiag(0)
    adjacency.eliminate_zeros()
    adjacency.data[:] = weight
    return (graph + adjacency).tocsr()


def ingest_relations(config, read_table):
    target = Path(config["relations"]["path"])
    if target.exists():
        return
    artists = read_table("artist", [0, 1], ["mb_artist", "artist_mbid"])
    items = pl.read_parquet(Path(config["m1"]) / "artists.parquet")
    mapped = artists.join(items.select("artist_mbid", "item"), on="artist_mbid")
    types = read_table(
        "link_type", [0, 3, 4, 5, 6], ["type_id", "type_mbid", "entity0", "entity1", "type"]
    )
    types = types.filter((pl.col("entity0") == "artist") & (pl.col("entity1") == "artist"))
    links = read_table("link", [0, 1], ["link", "type_id"])
    relations = read_table("l_artist_artist", [1, 2, 3], ["link", "artist0", "artist1"])
    relations = relations.join(links, on="link").join(types, on="type_id")
    total = relations.group_by("type_id").len().rename({"len": "dump_rows"})
    edges = (
        relations.join(mapped.select(pl.col("mb_artist").alias("artist0"), "item"), on="artist0")
        .join(
            mapped.select(pl.col("mb_artist").alias("artist1"), pl.col("item").alias("neighbor")),
            on="artist1",
        )
        .filter(pl.col("item") != pl.col("neighbor"))
        .select("item", "neighbor", "type_id", "type_mbid", "type")
        .unique()
        .sort("type_id", "item", "neighbor")
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    edges.write_parquet(target)
    counts = edges.group_by("type_id").len().rename({"len": "mapped_pairs"})
    summary = types.join(total, on="type_id", how="left").join(counts, on="type_id", how="left")
    summary = summary.select("type_id", "type_mbid", "type", "dump_rows", "mapped_pairs").fill_null(
        0
    )
    covered = pl.concat([edges["item"], edges["neighbor"]]).n_unique()
    result = {
        "m1": config["m1"],
        "artists": items.height,
        "covered_artists": covered,
        "coverage": covered / items.height if items.height else 0,
        "typed_pairs": edges.height,
        "types": summary.sort("mapped_pairs", descending=True).to_dicts(),
    }
    target.with_suffix(".json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result), flush=True)
