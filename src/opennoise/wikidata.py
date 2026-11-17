import hashlib
import json
import shutil
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path

import numpy as np
import polars as pl
from scipy import sparse

from opennoise import naming, tags
from opennoise.genres import split_labels
from opennoise.metrics import normalized_name, sealed

PREFIXES = """PREFIX wdt: <http://www.wikidata.org/prop/direct/>
PREFIX wd: <http://www.wikidata.org/entity/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
"""
QUERIES = {
    "music_genres": """SELECT DISTINCT ?genre WHERE {
{ ?genre wdt:P31/wdt:P279* wd:Q188451 } UNION { ?genre wdt:P279* wd:Q188451 } }""",
    "artist_genres": """SELECT DISTINCT ?mbid ?genre WHERE {
?artist wdt:P434 ?mbid; wdt:P136 ?genre }""",
    "vocabulary": """SELECT DISTINCT ?genre ?label ?alias ?parent WHERE {
{ SELECT DISTINCT ?genre WHERE {
{ ?genre wdt:P31 wd:Q188451 } UNION { ?genre wdt:P279+ wd:Q188451 }
} }
OPTIONAL { ?genre rdfs:label ?label FILTER(LANG(?label) = "en") }
OPTIONAL { ?genre skos:altLabel ?alias FILTER(LANG(?alias) = "en") }
OPTIONAL { ?genre wdt:P279 ?parent } }""",
}


def fetch(config, name):
    path = Path(config["cache"]) / f"{name}.json"
    cached = path.exists()
    if cached:
        payload = path.read_bytes()
    else:
        params = urllib.parse.urlencode({"query": PREFIXES + QUERIES[name], "send": 10_000_000})
        request = urllib.request.Request(
            config["endpoint"] + "?" + params, headers={"Accept": "application/sparql-results+json"}
        )
        with urllib.request.urlopen(request, timeout=180) as response:
            payload = response.read()
    data = json.loads(payload)
    rows = data["results"]["bindings"]
    if len(rows) != data["meta"]["result-size-total"]:
        raise ValueError(f"Truncated QLever result: {name}")
    if not cached:
        path.with_suffix(".part").write_bytes(payload)
        path.with_suffix(".part").rename(path)
    return rows


def ingest(config, run):
    root = Path(config["cache"])
    root.mkdir(parents=True, exist_ok=True)
    if (root / "coverage.json").exists() and json.loads((root / "coverage.json").read_text()).get(
        "music_genre_root"
    ) == "Q188451":
        print((root / "coverage.json").read_text(), flush=True)
        return
    start = time.monotonic()
    links = (
        pl.DataFrame(
            [
                (r["mbid"]["value"].lower(), r["genre"]["value"].rsplit("/", 1)[-1])
                for r in fetch(config, "artist_genres")
            ],
            schema={"artist_mbid": pl.String, "qid": pl.String},
            orient="row",
        )
        .unique()
        .filter(~pl.col("artist_mbid").map_elements(sealed, return_dtype=pl.Boolean))
    )
    names, parents = [], []
    for row in fetch(config, "vocabulary"):
        qid = row["genre"]["value"].rsplit("/", 1)[-1]
        for kind in ["label", "alias"]:
            if kind in row:
                name = row[kind]["value"]
                if normalized_name(name):
                    names.append((qid, name, normalized_name(name), kind))
        if "parent" in row:
            parents.append((qid, row["parent"]["value"].rsplit("/", 1)[-1]))
    vocabulary = pl.DataFrame(
        names,
        schema={"qid": pl.String, "name": pl.String, "normalized": pl.String, "kind": pl.String},
        orient="row",
    ).unique()
    hierarchy = pl.DataFrame(
        parents, schema={"qid": pl.String, "parent": pl.String}, orient="row"
    ).unique()
    allowed = {r["genre"]["value"].rsplit("/", 1)[-1] for r in fetch(config, "music_genres")}
    dropped = {
        "vocabulary_items_dropped": vocabulary.filter(~pl.col("qid").is_in(allowed))[
            "qid"
        ].n_unique(),
        "english_names_dropped": vocabulary.filter(~pl.col("qid").is_in(allowed)).height,
        "p136_pairs_dropped": links.filter(~pl.col("qid").is_in(allowed)).height,
    }
    vocabulary = vocabulary.filter(pl.col("qid").is_in(allowed))
    links = links.filter(pl.col("qid").is_in(allowed))
    hierarchy = hierarchy.filter(pl.col("qid").is_in(allowed) & pl.col("parent").is_in(allowed))
    artists = pl.read_parquet(Path(config["m1"]) / "artists.parquet")
    aligned = links.join(artists.select("artist_mbid", "item"), on="artist_mbid")
    _, _, heldout, _ = split_labels(naming.settings(config))
    available = set(vocabulary["normalized"])
    coverage = {
        "music_genre_root": "Q188451",
        **dropped,
        "global_artist_genres": len(links),
        "global_artists": links["artist_mbid"].n_unique(),
        "m1_artists": len(artists),
        "p136_artists": aligned["item"].n_unique(),
        "p136_artist_share": aligned["item"].n_unique() / len(artists),
        "english_p136_artists": aligned.join(vocabulary.select("qid").unique(), on="qid")[
            "item"
        ].n_unique(),
        "genre_items": vocabulary["qid"].n_unique(),
        "english_names": len(vocabulary),
        "parent_links": len(hierarchy),
        "heldout_names": sum(normalized_name(x) in available for x in heldout),
        "heldout_name_share": sum(normalized_name(x) in available for x in heldout) / len(heldout),
        "seconds": time.monotonic() - start,
        "response_sha256": {
            name: hashlib.sha256((root / f"{name}.json").read_bytes()).hexdigest()
            for name in QUERIES
        },
    }
    links.write_parquet(root / "artist_genres.parquet")
    vocabulary.sort("qid", "kind", "name").write_parquet(root / "vocabulary.parquet")
    hierarchy.write_parquet(root / "parents.parquet")
    (root / "coverage.json").write_text(json.dumps(coverage, indent=2))
    tags.log(
        run,
        "wikidata_ingest",
        coverage,
        note="CC0; full P434/P136; English labels/aliases and P279",
    )


