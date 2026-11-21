import argparse
import json
import pickle
import tomllib
from collections.abc import Iterator
from pathlib import Path

import numpy as np
import polars as pl

from opennoise import catalog, identities, named, names
from opennoise.reference import MapParser


def label_key(name: str) -> str:
    return names.key(names.canonical(name))


def reference_names(root: Path) -> set[str]:
    parser = MapParser()
    parser.feed((root / "map.html").read_text())
    return {row[0] for row in parser.rows} | {
        row["genre"] for row in json.loads((root / "enao.json").read_text())
    }


def candidates(
    credits: pl.DataFrame,
    identity: pl.DataFrame,
    redirects: dict[str, str],
    eligible: set[str],
    excluded: set[str],
    min_members: int,
) -> pl.DataFrame:
    unambiguous = (
        identity.with_columns(artist=pl.col("artist_mbid").replace(redirects))
        .group_by("discogs_id")
        .agg(pl.col("artist").unique())
        .filter(pl.col("artist").list.len() == 1)
        .explode("artist")
        .filter(pl.col("artist").is_in(sorted(eligible)))
    )
    allowed = [
        tag for tag in credits["tag"].unique() if (key := label_key(tag)) and key not in excluded
    ]
    return (
        credits.join(unambiguous, on="discogs_id")
        .with_columns(score=pl.col("weight") / (1 + pl.col("weight").sum().over("discogs_id")))
        .filter((pl.col("weight") >= 2) & pl.col("tag").is_in(allowed))
        .group_by("tag", "artist")
        .agg(pl.col("score").max())
        .filter(pl.len().over("tag") >= min_members)
        .sort("tag", "artist")
    )


def published_edges(root: Path, genres: list[dict]) -> Iterator[tuple[str, str, float]]:
    for genre in genres:
        id_ = genre["id"]
        detail = json.loads((root / "genres" / f"{id_}.json").read_bytes())
        for entry in detail["members"]:
            yield id_, entry["artist"]["id"], entry["score"]


def build(
    root: Path,
    tags: Path,
    references: Path,
    layout: Path,
    *,
    non_music: list[str],
    min_listeners: int,
    min_members: int,
) -> dict[str, dict]:
    manifest = json.loads((root / "manifest.json").read_text())
    if manifest["membership"] is None or manifest["genre_similarity"] is None:
        raise ValueError(
            "Discogs styles require a model catalog with memberships and related genres"
        )
    genres = json.loads((root / manifest["genres"]).read_text())
    search = json.loads((root / manifest["search"]).read_text())
    known = reference_names(references) | set(non_music)
    known.update(label for row in genres for label in [row["name"], *row["aliases"]])
    artists = pl.read_parquet(layout / "artists.parquet").sort("item")
    if artists["item"].to_list() != list(range(len(artists))):
        raise ValueError("Layout vectors require contiguous artist items")
    eligible = {
        row["id"]
        for row in search
        if row["kind"] == "artist" and (row["listeners"] or 0) >= min_listeners
    }
    edges = candidates(
        pl.read_parquet(tags / "discogs_masters.parquet"),
        pl.read_parquet(tags / "identity.parquet"),
        manifest["artist_redirects"],
        eligible.intersection(artists["artist_mbid"]),
        {label_key(name) for name in known},
        min_members,
    )
    summaries = {
        mbid: json.loads((root / "artists" / f"{mbid}.json").read_bytes())["artist"]
        for mbid in edges["artist"].unique()
    }
    edges = edges.filter(
        pl.col("artist").is_in(
            sorted(
                mbid
                for mbid, artist in summaries.items()
                if artist["positions"]["axes"] is not None
            )
        )
    ).filter(pl.len().over("tag") >= min_members)
    ids = {
        tag: identities.stable_id(f"discogs-style:{tag}", tag)
        for tag in edges["tag"].unique().sort()
    }
    if not ids:
        return {}
    edges = edges.select(genre=pl.col("tag").replace_strict(ids), artist="artist", score="score")
    placed = {("artist", mbid): artist["positions"] for mbid, artist in summaries.items()}
    with (layout / "sonic_model.pkl").open("rb") as stream:
        model = pickle.load(stream)
    with np.load(layout / "sonic_state.npz") as state:
        vectors = state["vectors"]
        if len(vectors) != len(artists):
            raise ValueError("Layout vectors do not match the artist table")
        catalog.group_coordinates(
            ids.values(), edges, {id_: id_ for id_ in ids.values()}, placed, artists, state, model
        )
    additions = {}
    for tag, id_ in ids.items():
        positions = placed.get(("genre", id_))
        if positions is None or positions["axes"] is None:
            continue
        members = [
            {"artist": summaries[mbid], "score": score}
            for mbid, score in edges.filter(pl.col("genre") == id_)
            .sort(["score", "artist"], descending=[True, False])
            .select("artist", "score")
            .iter_rows()
        ]
        additions[id_] = {
            "genre": {
                "id": id_,
                "name": tag,
                "aliases": [],
                "parent_id": None,
                "member_count": len(members),
                "positions": positions,
                "color": None,
            },
            "members": members,
        }
    if not additions:
        return {}
    edges = edges.filter(pl.col("genre").is_in(sorted(additions))).cast({"score": pl.Float64})
    existing = pl.DataFrame(published_edges(root, genres), schema=edges.schema, orient="row")
    related = catalog.related_genres(
        {row["id"]: row for row in genres}
        | {i: detail["genre"] for i, detail in additions.items()},
        pl.concat([existing, edges]),
        artists,
        vectors,
        queries=additions.keys(),
    )
    for i, detail in additions.items():
        detail["related"] = related[i]
    return additions


def main() -> None:
    parser = argparse.ArgumentParser(description="Add repeat-credited Discogs styles to a catalog")
    parser.add_argument("release", type=Path)
    parser.add_argument("release_id")
    parser.add_argument("tags", type=Path)
    parser.add_argument("layout", type=Path)
    parser.add_argument("--references", type=Path, default=Path("data/m2"))
    parser.add_argument("--config", type=Path, default=Path("configs/m3.toml"))
    args = parser.parse_args()
    config = tomllib.loads(args.config.read_text())
    additions = build(
        args.release,
        args.tags,
        args.references,
        args.layout,
        non_music=config["non_music"],
        min_listeners=config["min_listeners"],
        min_members=config["min_members"],
    )
    print(
        json.dumps({"styles": [detail["genre"]["name"] for detail in additions.values()]}),
        flush=True,
    )
    if additions:
        print(
            json.dumps(
                named.release(
                    args.release, args.release_id, duplicates_only=True, additions=additions
                )
            )
        )


if __name__ == "__main__":
    main()
