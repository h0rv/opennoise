import json
import re
import subprocess
import tarfile
import tomllib
import urllib.request
from pathlib import Path

import numpy as np
import polars as pl
from scipy.spatial import KDTree

from opennoise.generalization import ingest, labels_by_artist


def extract(root, source_index, names, marker):
    if (root / marker).exists():
        return
    source = tomllib.loads(Path("sources.toml").read_text())["sources"][source_index]
    members = {f"mbdump/{name}" for name in names}
    found = set()
    with urllib.request.urlopen(source["url"], timeout=180) as response:
        with tarfile.open(fileobj=response, mode="r|bz2") as archive:
            for member in archive:
                if member.name in members:
                    archive.extract(member, root, filter="data")
                    found.add(member.name)
    if found != members:
        raise ValueError(f"MusicBrainz tables missing: {members - found}")
    (root / marker).touch()


def prepare(root):
    root.mkdir(parents=True, exist_ok=True)
    release_id = re.search(
        r"CATALOG_RELEASE: (\S+)", Path(".github/workflows/pages.yml").read_text()
    )
    if release_id is None:
        raise ValueError("Pages workflow has no CATALOG_RELEASE")
    release_id = release_id[1]
    if not (root / "release" / "manifest.json").exists():
        archive = root / f"release-{release_id}.tar.zst"
        if not archive.exists():
            subprocess.run(
                [
                    "gh",
                    "release",
                    "download",
                    release_id,
                    "--pattern",
                    archive.name,
                    "--dir",
                    str(root),
                ],
                check=True,
            )
        subprocess.run(["tar", "--zstd", "-xf", str(archive), "-C", str(root)], check=True)
    manifest = json.loads((root / "release" / "manifest.json").read_text())
    if manifest["release_id"] != release_id:
        raise ValueError("cached release differs from Pages CATALOG_RELEASE; use a fresh root")
    extract(
        root,
        3,
        {"artist", "url", "l_artist_url", "artist_credit_name", "release_group"},
        "mbdump.done",
    )
    extract(root, 4, {"release_group_meta"}, "dates.done")


def table(root, name, columns, names):
    frame = pl.scan_csv(
        root / name,
        separator="\t",
        has_header=False,
        quote_char=None,
        infer_schema=False,
        null_values="\\N",
    )
    return frame.select(
        pl.col(f"column_{column}").alias(name) for column, name in zip(columns, names, strict=True)
    )


def cohorts(root, catalog):
    artists = table(root, "artist", [0, 1], ["mb_artist", "id"]).join(
        catalog.lazy().select("id"), on="id"
    )
    credits = table(root, "artist_credit_name", [0, 2], ["credit", "mb_artist"])
    groups = table(root, "release_group", [0, 3], ["group", "credit"])
    dates = table(root, "release_group_meta", [0, 2, 3, 4], ["group", "year", "month", "day"])
    releases = (
        artists.join(credits, on="mb_artist")
        .join(groups, on="credit")
        .join(dates, on="group", how="left")
        .with_columns(pl.col("year", "month", "day").cast(pl.Int32))
        .with_columns(
            (
                pl.col("year") * 10000
                + pl.col("month").fill_null(1) * 100
                + pl.col("day").fill_null(1)
            ).alias("lower"),
            (
                pl.col("year") * 10000
                + pl.col("month").fill_null(12) * 100
                + pl.col("day").fill_null(31)
            ).alias("upper"),
        )
        .select("id", "group", "year", "lower", "upper")
        .unique()
        .collect(engine="streaming")
    )
    earliest = releases.group_by("id").agg(
        pl.col("lower").min(),
        pl.col("upper").min(),
        pl.col("year").is_null().any().alias("undated"),
    )
    sources = tomllib.loads(Path("sources.toml").read_text())["sources"]
    path = root.parent / "enao.json"
    if not path.exists():
        urllib.request.urlretrieve(sources[1]["url"], path)
    spotify = {
        artist["artist_id"] for genre in json.loads(path.read_text()) for artist in genre["artists"]
    }
    urls = (
        table(root, "url", [0, 2], ["url_id", "url"])
        .with_columns(
            pl.col("url")
            .str.extract(
                r"^https?://open\.spotify\.com/(?:intl-[^/]+/)?artist/([A-Za-z0-9]{22})(?:[/?#]|$)",
                1,
            )
            .alias("spotify")
        )
        .filter(pl.col("spotify").is_in(sorted(spotify)))
    )
    members = (
        table(root, "l_artist_url", [2, 3], ["mb_artist", "url_id"])
        .join(urls, on="url_id")
        .join(artists, on="mb_artist")
        .select("id")
        .unique()
        .collect(engine="streaming")
    )
    new = earliest.filter((pl.col("lower") >= 20240101) & ~pl.col("undated")).join(
        members, on="id", how="anti"
    )
    old = earliest.filter(pl.col("upper") < 20231201)
    years = {
        str(year): releases.filter(
            pl.col("id").is_in(new["id"].implode()) & (pl.col("year") == year)
        )["id"].n_unique()
        for year in (2024, 2025, 2026)
    }
    summary = {
        "catalog": len(catalog),
        "new": len(new),
        "old": len(old),
        "new_release_group_years": years,
        "with_release_groups": len(earliest),
        "with_undated_groups": earliest["undated"].sum(),
        "enao_members": len(members),
    }
    return new["id"].sort().to_list(), old["id"].sort().to_list(), summary


