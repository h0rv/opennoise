"""Test curated tracklists without changing the shipped listening graph."""

import argparse
import json
import tomllib
from pathlib import Path

import igraph as ig
import leidenalg as la
import numpy as np
import polars as pl
from scipy import sparse

from opennoise.generalization import cluster_scores, similarity_score
from opennoise.genres import graph_matrix, heldout_genres
from opennoise.metrics import best_cluster, sealed

BASE = Path("runs/1f242e47ed38")
SPECIAL_ARTISTS = ["Various Artists", "[unknown]", "[no artist]", "[anonymous]"]
VARIANTS = {"dj-mix": "DJ-mix", "compilation": "Compilation"}


def table(root: Path, name: str, **columns: tuple[int, type[pl.DataType]]) -> pl.LazyFrame:
    return pl.scan_csv(
        root / name,
        separator="\t",
        has_header=False,
        quote_char=None,
        infer_schema=False,
        null_values="\\N",
    ).select(
        pl.col(f"column_{position - 1}").cast(dtype).alias(column)
        for column, (position, dtype) in columns.items()
    )


def tracklists(root: Path, artists: pl.DataFrame) -> pl.DataFrame:
    types = table(
        root, "release_group_secondary_type", type_id=(1, pl.UInt32), kind=(2, pl.String)
    ).filter(pl.col("kind").is_in(list(VARIANTS.values())))
    groups = table(
        root, "release_group_secondary_type_join", group=(1, pl.UInt32), type_id=(2, pl.UInt32)
    )
    releases = table(
        root, "release", release=(1, pl.UInt32), group=(5, pl.UInt32), status=(6, pl.UInt32)
    )
    statuses = table(root, "release_status", status=(1, pl.UInt32), name_=(2, pl.String))
    media = table(root, "medium", medium=(1, pl.UInt32), release=(2, pl.UInt32))
    tracks = table(
        root, "track", medium=(4, pl.UInt32), credit=(8, pl.UInt32), data_track=(12, pl.String)
    )
    credits = table(root, "artist_credit_name", credit=(1, pl.UInt32), artist=(3, pl.UInt32))
    mbids = table(root, "artist", artist=(1, pl.UInt32), artist_mbid=(2, pl.String))

    editions = (
        groups.join(types, on="type_id")
        .group_by("group")
        .agg(
            pl.when((pl.col("kind") == "DJ-mix").any())
            .then(pl.lit("DJ-mix"))
            .otherwise(pl.lit("Compilation"))
            .alias("kind")
        )
        .join(releases, on="group")
        .join(statuses.filter(pl.col("name_") == "Official").select("status"), on="status")
        .group_by("group", "kind")
        .agg(pl.col("release").min())
    )
    items = artists.filter(~pl.col("artist_name").is_in(SPECIAL_ARTISTS)).lazy()
    credit_items = credits.join(mbids, on="artist").join(items, on="artist_mbid")
    return (
        tracks.filter(pl.col("data_track") == "f")
        .join(media.join(editions, on="release"), on="medium")
        .join(credit_items, on="credit")
        .group_by("group", "kind")
        .agg(pl.col("item").unique().sort())
        .filter(pl.col("item").list.len().is_between(3, 60))
        .unique(subset=["kind", "item"])
        .select("kind", "item")
        .sort(["kind", "item"])
        .collect(engine="streaming")
    )


def playlist_edges(lists: pl.DataFrame, base: pl.DataFrame, n: int) -> pl.DataFrame:
    sizes = lists["item"].list.len().to_numpy()
    item = lists["item"].explode().to_numpy()
    column = np.repeat(np.arange(len(lists), dtype=np.int32), sizes)
    incidence = sparse.csr_matrix(
        (np.ones(len(item), dtype=np.float32), (item, column)), shape=(n, len(lists))
    )
    weighted = incidence.multiply(1 / np.sqrt(sizes.astype(np.float32) - 1)).tocsr()
    norm = np.sqrt(np.asarray(weighted.power(2).sum(axis=1)).ravel())
    norm[norm == 0] = 1
    weighted = weighted.multiply((1 / norm)[:, None]).tocsr()

    neighbors = base["neighbor"].to_numpy().reshape(n, 50).copy()
    scores = base["score"].to_numpy().reshape(n, 50).copy()
    for start in range(0, n, 1024):
        end = min(start + 1024, n)
        common = incidence[start:end] @ incidence.T
        common.data = np.asarray(common.data >= 2, dtype=np.float32)
        common.eliminate_zeros()
        boosted = (weighted[start:end] @ weighted.T).multiply(common).tocsr()
        for j in np.flatnonzero(np.diff(boosted.indptr)):
            i = start + int(j)
            row = boosted.getrow(int(j))
            keep = row.indices != i
            if not keep.any():
                continue
            ids = np.union1d(neighbors[i], row.indices[keep])
            values = np.zeros(len(ids), dtype=np.float32)
            values[np.searchsorted(ids, neighbors[i])] = scores[i]
            values[np.searchsorted(ids, row.indices[keep])] += 0.25 * row.data[keep]
            top = np.lexsort((ids, -values))[:50]
            neighbors[i], scores[i] = ids[top], values[top]
    return base.with_columns(neighbor=neighbors.ravel(), score=scores.ravel())


