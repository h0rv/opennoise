import json
import time
import tomllib
from pathlib import Path

import numpy as np
import polars as pl
from scipy import sparse

from opennoise import tags
from opennoise.genres import graph_matrix, split_labels, tag_matrix, update_top
from opennoise.metrics import name_agreement, name_hit, normalized_name


def settings(config):
    return tomllib.loads(Path(config["m2_config"]).read_text())


def structure(config):
    base = Path(config["m2"])
    genres = pl.read_parquet(base / "genres.parquet").filter(pl.col("level") >= 0).sort("id")
    archive = np.load(base / "clusters.npz")
    assignments = [archive[str(i)] for i in range(len(archive.files))]
    return genres, assignments


def discogs_matrix(config, artists):
    frame = pl.read_parquet(Path(config["tags_run"]) / "discogs.parquet")
    frame = frame.join(artists.select("artist_mbid", "item"), on="artist_mbid")
    if not len(frame) or frame["source"].unique().to_list() != ["discogs"]:
        raise ValueError("Expected nonempty MBID-aligned Discogs styles from PR109")
    vocabulary = frame.select("tag").unique().sort("tag").with_row_index("tag_id")
    frame = frame.join(vocabulary, on="tag")
    matrix = sparse.csr_matrix(
        (frame["weight"].to_numpy(), (frame["item"].to_numpy(), frame["tag_id"].to_numpy())),
        shape=(len(artists), len(vocabulary)),
    )
    return matrix, vocabulary["tag"].to_list()


def candidates(genres, assignments, matrix, vocabulary, popularity, variant):
    presence = matrix.copy()
    presence.data[:] = 1
    weighted = variant["method"] == "weighted"
    if weighted:
        matrix = matrix.copy()
        matrix.data = np.log1p(matrix.data)
        totals = np.asarray(matrix.sum(axis=1)).ravel()
        matrix = sparse.diags(popularity / np.maximum(totals, 1e-12)) @ matrix
        idf = np.log1p(matrix.shape[0] / np.maximum(presence.getnnz(axis=0), 1))
    else:
        matrix, popularity = presence, np.ones(matrix.shape[0])
    records = []
    previous = None
    for level, labels in enumerate(assignments):
        nodes = genres.filter(pl.col("level") == level).sort("id")
        sizes = np.bincount(labels)
        indicator = sparse.csr_matrix(
            (np.ones(len(labels)), (labels, np.arange(len(labels)))),
            shape=(len(nodes), len(labels)),
        )
        counts = (indicator @ presence).tocsr()
        mass = (indicator @ matrix).tocsr()
        populations = np.asarray(indicator @ popularity).ravel()
        if previous is None:
            parent_mass = sparse.csr_matrix(matrix.sum(axis=0))
            parent_sizes = np.array([popularity.sum()])
            parents = np.zeros(len(nodes), dtype=int)
        else:
            pairs = sparse.csr_matrix((np.ones(len(labels)), (labels, previous)))
            parents = np.asarray(pairs.argmax(axis=1)).ravel()
            parent_indicator = sparse.csr_matrix(
                (np.ones(len(labels)), (previous, np.arange(len(labels))))
            )
            parent_mass = (parent_indicator @ matrix).tocsr()
            parent_sizes = np.asarray(parent_indicator @ popularity).ravel()
        ordered = np.argsort(labels, kind="stable")
        bounds = np.concatenate([[0], np.cumsum(sizes)])
        for cluster, genre_id in enumerate(nodes["id"]):
            row = counts.getrow(cluster)
            select = row.data >= variant["min_support"]
            columns, support = row.indices[select], row.data[select]
            if not len(columns):
                continue
            parent = parents[cluster]
            denominator = parent_mass[parent, columns].toarray().ravel()
            context_size = parent_sizes[parent]
            if previous is not None:
                members = ordered[bounds[cluster] : bounds[cluster + 1]]
                outside = members[previous[members] != parent]
                denominator += np.asarray(matrix[outside][:, columns].sum(axis=0)).ravel()
                context_size += popularity[outside].sum()
            share = mass[cluster, columns].toarray().ravel() / populations[cluster]
            lift = share / np.maximum(denominator / context_size, 1e-12)
            score = share * idf[columns] * np.log1p(lift) if weighted else lift
            order = np.lexsort((columns, -support, -score))
            order = order[lift[order] >= variant["min_lift"]][:3]
            for rank, index in enumerate(order, 1):
                records.append(
                    (
                        genre_id,
                        rank,
                        vocabulary[columns[index]],
                        float(score[index]),
                        int(support[index]),
                        float(lift[index]),
                    )
                )
        previous = labels
    return pl.DataFrame(
        records,
        schema={
            "id": pl.Int64,
            "rank": pl.Int64,
            "name": pl.String,
            "score": pl.Float64,
            "support": pl.Int64,
            "lift": pl.Float64,
        },
        orient="row",
    )


