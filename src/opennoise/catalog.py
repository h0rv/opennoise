import hashlib
import json
import pickle
import re
import time
from pathlib import Path

import numpy as np
import polars as pl
from scipy import sparse
from sklearn.preprocessing import normalize
from threadpoolctl import threadpool_limits

from opennoise import grouping, identities, micro, names, sonic, tags
from opennoise.names import write


def coordinates(config):
    empty = {"axes": None, "islands": None}
    if not config.get("layout"):
        return {}, empty
    root = Path(config["layout"])
    frame = pl.read_parquet(root / "positions.parquet")
    if frame.select("kind", "id").n_unique() != len(frame):
        raise ValueError("Duplicate layout identity")
    result = {}
    for kind, id_, x, y, u, v in frame.select(
        "kind", "id", "x", "y", "island_x", "island_y"
    ).iter_rows():
        point = {}
        for family, a, b in [("axes", x, y), ("islands", u, v)]:
            if (a is None) != (b is None) or (a is not None and not (0 <= a <= 1 and 0 <= b <= 1)):
                raise ValueError("Invalid layout coordinates")
            point[family] = None if a is None else {"x": a, "y": b}
        result[kind, id_] = point
    return result, json.loads((root / "layouts.json").read_text())


def hierarchy(rows, retained):
    parents = {r["id"]: r["parent"] for r in rows}
    result = {}
    for i in retained:
        parent, seen = parents[i], {i}
        while parent is not None:
            if parent in seen or parent not in parents:
                raise ValueError("Invalid source genre hierarchy")
            seen.add(parent)
            if parent in retained:
                break
            parent = parents[parent]
        result[i] = parent
    for i in result:
        parent, seen = result[i], {i}
        while parent is not None:
            if parent in seen:
                raise ValueError("Cyclic genre hierarchy")
            seen.add(parent)
            parent = result[parent]
    return result


def group_coordinates(ids, memberships, public, placed, artists, state, model):
    ids = list(ids)
    if not ids:
        return
    edges = memberships.filter(pl.col("genre").is_in(list(ids)) & (pl.col("score") > 0))
    indexed = edges.join(
        artists.select("artist_mbid", "item"), left_on="artist", right_on="artist_mbid"
    )
    matrix = sparse.csr_matrix(
        (
            indexed["score"].to_numpy(),
            (
                indexed["genre"]
                .replace_strict(dict(zip(ids, range(len(ids)), strict=True)))
                .to_numpy(),
                indexed["item"].to_numpy(),
            ),
        ),
        shape=(len(ids), len(artists)),
    )
    with threadpool_limits(limits=1):
        points, mask, _ = sonic.place(model, matrix, state["vectors"], int(state["min_members"]))
    for id_, (x, y) in zip(np.asarray(ids)[mask], points, strict=True):
        placed.setdefault(("genre", public[id_]), {"axes": None, "islands": None})["axes"] = {
            "x": float(x),
            "y": float(y),
        }
    island_points = pl.DataFrame(
        [
            (i, p["islands"]["x"], p["islands"]["y"])
            for (kind, i), p in placed.items()
            if kind == "artist" and p["islands"] is not None
        ],
        schema={"artist": pl.String, "x": pl.Float64, "y": pl.Float64},
        orient="row",
    )
    island_centers = (
        edges.join(island_points, on="artist")
        .group_by("genre")
        .agg(
            *[
                ((pl.col(c) * pl.col("score")).sum() / pl.col("score").sum()).alias(c)
                for c in ["x", "y"]
            ]
        )
    )
    for i, x, y in island_centers.select("genre", "x", "y").iter_rows():
        placed.setdefault(("genre", public[i]), {"axes": None, "islands": None})["islands"] = {
            "x": x,
            "y": y,
        }


def tables(config):
    path = Path(config["export"])
    found = pl.read_parquet(path / "genres.parquet"), pl.read_parquet(path / "memberships.parquet")
    return micro.release(Path(config["micro"]), *found) if "micro" in config else found


