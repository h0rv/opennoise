import hashlib
import json
import urllib.parse
import urllib.request
from pathlib import Path

import numpy as np
import polars as pl
from scipy import sparse
from scipy.spatial import KDTree

from opennoise.metrics import best_cluster, name_agreement
from opennoise.tags import log

PREFIX = """
PREFIX wd: <http://www.wikidata.org/entity/>
PREFIX wdt: <http://www.wikidata.org/prop/direct/>
PREFIX p: <http://www.wikidata.org/prop/>
PREFIX ps: <http://www.wikidata.org/prop/statement/>
PREFIX pr: <http://www.wikidata.org/prop/reference/>
PREFIX prov: <http://www.w3.org/ns/prov#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
"""
QUERIES = {
    "statements": """SELECT DISTINCT ?statement ?mbid ?qid ?genre WHERE {
      ?artist wdt:P434 ?mbid ; p:P136 ?statement . ?statement ps:P136 ?qid .
      OPTIONAL { ?qid rdfs:label ?genre FILTER(LANG(?genre) = "en") }
    }""",
    "url_references": """SELECT DISTINCT ?statement WHERE {
      ?artist wdt:P434 ?mbid ; p:P136 ?statement .
      ?statement prov:wasDerivedFrom/pr:P854 ?url .
      FILTER(CONTAINS(LCASE(STR(?url)), "everynoise"))
    }""",
    "stated_in": """SELECT DISTINCT ?statement WHERE {
      ?artist wdt:P434 ?mbid ; p:P136 ?statement .
      ?statement prov:wasDerivedFrom/pr:P248 ?source .
      { ?source rdfs:label ?label FILTER(LANG(?label) = "en")
        FILTER(CONTAINS(LCASE(?label), "every noise")) }
      UNION { ?source wdt:P856 ?url FILTER(CONTAINS(LCASE(STR(?url)), "everynoise")) }
    }""",
    "linked": "SELECT DISTINCT ?qid WHERE { ?qid wdt:P9881 ?id }",
    "music": "SELECT DISTINCT ?qid WHERE { ?qid wdt:P31?/wdt:P279* wd:Q188451 }",
}
SCHEMA = {
    "artist_mbid": pl.String,
    "genre_qid": pl.String,
    "genre": pl.String,
    "enao_linked": pl.Boolean,
}


def query(endpoint, name, root):
    sparql = PREFIX + QUERIES[name]
    digest = hashlib.sha256(sparql.encode()).hexdigest()[:12]
    path = root / f"{name}-{digest}.json"
    if not path.exists():
        request = urllib.request.Request(
            endpoint,
            data=urllib.parse.urlencode({"query": sparql}).encode(),
            headers={"Accept": "application/sparql-results+json"},
        )
        with urllib.request.urlopen(request, timeout=180) as response:
            result = json.load(response)
        if "results" not in result or result.get("exception"):
            raise ValueError(f"Wikidata {name}: {result.get('exception', 'missing results')}")
        path.write_text(json.dumps(result))
    result = json.loads(path.read_text())
    return [
        {key: value["value"] for key, value in row.items()} for row in result["results"]["bindings"]
    ]


def clean_reference(statements, url_references, stated_in, linked, music=None):
    tainted = {row["statement"] for row in [*url_references, *stated_in]}
    linked = {row["qid"] for row in linked}
    rows = [
        (row["mbid"], row["qid"].rsplit("/", 1)[-1], row.get("genre", ""), row["qid"] in linked)
        for row in statements
        if row["statement"] not in tainted
        and (music is None or row["qid"] in music)
        and row.get("genre")
    ]
    frame = pl.DataFrame(rows, schema=SCHEMA, orient="row").unique()
    if music is None:
        eligible = frame.group_by("genre_qid").agg(pl.col("artist_mbid").n_unique().alias("n"))
        frame = frame.join(eligible.filter(pl.col("n") >= 5).select("genre_qid"), on="genre_qid")
    return frame.sort("artist_mbid", "genre_qid")