def evidence(config, artists):
    root = Path(config["cache"])
    vocabulary = pl.read_parquet(root / "vocabulary.parquet")
    allowed = {r["genre"]["value"].rsplit("/", 1)[-1] for r in fetch(config, "music_genres")}
    vocabulary = vocabulary.filter(pl.col("qid").is_in(allowed))
    labels = {}
    aliases = defaultdict(set)
    canonical = defaultdict(set)
    for qid, name, normalized, kind in vocabulary.sort("kind", "name").iter_rows():
        aliases[normalized].add(qid)
        if kind == "label":
            labels[qid] = name
            canonical[normalized].add(qid)
        else:
            labels.setdefault(qid, name)
    identifiers = sorted(labels)
    columns = {qid: i for i, qid in enumerate(identifiers)}
    links = (
        pl.read_parquet(root / "artist_genres.parquet")
        .filter(~pl.col("artist_mbid").map_elements(sealed, return_dtype=pl.Boolean))
        .join(artists.select("item", "artist_mbid"), on="artist_mbid")
        .filter(pl.col("qid").is_in(identifiers))
    )
    wd = sparse.csr_matrix(
        (np.ones(len(links)), (links["item"].to_numpy(), [columns[x] for x in links["qid"]])),
        shape=(len(artists), len(identifiers)),
    )
    dc, styles = naming.discogs_matrix(config, artists)
    mapped, preferred = [], {}
    frequency = dc.getnnz(axis=0)
    for i, style in enumerate(styles):
        normalized = normalized_name(style)
        matches = canonical.get(normalized) or aliases.get(normalized, set())
        if len(matches) == 1:
            qid = next(iter(matches))
            mapped.append(columns[qid])
            if qid not in preferred or frequency[i] > preferred[qid][0]:
                preferred[qid] = (frequency[i], style)
        else:
            mapped.append(len(identifiers))
            identifiers.append("discogs:" + style)
            labels[identifiers[-1]] = style
    mapping = sparse.csr_matrix(
        (np.ones(len(styles)), (np.arange(len(styles)), mapped)),
        shape=(len(styles), len(identifiers)),
    )
    dc.data = np.log1p(dc.data)
    dc = sparse.diags(1 / np.maximum(np.asarray(dc.sum(axis=1)).ravel(), 1e-12)) @ dc
    dc = (dc @ mapping).tocsr()
    wd = sparse.hstack(
        [wd, sparse.csr_matrix((len(artists), len(identifiers) - wd.shape[1]))]
    ).tocsr()
    wd = sparse.diags(1 / np.maximum(np.asarray(wd.sum(axis=1)).ravel(), 1e-12)) @ wd
    stats = {
        "mapped_discogs_styles": sum(not identifiers[i].startswith("discogs:") for i in mapped),
        "mapped_wikidata_genres": len(preferred),
    }
    return wd, dc, identifiers, labels, preferred, stats


def build(config, run):
    artists = pl.read_parquet(Path(config["m1"]) / "artists.parquet")
    genres, assignments = naming.structure(config)
    wd, dc, identifiers, labels, preferred, stats = evidence(config, artists)
    for old, name in [
        ("musicbrainz_baseline", "musicbrainz_baseline"),
        ("discogs_weighted", "m2b_discogs_weighted"),
    ]:
        target = run / name
        target.mkdir(exist_ok=True)
        for file in ["genres.parquet", "candidates.parquet", "build.json"]:
            shutil.copy2(Path(config["m2b"]) / old / file, target / file)
    for variant in config["variants"]:
        target = run / variant["name"]
        target.mkdir(exist_ok=True)
        if (target / "build.json").exists():
            continue
        start = time.monotonic()
        matrix = wd if variant["source"] == "wikidata" else wd * variant["wikidata_weight"] + dc
        names = [
            preferred[qid][1] if variant["style_names"] and qid in preferred else labels[qid]
            for qid in identifiers
        ]
        rows = naming.candidates(
            genres, assignments, matrix, names, np.log1p(artists["listeners"].to_numpy()), variant
        )
        named = (
            genres.drop("name")
            .join(rows.filter(pl.col("rank") == 1).select("id", "name"), on="id", how="left")
            .select("id", "name", "level", "parent", "size")
        )
        rows.write_parquet(target / "candidates.parquet")
        named.write_parquet(target / "genres.parquet")
        summary = {
            "source": variant["source"],
            "seconds": time.monotonic() - start,
            "tagged_artists": int(np.count_nonzero(matrix.getnnz(axis=1))),
            "vocabulary": len(names),
            **stats,
        }
        (target / "build.json").write_text(json.dumps(summary, indent=2))
        print(variant["name"], json.dumps(summary), flush=True)


def execute(stage, config, run):
    try:
        {"ingest": ingest, "build": build, "eval": naming.evaluate, "export": naming.export}[stage](
            config, run
        )
    except Exception as error:
        tags.log(run, f"m2c_{stage}", {"status": "failed", "error": str(error)})
        raise