def build(config, run):
    artists = pl.read_parquet(Path(config["m1"]) / "artists.parquet")
    genres, assignments = structure(config)
    mb_matrix, mb_names = tag_matrix(len(artists))
    dc_matrix, dc_names = discogs_matrix(config, artists)
    baseline = {"name": "musicbrainz_baseline", "method": "lift", "min_support": 3, "min_lift": 0}
    for variant in [baseline, *config["variants"]]:
        target = run / variant["name"]
        target.mkdir(exist_ok=True)
        if (target / "build.json").exists():
            continue
        start = time.monotonic()
        try:
            is_baseline = variant is baseline
            matrix, names = (mb_matrix, mb_names) if is_baseline else (dc_matrix, dc_names)
            rows = candidates(
                genres,
                assignments,
                matrix,
                names,
                np.log1p(artists["listeners"].to_numpy()),
                variant,
            )
            named = (
                genres.drop("name")
                .join(rows.filter(pl.col("rank") == 1).select("id", "name"), on="id", how="left")
                .select("id", "name", "level", "parent", "size")
            )
            if is_baseline:
                current = genres.filter(~pl.col("name").str.starts_with("unnamed "))
                recovered = named.filter(pl.col("name").is_not_null())
                if (
                    current.select("id", "name").sort("id").rows()
                    != recovered.select("id", "name").sort("id").rows()
                ):
                    raise ValueError("MusicBrainz baseline differs from kept M2 names")
            rows.write_parquet(target / "candidates.parquet")
            named.write_parquet(target / "genres.parquet")
            summary = {
                "source": "musicbrainz" if is_baseline else "discogs",
                "seconds": time.monotonic() - start,
                "vocabulary": len(names),
                "tagged_artists": int(np.count_nonzero(matrix.getnnz(axis=1))),
                "vocabulary_name_share": None,
            }
            _, _, heldout, _ = split_labels(settings(config))
            vocabulary = {normalized_name(name) for name in names}
            summary["vocabulary_name_share"] = sum(
                normalized_name(name) in vocabulary for name in heldout
            ) / len(heldout)
            (target / "build.json").write_text(json.dumps(summary, indent=2))
            print(variant["name"], json.dumps(summary), flush=True)
        except Exception as error:
            raise RuntimeError(f"{variant['name']}: {error}") from error