def ingest(config):
    root = Path(config["reference"])
    root.mkdir(parents=True, exist_ok=True)
    target = root / "wikidata.parquet"
    if not target.exists():
        results = {
            name: query(config["endpoint"], name, root) for name in QUERIES if name != "music"
        }
        try:
            music = {row["qid"] for row in query(config["endpoint"], "music", root)}
            restriction = "P31?/P279* Q188451"
        except (OSError, ValueError) as error:
            print(f"Music hierarchy unavailable: {error}; using >=5 MBID artists", flush=True)
            music, restriction = None, ">=5 MBID artists"
        frame = clean_reference(**results, music=music)
        url = {row["statement"] for row in results["url_references"]}
        stated = {row["statement"] for row in results["stated_in"]}
        summary = {
            "statements": len({row["statement"] for row in results["statements"]}),
            "enao_url_statements": len(url),
            "enao_stated_in_statements": len(stated),
            "dropped_statements": len(url | stated),
            "restriction": restriction,
        }
        frame.write_parquet(target)
        (root / "summary.json").write_text(json.dumps(summary, indent=2))
    frame = pl.read_parquet(target)
    summary = json.loads((root / "summary.json").read_text()) | {
        "rows": len(frame),
        "artists": frame["artist_mbid"].n_unique(),
        "genres": frame["genre_qid"].n_unique(),
        "independent_genres": frame.filter(~pl.col("enao_linked"))["genre_qid"].n_unique(),
        "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
    }
    print(json.dumps(summary), flush=True)


def labels_by_artist(reference):
    return {
        key[0]: set(group["genre_qid"])
        for key, group in reference.group_by("artist_mbid", maintain_order=True)
    }


def mean(values):
    return float(np.mean(values)) if len(values) else None


def similarity_score(reference, artists, edges, seed=42, k=10):
    if k < 1:
        raise ValueError("k must be positive")
    labels = labels_by_artist(reference)
    ids = dict(artists.select("item", "artist_mbid").iter_rows())
    pool = sorted(set(ids.values()) & labels.keys())
    rng = np.random.default_rng(seed)
    edges = edges.filter(pl.col("item") != pl.col("neighbor")).sort(
        ["item", "score", "neighbor"], descending=[False, True, False]
    )
    actual, random, pairs = [], [], 0
    positions = {artist: i for i, artist in enumerate(pool)}
    for key, group in edges.group_by("item", maintain_order=True):
        artist = ids.get(key[0])
        if artist not in positions or len(pool) < 2:
            continue
        neighbors = [ids.get(item) for item in group.head(k)["neighbor"]]
        neighbors = [neighbor for neighbor in neighbors if neighbor in labels]
        if not neighbors:
            continue
        actual.append(mean([bool(labels[artist] & labels[n]) for n in neighbors]))
        draws = rng.integers(len(pool) - 1, size=len(neighbors))
        draws += draws >= positions[artist]
        random.append(mean([bool(labels[artist] & labels[pool[i]]) for i in draws]))
        pairs += len(neighbors)
    return {
        "agreement@10": mean(actual),
        "random": mean(random),
        "artists": len(actual),
        "pairs": pairs,
    }