def read_catalog(release):
    rows = []
    for path in sorted((release / "artists").glob("*.json")):
        detail = json.loads(path.read_bytes())
        artist = detail["artist"]
        point = artist["positions"]["axes"]
        rows.append(
            {
                "id": artist["id"],
                "name": artist["name"],
                "listeners": artist["listeners"],
                "x": point["x"] if point else None,
                "y": point["y"] if point else None,
                "genres": [g["id"] for g in detail["genres"] or [] if g["score"] > 0],
                "similar": [n["artist"]["id"] for n in (detail["similar"] or [])[:10]],
            }
        )
    if not rows:
        raise ValueError("release has no artist details")
    return pl.DataFrame(rows)


def interval(values, seed=42, samples=2000):
    values = np.asarray(values, dtype=float)
    if not len(values):
        return {"mean": None, "ci95": None, "artists": 0}
    if np.all(values == values[0]):
        value = float(values[0])
        return {"mean": value, "ci95": [value, value], "artists": len(values)}
    rng = np.random.default_rng(seed)
    means = np.empty(samples)
    for start in range(0, samples, 20):
        count = min(20, samples - start)
        means[start : start + count] = rng.choice(values, (count, len(values))).mean(axis=1)
    return {
        "mean": float(values.mean()),
        "ci95": np.quantile(means, [0.025, 0.975]).tolist(),
        "artists": len(values),
    }


def agreement(ids, neighbors, labels, pool, seed=42):
    rng = np.random.default_rng(seed)
    pool = sorted(set(pool) & labels.keys())
    positions = {artist: i for i, artist in enumerate(pool)}
    actual, random = [], []
    pairs = 0
    for artist in ids:
        if artist not in positions or len(pool) < 2:
            continue
        eligible = [n for n in neighbors.get(artist, [])[:10] if n != artist and n in labels]
        if not eligible:
            continue
        actual.append(np.mean([bool(labels[artist] & labels[n]) for n in eligible]))
        draws = rng.integers(len(pool) - 1, size=len(eligible))
        draws += draws >= positions[artist]
        random.append(np.mean([bool(labels[artist] & labels[pool[i]]) for i in draws]))
        pairs += len(eligible)
    return {"actual": interval(actual), "random": interval(random), "pairs": pairs}


def map_neighbors(catalog):
    positioned = catalog.filter(pl.col("x").is_not_null() & pl.col("y").is_not_null())
    ids = positioned["id"].to_list()
    if len(ids) < 2:
        return {}
    points = positioned.select("x", "y").to_numpy()
    _, indices = KDTree(points).query(points, k=min(11, len(ids)), workers=-1)
    return {
        artist: [ids[j] for j in row if ids[j] != artist][:10]
        for artist, row in zip(ids, indices, strict=True)
    }