def evaluate(config, run):
    _, _, heldout, _ = split_labels(settings(config))
    matches = json.loads((Path(config["m2"]) / "matches.json").read_text())
    if set(matches) != set(heldout) or len(heldout) != 868:
        raise ValueError("Expected the kept M2 split: all 868 held-out genres")
    results = {}
    for name in [
        *config.get("baselines", ["musicbrainz_baseline"]),
        *[v["name"] for v in config["variants"]],
    ]:
        target = run / name
        rows = pl.read_parquet(target / "candidates.parquet").sort("id", "rank")
        choices = {group["id"][0]: group["name"].to_list() for group in rows.partition_by("id")}
        agreement, hit3 = [], []
        for reference, match in matches.items():
            names = choices.get(match["cluster"], [])
            hit3.append(name_hit(reference, names))
            if match["jaccard"] >= 0.2:
                agreement.append(name_agreement(reference, names[0] if names else ""))
        genres = pl.read_parquet(target / "genres.parquet")
        metrics = json.loads((target / "build.json").read_text()) | {
            "heldout_genres": len(heldout),
            "matched_genres": len(agreement),
            "name_exact": float(np.mean([x[0] for x in agreement])) if agreement else 0,
            "name_token_jaccard": float(np.mean([x[1] for x in agreement])) if agreement else 0,
            "name@3": float(np.mean(hit3)),
            "named_clusters": int(genres["name"].is_not_null().sum()),
            "clusters": len(genres),
            "named_cluster_share": int(genres["name"].is_not_null().sum()) / len(genres),
        }
        results[name] = metrics
    eligible = [
        name
        for name, value in results.items()
        if value["source"] in {"discogs", "wikidata", "combined"}
    ]
    best = max(
        eligible,
        key=lambda name: (
            results[name]["name@3"]
            + (results[name]["name_exact"] if config.get("selection") == "exact_plus_name3" else 0),
            results[name]["name_exact"],
        ),
    )
    for name, metrics in results.items():
        target = run / name / "metrics.json"
        if not target.exists():
            tags.log(run, name, metrics, name == best, "M2 fine k20; unchanged 868-genre split")
            target.write_text(json.dumps(metrics, indent=2))
    (run / "metrics.json").write_text(json.dumps(results, indent=2))
    (run / "best.json").write_text(
        json.dumps({"variant": best, "source": results[best]["source"]}, indent=2)
    )
    write_probes(config, run, results, matches)


def write_probes(config, run, results, matches):
    artists = pl.read_parquet(Path(config["m1"]) / "artists.parquet")
    genres, assignments = structure(config)
    offsets = [genres.filter(pl.col("level") == i)["id"].min() for i in range(len(assignments))]
    lines = []
    for variant in results:
        rows = pl.read_parquet(run / variant / "candidates.parquet").sort("id", "rank")
        names = {g["id"][0]: g["name"].to_list() for g in rows.partition_by("id")}
        lines.append(variant)
        for probe in ["Aphex Twin", "Slowdive", "Burial", "Kendrick Lamar"]:
            item = artists.filter(pl.col("artist_name") == probe)["item"][0]
            values = [
                names.get(int(level[item]) + offset, [])
                for level, offset in zip(assignments, offsets, strict=True)
            ]
            lines.append(f"{probe}: {json.dumps(values)}")
        for probe in ["shoegaze", "drill"]:
            match = matches[probe]
            lines.append(
                f"{probe}: Jaccard={match['jaccard']:.4f}; "
                f"cluster={match['cluster']}; {json.dumps(names.get(match['cluster'], []))}"
            )
        lines.append("")
    (run / "probes.txt").write_text("\n".join(lines))