def cluster_scores(reference, memberships, genres, seed=42, minimum=5):
    if minimum < 1:
        raise ValueError("minimum must be positive")
    memberships = memberships.filter(pl.col("score") > 0).select("artist", "genre").unique()
    discovered = genres.filter(pl.col("level") >= 0)
    memberships = memberships.join(discovered.select(pl.col("id").alias("genre")), on="genre")
    artists = sorted(set(reference["artist_mbid"]) & set(memberships["artist"]))
    if not artists:
        return {
            "genre_match": None,
            "median_jaccard": None,
            "random_genre_match": None,
            "random_median_jaccard": None,
            "genres": 0,
            "artists": 0,
        }
    index = {artist: i for i, artist in enumerate(artists)}
    assignments = []
    for group in discovered.partition_by("level"):
        ids = group["id"].to_list()
        members = memberships.filter(pl.col("genre").is_in(ids) & pl.col("artist").is_in(artists))
        if members["artist"].n_unique() != len(artists) or members.height != len(artists):
            raise ValueError("Discovered levels must partition covered artists")
        clusters = {cluster: i for i, cluster in enumerate(sorted(ids))}
        labels = np.empty(len(artists), dtype=np.int64)
        for artist, cluster in members.iter_rows():
            labels[index[artist]] = clusters[cluster]
        assignments.append(labels)
    order = np.random.default_rng(seed).permutation(len(artists))
    shuffled = [labels[order] for labels in assignments]
    values, random = [], []
    for group in reference.partition_by("genre_qid"):
        truth = [index[a] for a in set(group["artist_mbid"]) if a in index]
        if len(truth) >= minimum:
            values.append(best_cluster(truth, assignments)[0])
            random.append(best_cluster(truth, shuffled)[0])
    return {
        "genre_match": mean([value >= 0.2 for value in values]),
        "median_jaccard": float(np.median(values)) if values else None,
        "random_genre_match": mean([value >= 0.2 for value in random]),
        "random_median_jaccard": float(np.median(random)) if random else None,
        "genres": len(values),
        "artists": len(artists),
    }


def naming_score(reference, memberships, genres, seed=42):
    named = genres.filter(
        (pl.col("level") >= 0)
        & pl.col("name").is_not_null()
        & ~pl.col("name").str.starts_with("unnamed ")
        & (pl.col("name").str.len_chars() > 0)
    )
    labels = reference.select(pl.col("artist_mbid").alias("artist"), "genre_qid", "genre").unique()
    counts = (
        memberships.filter(pl.col("score") > 0)
        .select("artist", pl.col("genre").alias("id"))
        .unique()
        .join(labels, on="artist")
        .group_by("id", "genre_qid", "genre")
        .len()
    )
    common = (
        counts.sort(["id", "len", "genre_qid"], descending=[False, True, False])
        .unique("id", keep="first", maintain_order=True)
        .join(named.select("id", "name"), on="id")
    )
    names, truth = common["name"].to_list(), common["genre"].to_list()
    shuffled = np.random.default_rng(seed).permutation(names)
    actual = [name_agreement(name, label)[1] for name, label in zip(names, truth, strict=True)]
    random = [name_agreement(name, label)[1] for name, label in zip(shuffled, truth, strict=True)]
    return {
        "token_match_share": mean([v > 0 for v in actual]),
        "random": mean([v > 0 for v in random]),
        "token_jaccard": mean(actual),
        "random_token_jaccard": mean(random),
        "clusters": len(common),
        "named_clusters": len(named),
    }