def related_genres(catalog, memberships, artists, vectors):
    ids = sorted(catalog, key=lambda i: catalog[i]["id"])
    result = {i: [] for i in ids}
    if not ids:
        return result
    edges = memberships.join(
        artists.select("artist_mbid", "item"), left_on="artist", right_on="artist_mbid"
    )
    matrix = sparse.csr_matrix(
        (
            edges["score"].to_numpy(),
            (
                edges["genre"]
                .replace_strict(dict(zip(ids, range(len(ids)), strict=True)))
                .to_numpy(),
                edges["item"].to_numpy(),
            ),
        ),
        shape=(len(ids), len(artists)),
    )
    with threadpool_limits(limits=1):
        centers = normalize(matrix @ vectors)
        targets = np.array(
            [
                n
                for n, i in enumerate(ids)
                if " · " not in catalog[i]["name"] and np.any(centers[n])
            ],
            dtype=int,
        )
        for start in range(0, len(ids), 256):
            scores = np.clip(centers[start : start + 256] @ centers[targets].T, 0, 1)
            for offset, neighbors in enumerate(
                np.argsort(-scores, axis=1, kind="stable")[:, :11].tolist()
            ):
                i = ids[start + offset]
                result[i] = [
                    {"id": catalog[ids[targets[n]]]["id"], "score": float(scores[offset, n])}
                    for n in neighbors
                    if ids[targets[n]] != i and scores[offset, n] > 0
                ][:10]
    return result