def artist_tags(root, catalog):
    extract(root, 4, {"artist_tag", "tag"}, "tags.done")
    dump = root / "mbdump"
    return (
        table(dump, "artist_tag", [0, 1, 2], ["mb_artist", "tag_id", "count"])
        .filter(pl.col("count").cast(pl.Int32) > 0)
        .join(table(dump, "artist", [0, 1], ["mb_artist", "artist_mbid"]), on="mb_artist")
        .join(table(dump, "tag", [0, 1], ["tag_id", "genre_qid"]), on="tag_id")
        .join(catalog.lazy().select(pl.col("id").alias("artist_mbid")), on="artist_mbid")
        .select("artist_mbid", "genre_qid")
        .unique()
        .collect(engine="streaming")
    )


def evaluate(catalog, new, old, reference):
    labels = labels_by_artist(reference)
    similar = dict(catalog.select("id", "similar").iter_rows())
    near = map_neighbors(catalog)
    result = {}
    pool = catalog["id"].to_list()
    for name, ids in (("new", new), ("old", old), ("random_catalog", pool)):
        frame = catalog.filter(pl.col("id").is_in(ids))
        positioned = frame["x"].is_not_null() & frame["y"].is_not_null()
        genres = frame["genres"].list.len() > 0
        neighbors = frame["similar"].list.len() > 0
        result[name] = {
            "size": len(ids),
            "reference_artists": sum(artist in labels for artist in ids),
            "coverage": {
                "position": interval(positioned.to_list()),
                "genres": interval(genres.to_list()),
                "similar": interval(neighbors.to_list()),
                "all_three": interval((positioned & genres & neighbors).to_list()),
            },
            "similar": agreement(ids, similar, labels, pool),
            "map": agreement(ids, near, labels, pool),
        }
    return result


def run(root=Path("data/extrapolation")):
    prepare(root)
    release = root / "release"
    manifest = json.loads((release / "manifest.json").read_text())
    cache = root / "catalog.parquet"
    if not cache.exists():
        read_catalog(release).write_parquet(cache)
    catalog = pl.read_parquet(cache)
    cohort_cache = root / "cohorts.json"
    if not cohort_cache.exists():
        new, old, summary = cohorts(root / "mbdump", catalog)
        cohort_cache.write_text(json.dumps({"new": new, "old": old, "summary": summary}))
    cohort = json.loads(cohort_cache.read_text())
    reference_root = root / "wikidata"
    ingest({"reference": str(reference_root), "endpoint": "https://qlever.dev/api/wikidata"})
    reference = pl.read_parquet(reference_root / "wikidata.parquet")
    results = {
        "release": manifest["release_id"],
        "method": {
            "k": 10,
            "bootstrap_samples": 2000,
            "seed": 42,
            "resampling_unit": "artist",
            "new": "earliest date >=2024-01-01, no undated groups, absent ENAO crosswalk",
            "old": "a release group certainly before 2023-12-01; full cohort",
            "random": "uniform catalog artists with reference labels, excluding self",
            "fallback_below_scored_new_artists": 100,
            "fallback_below_new_reference_coverage": 0.05,
        },
        "cohorts": cohort["summary"],
        "wikidata": evaluate(catalog, cohort["new"], cohort["old"], reference),
    }
    new_result = results["wikidata"]["new"]
    if (
        new_result["similar"]["actual"]["artists"] < 100
        or new_result["reference_artists"] < 0.05 * new_result["size"]
    ):
        tags = artist_tags(root, catalog)
        results["musicbrainz_tags_evaluation_only"] = evaluate(
            catalog, cohort["new"], cohort["old"], tags
        )
    (root / "results.json").write_text(json.dumps(results, indent=2))
    print(json.dumps(results, indent=2), flush=True)
    return results
