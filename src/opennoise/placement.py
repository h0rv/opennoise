import hashlib
import json
import time
import tomllib
from pathlib import Path

import numpy as np
import polars as pl
from scipy import sparse
from sklearn.preprocessing import StandardScaler, normalize
from threadpoolctl import threadpool_limits
from umap import UMAP

from opennoise import grouping, layout, tags
from opennoise.catalog import hierarchy


def bounds(sets):
    joined = np.concatenate(sets)
    if not len(joined) or not np.isfinite(joined).all():
        raise ValueError("Layout must contain finite points")
    low, high = joined.min(axis=0), joined.max(axis=0)
    span = np.maximum(high - low, 1e-12)
    return [(points - low) / span for points in sets]


def project(reference, coordinates, train, targets, config):
    if not len(targets):
        return np.empty((0, 2))
    scaler = StandardScaler().fit(coordinates[train])
    model = layout.estimator("knn", 5, config)
    model.fit(reference[train], scaler.transform(coordinates[train]))
    return np.concatenate(
        [
            scaler.inverse_transform(model.predict(targets[start : start + 512]))
            for start in range(0, len(targets), 512)
        ]
    )


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
        evaluated / "genre_split.parquet",
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
    expected = {
        "axes": "als_2+audio_ab_all_log_listeners_knn_5",
        "islands": "als_2+audio_ab_all_umap_40_axes",
    }
    if winners != expected:
        raise ValueError("Expected the fixed ALS+audio layout models")
    artists = pl.read_parquet(m1 / "artists.parquet").sort("item")
    raw = Path(catalog["export"])
    rows = pl.read_parquet(raw / "genres.parquet").to_dicts()
    parents = hierarchy(rows, {r["id"] for r in rows})
    memberships = pl.read_parquet(raw / "memberships.parquet")
    public = {int(k): v for k, v in json.loads((source / "genre_ids.json").read_text()).items()}
    if catalog.get("group_siblings"):
        memberships, _, _, _ = grouping.siblings(rows, parents, memberships, public)
    if {r["id"] for r in rows} != public.keys():
        raise ValueError("Layout and catalog genre identities differ")
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
    artist_vectors = normalize(layout.artist_vectors(settings, evaluated, "als_2+audio_ab_all"))
    uniform = normalize(matrix @ artist_vectors)
    weights = np.log(np.maximum(artists["listeners"].to_numpy(), 2))
    weighted = normalize((matrix @ sparse.diags(weights)) @ artist_vectors)
    placed = (np.diff(matrix.indptr) >= settings["min_members"]) & (
        np.linalg.norm(uniform, axis=1) > 0
    )
    artist_placed = np.linalg.norm(artist_vectors, axis=1) > 0
    frame = pl.read_parquet(evaluated / "als_2+audio_ab_all_log_listeners_placed.parquet")
    split = pl.read_parquet(evaluated / "genre_split.parquet")
    frame = frame.join(split.select("genre", "fold"), on="genre", maintain_order="left")
    frame = frame.join(
        pl.read_parquet(Path(settings["reference"]) / "map.parquet"),
        on="genre",
        maintain_order="left",
    )
    reference = np.load(evaluated / "als_2+audio_ab_all_log_listeners_genre_vectors.npy")
    coordinates = frame.select("x", "y").to_numpy().astype(float)
    train = frame["split"].to_numpy() == "train"
    fold_by_name = dict(frame.select("genre", "fold").iter_rows())
    target_folds = np.array(
        [fold_by_name.get(r["name"], -1) if r["level"] == -1 else -1 for r in rows]
    )
    axes = np.zeros((len(rows), 2))
    with threadpool_limits(limits=settings["workers"]):
        for fold in range(-1, 5):
            target = placed & (target_folds == fold)
            fit = train if fold == -1 else train & (frame["fold"].to_numpy() != fold)
            axes[target] = project(reference, coordinates, fit, weighted[target], settings)
        artist_axes = project(
            reference, coordinates, train, artist_vectors[artist_placed], settings
        )
        print("Axes projected", flush=True)
        uniform_reference = np.load(evaluated / "als_2+audio_ab_all_genre_vectors.npy")
        initial = np.load(evaluated / "als_2+audio_ab_all_knn_5_coords.npy")
        model = UMAP(
            n_neighbors=40,
            min_dist=settings["umap_min_dist"],
            n_epochs=settings["umap_epochs"],
            metric="cosine",
            init=StandardScaler().fit_transform(initial).astype(np.float32),
            random_state=settings["seed"],
            n_jobs=1,
            compatibility_layout=True,
        )
        embedded = model.fit_transform(uniform_reference)
        cached = np.load(evaluated / f"{winners['islands']}_coords.npy")
        if not np.allclose(embedded, cached, atol=1e-6):
            raise ValueError("Fixed islands refit did not reproduce evaluation coordinates")
        islands = model.transform(uniform[placed])
        print("Genre islands projected", flush=True)
        artist_islands = model.transform(artist_vectors[artist_placed])
    genre_axes, artist_axes = bounds([axes[placed], artist_axes])
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
                "axes": {
                    "x_min": "Dense / atmospheric",
                    "x_max": "Spiky / bouncy",
                    "y_min": "Mechanical / electric",
                    "y_max": "Organic",
                },
                "islands": {"method": "UMAP 40; ALS + AcousticBrainz"},
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
        "fixed ALS+audio models; existing supervised folds; train-only axes; islands transform",
    )
    print(json.dumps(summary), flush=True)