def export(config, run):
    start = time.monotonic()
    m1 = Path(config["m1"])
    similarity = Path(config.get("similarity", m1 / "tfidf.parquet"))
    artists = pl.read_parquet(m1 / "artists.parquet").sort("item")
    redirects_path = m1 / "artist_redirects.json"
    aliases_path = m1 / "artist_aliases.json"
    artist_aliases = json.loads(aliases_path.read_text()) if aliases_path.exists() else {}
    artist_ids = set(artists["artist_mbid"])
    artist_redirects = (
        {
            old: target
            for old, target in json.loads(redirects_path.read_text()).items()
            if target in artist_ids
        }
        if redirects_path.exists()
        else {}
    )
    if artists["item"].n_unique() != len(artists) or artists["artist_mbid"].n_unique() != len(
        artists
    ):
        raise ValueError("Duplicate artist identity")
    if (
        not artists["artist_mbid"]
        .str.contains(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
        .all()
        or artists["artist_mbid"].null_count()
    ):
        raise ValueError("Public artist IDs must be lowercase MBIDs")
    genres, memberships = tables(config)
    if genres["id"].n_unique() != len(genres):
        raise ValueError("Duplicate local genre ID")
    all_rows = genres.to_dicts()
    rows = [
        r
        for r in all_rows
        if r["name"]
        and r["name"].strip()
        and not re.fullmatch(r"unnamed \d+", r["name"], re.IGNORECASE)
    ]
    retained = {r["id"] for r in rows}
    parents = hierarchy(all_rows, retained)
    if not set(memberships["genre"]) <= set(genres["id"]):
        raise ValueError("Unknown membership genre")
    memberships = memberships.filter(pl.col("genre").is_in(sorted(retained)))
    if not set(memberships["artist"]) <= set(artists["artist_mbid"]):
        raise ValueError("Unknown membership artist")
    if (
        memberships.select("artist", "genre").n_unique() != len(memberships)
        or memberships["score"].null_count()
        or not memberships["score"].is_finite().all()
        or not memberships["score"].is_between(0, 1).all()
    ):
        raise ValueError("Invalid membership strengths")
    members = {
        i: group["artist"].sort().to_list()
        for (i,), group in memberships.partition_by("genre", as_dict=True).items()
    }
    records, keys = [], {}
    for row in rows:
        if row["level"] == -1:
            scope, key, ids = "supervised", "enao:" + row["name"], []
        else:
            scope = config["levels"][row["level"]]
            ids = members.get(row["id"], [])
            key = "cluster:" + scope + ":" + hashlib.sha256("\n".join(ids).encode()).hexdigest()
        keys[row["id"]] = key
        records.append({"key": key, "scope": scope, "name": row["name"], "members": ids})
    registry = Path(config["registry"])
    previous_groups = []
    if (config.get("group_siblings") or config.get("group_globally")) and registry.exists():
        previous_groups = [
            {k: r[k] for k in ["key", "scope", "name", "members"]}
            for r in json.loads(registry.read_text())["genres"]
            if r["active"] and r["scope"] == "group"
        ]
    assigned = identities.assign(registry, records + previous_groups, config["identity_jaccard"])
    public = {i: assigned[key]["id"] for i, key in keys.items()}
    groups, global_groups, global_keys = {}, {}, {}
    if config.get("group_siblings"):
        memberships, added, group_keys, groups = grouping.siblings(
            rows, parents, memberships, public
        )
        records.extend(added)
        keys.update(group_keys)
    if config.get("group_globally"):
        memberships, added, global_keys, global_groups = grouping.global_names(
            rows, parents, memberships, keys
        )
        records.extend(added)
        keys.update(global_keys)
    if config.get("group_siblings") or config.get("group_globally"):
        assigned = identities.assign(registry, records, config["identity_jaccard"])
        public = {i: assigned[key]["id"] for i, key in keys.items()}
        retained = set(public)
        for group in groups.get("largest", []):
            group["id"] = public[group.pop("local_id")]
    target = run / "release"
    mapping = {str(i): public[i] for i in sorted(public)}
    if target.exists():
        return
    stage = run / "release.building"
    readability = (
        grouping.readable(rows, parents, memberships, artists, public)
        if config.get("readable_names")
        else {}
    )
    if config.get("group_globally") and config.get("vocabulary"):
        memberships, _, _, alias_groups = grouping.global_names(
            rows,
            parents,
            memberships,
            keys,
            grouping.aliases(pl.read_parquet(config["vocabulary"])),
        )
        global_groups["aliases"] = alias_groups
    stage.mkdir()
    (stage / "artists").mkdir()
    (stage / "genres").mkdir()
    positions = {"axes": None, "islands": None}
    placed, layouts = coordinates(config)
    if config.get("layout") and global_keys:
        with (Path(config["layout"]) / "sonic_model.pkl").open("rb") as stream:
            model = pickle.load(stream)
        with np.load(Path(config["layout"]) / "sonic_state.npz") as state:
            group_coordinates(global_keys, memberships, public, placed, artists, state, model)
    if "disambiguation" not in artists.columns:
        artists = artists.with_columns(pl.lit(None, dtype=pl.String).alias("disambiguation"))
    summaries = {
        mbid: {
            "id": mbid,
            "name": name,
            "disambiguation": disambiguation,
            "listeners": listeners,
            "positions": placed.get(("artist", mbid), positions),
            "color": None,
        }
        for _, mbid, listeners, name, disambiguation in artists.select(
            "item", "artist_mbid", "listeners", "artist_name", "disambiguation"
        ).iter_rows()
    }
    edges = memberships.with_columns(
        pl.col("genre").replace_strict(public, return_dtype=pl.String).alias("genre_id")
    )
    artist_genres = {}
    for group in (
        edges.sort(["artist", "score", "genre_id"], descending=[False, True, False])
        .group_by("artist", maintain_order=True)
        .agg("genre_id", "score")
        .iter_rows()
    ):
        mbid, ids, scores = group
        artist_genres[mbid] = [{"id": i, "score": s} for i, s in zip(ids, scores, strict=True)]
    counts = dict(memberships.group_by("genre").len().iter_rows())
    catalog: dict = {
        r["id"]: {
            "id": public[r["id"]],
            "name": r["name"],
            "aliases": sorted(
                (set(assigned[keys[r["id"]]]["aliases"]) | set(r.get("aliases", []))) - {r["name"]}
            ),
            "parent_id": public[parents[r["id"]]] if parents[r["id"]] is not None else None,
            "member_count": counts.get(r["id"], 0),
            "positions": placed.get(("genre", public[r["id"]]), positions),
            "color": None,
        }
        for r in rows
    }
    grouped = (
        memberships.sort(["genre", "score", "artist"], descending=[False, True, False])
        .group_by("genre", maintain_order=True)
        .agg("artist", "score")
    )
    if config.get("clean_names"):
        names.clean(
            list(catalog.values()),
            {
                catalog[i]["id"]: [summaries[m]["name"] for m in mbids]
                for i, mbids, _ in grouped.iter_rows()
            },
        )
    else:
        for genre in catalog.values():
            names.rename(genre)
    related = None
    if config.get("related_genres"):
        with np.load(Path(config["layout"]) / "sonic_state.npz") as state:
            related = related_genres(catalog, memberships, artists, state["vectors"])
    populated = set()
    for i, mbids, scores in grouped.iter_rows():
        populated.add(i)
        write(
            stage / "genres" / f"{public[i]}.json",
            {
                "genre": catalog[i],
                "related": related[i] if related is not None else None,
                "members": [
                    {"artist": summaries[m], "score": s} for m, s in zip(mbids, scores, strict=True)
                ],
            },
        )
    for i in retained - populated:
        write(
            stage / "genres" / f"{public[i]}.json",
            {
                "genre": catalog[i],
                "members": [],
                "related": related[i] if related is not None else None,
            },
        )
    graph = pl.read_parquet(similarity)
    if "similarity" in config:
        graph = graph.with_columns(pl.col("score") / max(1.0, graph["score"].max() or 1.0))
    if (
        graph.select("item", "neighbor").n_unique() != len(graph)
        or (graph["item"] == graph["neighbor"]).any()
        or graph["score"].null_count()
        or not graph["score"].is_finite().all()
        or not graph["score"].is_between(0, 1).all()
        or not set(graph["item"]) <= set(artists["item"])
    ):
        raise ValueError("Invalid M1 similarity graph")
    mapped = graph.join(
        artists.select(pl.col("item").alias("neighbor"), "artist_mbid"), on="neighbor"
    )
    if len(mapped) != len(graph):
        raise ValueError("Unknown M1 neighbor")
    neighbors = iter(
        mapped.sort(["item", "score", "artist_mbid"], descending=[False, True, False])
        .group_by("item", maintain_order=True)
        .agg("artist_mbid", "score")
        .iter_rows()
    )
    next_row = next(neighbors, None)
    for item, mbid in artists.select("item", "artist_mbid").iter_rows():
        similar = None
        if next_row is not None and next_row[0] == item:
            similar = [
                {"artist": summaries[m], "score": s}
                for m, s in zip(next_row[1], next_row[2], strict=True)
            ]
            next_row = next(neighbors, None)
        write(
            stage / "artists" / f"{mbid}.json",
            {
                "artist": summaries[mbid],
                "genres": artist_genres.get(mbid, []),
                "similar": similar,
                "signals": ["listening"],
                "links": [],
                "preview": None,
            },
        )
    genres_index = sorted(catalog.values(), key=lambda r: r["id"])
    write(stage / "genres.json", genres_index)
    search = [
        {"kind": "genre", "id": g["id"], "name": g["name"], "aliases": g["aliases"]}
        for g in genres_index
    ]
    search.extend(
        {
            "kind": "artist",
            "id": i,
            "name": summaries[i]["name"],
            "aliases": [name for name in artist_aliases.get(i, []) if name != summaries[i]["name"]],
            "listeners": summaries[i]["listeners"],
            "disambiguation": summaries[i]["disambiguation"],
        }
        for i in sorted(summaries)
    )
    write(stage / "search.json", search)
    write(
        stage / "manifest.json",
        {
            "schema_version": 1,
            "release_id": run.name,
            "data_kind": "model",
            "layouts": layouts,
            "membership": "all-label propagation and Leiden membership",
            "similarity": "M1 top-50 artist similarity",
            "genre_similarity": "ALS+audio cosine top-10" if related is not None else None,
            "genres": "genres.json",
            "search": "search.json",
            "artist_redirects": artist_redirects,
        },
    )
    files = list(stage.rglob("*.json"))
    summary = {
        "genres": len(catalog),
        "artists": len(summaries),
        "memberships": len(memberships),
        "similarities": len(graph),
        "files": len(files),
        "bytes": sum(p.stat().st_size for p in files),
        "grouping": groups,
        "global_grouping": global_groups,
        "readability": readability,
        "placement": {
            kind: {
                family: sum(
                    value[family] is not None for (k, _), value in placed.items() if k == kind
                )
                for family in ["axes", "islands"]
            }
            for kind in ["genre", "artist"]
        },
        "seconds": time.monotonic() - start,
    }
    write(run / "genre_ids.json", mapping)
    write(run / "release-summary.json", summary)
    stage.rename(target)
    tags.log(run, "m2d_export", summary, True)


def execute(stage, config, run):
    try:
        export(config, run)
    except Exception as error:
        tags.log(run, "m2d_export", {"status": "failed", "error": str(error)})
        raise