def layout_score(reference, layout, members, ceiling, seed=42, k=10):
    if k < 1:
        raise ValueError("k must be positive")
    joined = (
        members.select("genre", "artist_mbid")
        .unique()
        .join(reference.select("artist_mbid", "genre_qid"), on="artist_mbid")
    )
    frame = (
        layout.select("genre", "x", "y")
        .drop_nulls()
        .join(ceiling.select("genre", pl.col("x").alias("cx"), pl.col("y").alias("cy")), on="genre")
        .filter(pl.all_horizontal(pl.col("x", "y", "cx", "cy").is_finite()))
        .sort("genre")
    )
    frame = frame.join(joined.select("genre").unique(), on="genre").sort("genre")
    if len(frame) < 2:
        return {
            "neighbor_cosine@10": None,
            "enao_ceiling": None,
            "random": None,
            "genres": len(frame),
        }
    gi = {g: i for i, g in enumerate(frame["genre"])}
    qi = {q: i for i, q in enumerate(sorted(set(joined["genre_qid"])))}
    counts = joined.filter(pl.col("genre").is_in(list(gi))).group_by("genre", "genre_qid").len()
    vectors = sparse.csr_matrix(
        (
            counts["len"].to_numpy().astype(float),
            ([gi[g] for g in counts["genre"]], [qi[q] for q in counts["genre_qid"]]),
        ),
        shape=(len(frame), len(qi)),
    )
    norms = np.sqrt(np.asarray(vectors.multiply(vectors).sum(axis=1)).ravel())
    vectors = (sparse.diags(1 / np.maximum(norms, 1e-12)) @ vectors).tocsr()
    width = min(k, len(frame) - 1)
    rows = np.repeat(np.arange(len(frame)), width)

    def score(points):
        neighbors = KDTree(points).query(points, k=width + 1)[1]
        ids = np.array([row[row != i][:width] for i, row in enumerate(neighbors)])
        return float(vectors[rows].multiply(vectors[ids.ravel()]).sum() / len(rows))

    rng = np.random.default_rng(seed)
    random = rng.integers(len(frame) - 1, size=len(rows))
    random += random >= rows
    return {
        "neighbor_cosine@10": score(frame.select("x", "y").to_numpy()),
        "enao_ceiling": score(frame.select("cx", "cy").to_numpy()),
        "random": float(vectors[rows].multiply(vectors[random]).sum() / len(rows)),
        "genres": len(frame),
    }


def evaluate(config, run):
    reference = pl.read_parquet(Path(config["reference"]) / "wikidata.parquet")
    crosswalk = Path(config["crosswalk"])
    slices = {"all": reference, "independent": reference.filter(~pl.col("enao_linked"))}
    if crosswalk.exists():
        known = pl.read_parquet(crosswalk)["artist_mbid"]
        slices["artists_absent_enao"] = reference.filter(
            ~pl.col("artist_mbid").is_in(known.implode())
        )
    result = {
        "reference_sha256": hashlib.sha256(
            (Path(config["reference"]) / "wikidata.parquet").read_bytes()
        ).hexdigest(),
        "slices": {},
        "unavailable": {},
    }
    if not crosswalk.exists():
        result["unavailable"]["artists_absent_enao"] = "M2 crosswalk missing"
    available = {}
    for stage in ["m1", "m2", "naming", "layout"]:
        paths = {key: Path(value) for key, value in config[stage].items()}
        missing = [str(path) for path in paths.values() if not path.exists()]
        if missing:
            result["unavailable"][stage] = missing
            continue
        frames = {key: pl.read_parquet(path) for key, path in paths.items()}
        if stage == "layout":
            frames["members"] = (
                frames.pop("labels")
                .join(frames.pop("artists").select("item", "artist_mbid"), on="item")
                .select("genre", "artist_mbid")
            )
        available[stage] = frames
    for name, subset in slices.items():
        metrics = {
            "rows": len(subset),
            "artists": subset["artist_mbid"].n_unique(),
            "genres": subset["genre_qid"].n_unique(),
        }
        for stage, frames in available.items():
            if stage == "m1":
                metrics[stage] = similarity_score(subset, **frames, seed=config["seed"])
            elif stage == "m2":
                metrics[stage] = cluster_scores(subset, **frames, seed=config["seed"])
            elif stage == "naming":
                metrics[stage] = naming_score(subset, **frames, seed=config["seed"])
            else:
                metrics[stage] = layout_score(subset, **frames, seed=config["seed"])
        result["slices"][name] = metrics
    (run / "metrics.json").write_text(json.dumps(result, indent=2, allow_nan=False))
    log(run, "generalization", result)


def execute(stage, config, run):
    if stage == "ingest":
        ingest(config)
    elif stage == "eval":
        evaluate(config, run)
    else:
        raise ValueError("generalization supports ingest and eval only")
