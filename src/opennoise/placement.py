import hashlib
import json
import pickle
import shutil
import time
import tomllib
from pathlib import Path

import numpy as np
import polars as pl
from scipy import sparse
from sklearn.preprocessing import normalize
from threadpoolctl import threadpool_limits

from opennoise import grouping, layout, sonic, tags
from opennoise.catalog import hierarchy, tables


def bounds(sets):
    joined = np.concatenate(sets)
    low, high = joined.min(axis=0), joined.max(axis=0)
    span = np.maximum(high - low, 1e-12)
    return [(points - low) / span for points in sets]


def export(config, run):
    start = time.monotonic()
    evaluated = Path(config["evaluation_run"])
    settings = tomllib.loads(Path(config["layout_config"]).read_text())
    source = Path(config["catalog_run"])
    catalog = tomllib.loads((source / "config.toml").read_text())
    settings["input_run"] = catalog["m1"]
    m1 = Path(catalog["m1"])
    files = [
        Path(config["layout_config"]),
        source / "genre_ids.json",
        source / "release-summary.json",
        evaluated / "layout_metrics.json",
        evaluated / "layout_models.json",
        evaluated / "layout_best.json",
        evaluated / "islands_genre_vectors.npy",
        evaluated / "sonic_model.pkl",
        Path(settings["audio_features"]),
        m1 / "als_2.npy",
        m1 / "audio_ab_all.npy",
    ]
    hashes = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    if (run / "positions.parquet").exists():
        if json.loads((run / "placement-summary.json").read_text())["inputs"] != hashes:
            raise ValueError("Immutable layout inputs changed")
        print("Cached catalog positions", flush=True)
        return
    winners = json.loads((evaluated / "layout_best.json").read_text())
    models = json.loads((evaluated / "layout_models.json").read_text())
    if hashes[settings["audio_features"]] != models["audio_sha256"]:
        raise ValueError("Audio features differ from layout evaluation")
    artists = pl.read_parquet(m1 / "artists.parquet").sort("item")
    genres, memberships = tables(catalog)
    rows = genres.to_dicts()
    parents = hierarchy(rows, {r["id"] for r in rows})
    public = {int(k): v for k, v in json.loads((source / "genre_ids.json").read_text()).items()}
    if catalog.get("group_siblings"):
        memberships, _, _, _ = grouping.siblings(rows, parents, memberships, public)
    rows.sort(key=lambda r: public[r["id"]])
    indices = {r["id"]: i for i, r in enumerate(rows)}
    edges = memberships.join(
        artists.select("artist_mbid", "item"), left_on="artist", right_on="artist_mbid"
    )
    matrix = sparse.csr_matrix(
        (
            edges["score"].to_numpy(),
            (
                edges["genre"].replace_strict(indices, return_dtype=pl.Int64).to_numpy(),
                edges["item"].to_numpy(),
            ),
        ),
        shape=(len(rows), len(artists)),
    )
    artist_vectors = normalize(layout.artist_vectors(settings, evaluated, models["embedding"]))
    uniform = normalize(matrix @ artist_vectors)
    with (evaluated / "sonic_model.pkl").open("rb") as stream:
        state = pickle.load(stream)
    artist_placed = np.linalg.norm(artist_vectors, axis=1) > 0
    with threadpool_limits(limits=settings["workers"]):
        genre_axes, placed, _ = sonic.place(state, matrix, artist_vectors, settings["min_members"])
        artist_axes = sonic.transform(state, artist_vectors[artist_placed])
    np.savez(
        run / "sonic_state.npz",
        vectors=artist_vectors,
        min_members=settings["min_members"],
    )
    shutil.copyfile(evaluated / "sonic_model.pkl", run / "sonic_model.pkl")
    with threadpool_limits(limits=settings["workers"]):
        print("Ranked oriented UMAP axes with frozen repulsion projected", flush=True)
        uniform_reference = np.load(evaluated / "islands_genre_vectors.npy")
        model = layout.islands_model(settings, models["neighbors"])
        embedded = model.fit_transform(uniform_reference)
        cached = np.load(evaluated / f"{winners['islands']}_coords.npy")
        if not np.allclose(embedded, cached, atol=1e-6):
            raise ValueError("Fixed islands refit did not reproduce evaluation coordinates")
        islands = model.transform(uniform[placed])
        print("Genre islands projected", flush=True)
        artist_islands = model.transform(artist_vectors[artist_placed])
    genre_islands, artist_islands = bounds([islands, artist_islands])
    output = []
    for kind, ids, mask, xy, uv in [
        ("genre", [public[r["id"]] for r in rows], placed, genre_axes, genre_islands),
        ("artist", artists["artist_mbid"].to_list(), artist_placed, artist_axes, artist_islands),
    ]:
        offset = 0
        for i, id_ in enumerate(ids):
            point = [None] * 4
            if mask[i]:
                point = [*xy[offset], *uv[offset]]
                offset += 1
            output.append((kind, id_, *point))
    pl.DataFrame(
        output,
        schema={
            "kind": pl.String,
            "id": pl.String,
            "x": pl.Float64,
            "y": pl.Float64,
            "island_x": pl.Float64,
            "island_y": pl.Float64,
        },
        orient="row",
    ).write_parquet(run / "positions.parquet")
    (run / "layouts.json").write_text(
        json.dumps(
            {
                "axes": models["captions"],
                "islands": {
                    "method": f"Spectral UMAP {models['neighbors']}; {models['embedding']}"
                },
            }
        )
    )
    metrics = json.loads((evaluated / "layout_metrics.json").read_text())
    summary = {
        "genres": len(rows),
        "genre_placed": int(placed.sum()),
        "genre_unplaced": int((~placed).sum()),
        "artists": len(artists),
        "artist_placed": int(artist_placed.sum()),
        "artist_unplaced": int((~artist_placed).sum()),
        "models": winners,
        "evaluation": {family: metrics[name] for family, name in winners.items()},
        "inputs": hashes,
        "seconds": time.monotonic() - start,
    }
    (run / "placement-summary.json").write_text(json.dumps(summary, indent=2))
    tags.log(
        run,
        "catalog_placement",
        summary,
        True,
        "ranked audio-oriented UMAP axes with frozen repulsion; spectral islands transform",
    )
    print(json.dumps(summary), flush=True)