def score(run: Path) -> dict:
    config = tomllib.loads(Path("configs/m2.toml").read_text())
    variant = next(v for v in config["variants"] if v["name"] == "fine_k20")
    graph, _ = graph_matrix({"m1": str(run)}, variant)
    edges = sparse.triu(graph, k=1).tocoo()
    network = ig.Graph(n=graph.shape[0], edges=np.column_stack((edges.row, edges.col)))
    artists = pl.read_parquet(run / "artists.parquet").sort("item")
    ranked = pl.read_parquet(run / "tfidf.parquet")
    memberships, genres, assignments = [], [], []
    offset = 0
    for level, resolution in enumerate(variant["resolutions"]):
        print(run.name, "clustering at", resolution, flush=True)
        partition = la.find_partition(
            network,
            la.RBConfigurationVertexPartition,
            weights=edges.data,
            resolution_parameter=resolution,
            seed=config["seed"],
            n_iterations=2,
        )
        labels = np.array(partition.membership)
        assignments.append(labels)
        memberships.append(
            artists.select(artist="artist_mbid", genre=labels + offset, score=pl.lit(1))
        )
        genres.append(pl.DataFrame({"id": range(offset, offset + len(partition)), "level": level}))
        offset += len(partition)
    hidden = heldout_genres(config)
    groups = pl.read_parquet("data/m2/labels.parquet").filter(pl.col("genre").is_in(hidden))
    overlap = [
        best_cluster(group["item"].to_numpy(), assignments)[0]
        for group in groups.partition_by("genre")
    ]

    gen = tomllib.loads(Path("configs/gen.toml").read_text())
    reference = pl.read_parquet(Path(gen["reference"]) / "wikidata.parquet").filter(
        pl.col("artist_mbid").map_elements(sealed, return_dtype=pl.Boolean)
    )
    result = {
        "every_noise": {
            "genres": len(overlap),
            "genre_match": np.mean(np.asarray(overlap) >= 0.2).item(),
            "median_jaccard": np.median(overlap).item(),
        }
    }
    for name, subset in (
        ("sealed", reference),
        ("sealed_independent", reference.filter(~pl.col("enao_linked"))),
    ):
        result[name] = {
            "clusters": cluster_scores(
                subset, pl.concat(memberships), pl.concat(genres), seed=gen["seed"]
            ),
            "neighbors": similarity_score(subset, artists, ranked, seed=gen["seed"]),
        }
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("variant", choices=["baseline", *VARIANTS])
    parser.add_argument(
        "--tables", type=Path, help="directory of extracted MusicBrainz core tables"
    )
    args = parser.parse_args()
    work = Path("runs/playlist-signal")
    work.mkdir(parents=True, exist_ok=True)
    run = BASE
    coverage = {}
    if args.variant != "baseline":
        if args.tables is None:
            parser.error("--tables is required for a playlist variant")
        artists = pl.read_parquet(BASE / "artists.parquet")
        lists = tracklists(args.tables, artists).filter(pl.col("kind") == VARIANTS[args.variant])
        if lists.is_empty():
            raise ValueError(f"No usable {args.variant} tracklists")
        coverage = {
            "lists": len(lists),
            "artists_in_lists": lists["item"].explode().n_unique(),
        }
        print(args.variant, coverage, flush=True)
        run = work / args.variant
        run.mkdir(exist_ok=True)
        target = run / "artists.parquet"
        if not target.exists():
            target.symlink_to((BASE / "artists.parquet").resolve())
        edges = pl.read_parquet(BASE / "tfidf.parquet")
        boosted = playlist_edges(lists, edges, len(artists))
        coverage["artists_with_reordered_top50"] = boosted.filter(
            pl.col("neighbor") != edges["neighbor"]
        )["item"].n_unique()
        boosted.write_parquet(run / "tfidf.parquet")
    path = work / f"{args.variant}.json"
    path.write_text(json.dumps({"coverage": coverage, **score(run)}, indent=2) + "\n")
    print(path.read_text(), end="")


if __name__ == "__main__":
    main()