def export(config, run):
    target = run / "export"
    target.mkdir(exist_ok=True)
    if (target / "summary.json").exists():
        return
    start = time.monotonic()
    selected = json.loads((run / "best.json").read_text())
    allowed = [*config.get("baselines", []), *[v["name"] for v in config["variants"]]]
    if (
        selected["source"] not in {"discogs", "wikidata", "combined"}
        or selected["variant"] not in allowed
    ):
        raise ValueError("Export requires a scored CC0 naming variant")
    model = settings(config)
    _, _, _, truth = split_labels(model)
    names = sorted(truth)
    artists = pl.read_parquet(Path(config["m1"]) / "artists.parquet")
    n = len(artists)
    if config.get("membership_cache"):
        cached = Path(config["membership_cache"])
        known = pl.read_parquet(cached / "genres.parquet").filter(pl.col("level") == -1).sort("id")
        if known["name"].to_list() != names:
            raise ValueError("Cached membership refit has different supervised genres")
        memberships = pl.read_parquet(cached / "memberships.parquet").filter(
            pl.col("genre") < len(names)
        )
        memberships = memberships.join(
            artists.select("item", "artist_mbid"), left_on="artist", right_on="artist_mbid"
        ).select("item", "genre", "score")
    else:
        variant = next(v for v in model["variants"] if v["name"] == "fine_k20")
        _, transition = graph_matrix(model, variant)
        ids = np.full((n, 10), -1, dtype=np.int32)
        values = np.zeros((n, 10), dtype=np.float32)
        for start_genre in range(0, len(names), 32):
            batch = names[start_genre : start_genre + 32]
            seeds = np.zeros((n, len(batch)), dtype=np.float32)
            for column, name in enumerate(batch):
                seeds[truth[name], column] = 1
            scores = transition @ seeds
            if variant["hops"] == 2:
                scores = 0.5 * scores + 0.5 * (transition @ scores)
            ids, values = update_top(ids, values, scores, start_genre)
        keep = (values.ravel() > 0) & (ids.ravel() >= 0)
        memberships = pl.DataFrame(
            {
                "item": np.repeat(np.arange(n), 10)[keep],
                "genre": ids.ravel()[keep],
                "score": values.ravel()[keep],
            }
        )
    sizes = dict(memberships.group_by("genre").len().iter_rows())
    base, assignments = structure(config)
    shift = len(names) - int(base["id"].min())
    named = pl.read_parquet(run / selected["variant"] / "genres.parquet")
    named = named.filter(pl.col("name").is_not_null())
    retained = set(named["id"])
    parents = dict(base.select("id", "parent").iter_rows())
    rows = [(i, name, -1, None, sizes.get(i, 0)) for i, name in enumerate(names)]
    for genre_id, name, level, parent, size in named.iter_rows():
        while parent is not None and parent not in retained:
            parent = parents[parent]
        rows.append(
            (genre_id + shift, name, level, parent + shift if parent is not None else None, size)
        )
    genres = pl.DataFrame(
        rows,
        schema={
            "id": pl.Int64,
            "name": pl.String,
            "level": pl.Int64,
            "parent": pl.Int64,
            "size": pl.Int64,
        },
        orient="row",
    )
    discovered = []
    for level, labels in enumerate(assignments):
        offset = int(base.filter(pl.col("level") == level)["id"].min())
        discovered.append(
            pl.DataFrame(
                {
                    "item": np.arange(n),
                    "genre": labels + offset,
                    "score": np.ones(n, dtype=np.float32),
                }
            )
            .filter(pl.col("genre").is_in(list(retained)))
            .with_columns(pl.col("genre") + shift)
        )
    memberships = pl.concat([memberships, *discovered], how="vertical_relaxed")
    memberships = memberships.join(artists.select("item", "artist_mbid"), on="item").select(
        pl.col("artist_mbid").alias("artist"), "genre", "score"
    )
    genres.write_parquet(target / "genres.parquet")
    memberships.write_parquet(target / "memberships.parquet")
    summary = {
        "variant": selected["variant"],
        "naming_source": selected["source"] + " CC0; ENAO supervised labels",
        "membership_refit_reused": bool(config.get("membership_cache")),
        "supervised_genres": len(names),
        "training_labels": sum(map(len, truth.values())),
        "training_artists": len(set(np.concatenate(list(truth.values())).tolist())),
        "discovered_genres": len(named),
        "excluded_unnamed_clusters": len(base) - len(named),
        "genres": len(genres),
        "memberships": len(memberships),
        "seconds": time.monotonic() - start,
    }
    (target / "summary.json").write_text(json.dumps(summary, indent=2))
    tags.log(
        run,
        config["milestone"] + "_export",
        summary,
        True,
        "all eligible genres and artists; no holdouts",
    )


def execute(stage, config, run):
    try:
        if stage == "ingest":
            tag_config = tomllib.loads(Path(config["tags_config"]).read_text())
            tag_run = Path(config["tags_run"])
            tag_run.mkdir(parents=True, exist_ok=True)
            tags.execute(stage, tag_config, tag_run)
        else:
            {"build": build, "eval": evaluate, "export": export}[stage](config, run)
    except Exception as error:
        tags.log(run, f"m2b_{stage}", {"status": "failed", "error": str(error)})
        raise
