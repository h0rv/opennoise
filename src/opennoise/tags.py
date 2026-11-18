import datetime
import gzip
import hashlib
import json
import re
import shutil
import subprocess
import tarfile
import time
import tomllib
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import lxml.etree as etree
import numpy as np
import polars as pl
from scipy import sparse

from opennoise.evaluate import PROBES, colistening, heldout_sets
from opennoise.graph import normalize
from opennoise.metrics import overlap


def tag_name(value):
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def discogs_id(url):
    parsed = urlsplit(url)
    if parsed.hostname not in {"discogs.com", "www.discogs.com"}:
        return None
    match = re.fullmatch(r"/(?:[a-z]{2}/)?artist/(\d+)(?:-[^/]*)?/?", parsed.path)
    return int(match[1]) if match else None


def log(run, change, metrics, kept=False, note=""):
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    row = [
        datetime.datetime.now(datetime.UTC).isoformat(),
        commit,
        run.name,
        change,
        json.dumps(metrics, separators=(",", ":")),
        "kept" if kept else "discarded",
        note.replace("\n", " ").replace("\t", " "),
    ]
    with Path("experiments/results.tsv").open("a") as stream:
        stream.write("\t".join(row) + "\n")
    print(change, json.dumps(metrics), flush=True)


def download(name, path):
    sources = tomllib.loads(Path("sources.toml").read_text())["sources"]
    source = next(row for row in sources if row.get("name") == name)
    if not path.exists():
        part = path.with_suffix(path.suffix + ".part")
        subprocess.run(["curl", "-fL", "--retry", "3", source["url"], "-o", str(part)], check=True)
        part.rename(path)
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    if digest != source["sha256"]:
        raise ValueError(f"Checksum mismatch: {path}")


def execute(stage, config, run):
    start = time.monotonic()
    try:
        {"ingest": ingest, "build": build, "eval": evaluate}[stage](config, run)
        log(run, f"tags_{stage}", {"status": "ok", "seconds": time.monotonic() - start})
    except Exception as error:
        log(run, f"tags_{stage}", {"status": "failed", "error": str(error)})
        raise


def normalized_cache(config):
    sources = tomllib.loads(Path("sources.toml").read_text())["sources"]
    hashes = sorted(
        (row["name"], row["sha256"])
        for row in sources
        if row.get("name") in {"musicbrainz_artists", "discogs_releases"}
    )
    digest = hashlib.sha256(json.dumps(hashes).encode()).hexdigest()[:12]
    return Path(config["tags"]["cache"]) / digest


def musicbrainz(path, root):
    tags, links = [], []
    with tarfile.open(path, "r|xz") as archive:
        for member in archive:
            if not member.isfile() or Path(member.name).name != "artist":
                continue
            stream = archive.extractfile(member)
            if stream is None:
                continue
            for line in stream:
                artist = json.loads(line)
                mbid = artist["id"]
                for tag in artist.get("tags", []):
                    name = tag_name(tag["name"])
                    if name and tag["count"] > 0:
                        tags.append((mbid, name, float(tag["count"]), "musicbrainz"))
                for relation in artist.get("relations", []):
                    identifier = discogs_id(relation.get("url", {}).get("resource", ""))
                    if identifier is not None and identifier not in {194, 355}:
                        links.append((mbid, identifier))
    frame = pl.DataFrame(
        tags,
        schema={
            "artist_mbid": pl.String,
            "tag": pl.String,
            "weight": pl.Float32,
            "source": pl.String,
        },
        orient="row",
    )
    frame.write_parquet(root / "musicbrainz.parquet")
    pl.DataFrame(
        links, schema={"artist_mbid": pl.String, "discogs_id": pl.Int64}, orient="row"
    ).unique().write_parquet(root / "identity.parquet")


def discogs(path, root):
    identity = pl.read_parquet(root / "identity.parquet")
    wanted = set(identity["discogs_id"])
    counts = Counter()
    releases = 0
    with gzip.open(path, "rb") as stream:
        context = etree.iterparse(stream, events=("end",), tag="release", huge_tree=True)
        for _, release in context:
            ids = {int(node.text) for node in release.findall("artists/artist/id") if node.text}
            ids &= wanted
            if ids:
                styles = {
                    tag_name(node.text) for node in release.findall("styles/style") if node.text
                }
                for identifier in ids:
                    counts.update((identifier, style) for style in styles if style)
            releases += 1
            if releases % 1_000_000 == 0:
                print(
                    json.dumps({"discogs_releases": releases, "artist_styles": len(counts)}),
                    flush=True,
                )
            release.clear()
            if (parent := release.getparent()) is not None:
                while release.getprevious() is not None:
                    del parent[0]
    frame = pl.DataFrame(
        [(identifier, tag, count) for (identifier, tag), count in counts.items()],
        schema={"discogs_id": pl.Int64, "tag": pl.String, "weight": pl.Float32},
        orient="row",
    )
    frame.join(identity, on="discogs_id").group_by("artist_mbid", "tag").agg(
        pl.col("weight").sum()
    ).with_columns(pl.lit("discogs").alias("source")).select(
        "artist_mbid", "tag", "weight", "source"
    ).write_parquet(root / "discogs.parquet")
    return releases


def ingest(config, run):
    settings = config["tags"]
    root = Path(settings["cache"])
    root.mkdir(parents=True, exist_ok=True)
    normalized = normalized_cache(config)
    normalized.mkdir(exist_ok=True)
    for source, filename, target in [
        ("musicbrainz_artists", "artist.tar.xz", "musicbrainz"),
        ("discogs_releases", "discogs_releases.xml.gz", "discogs"),
    ]:
        outputs = ["identity.parquet"] if target == "musicbrainz" else []
        if target in settings["sources"]:
            outputs.append(f"{target}.parquet")
        if all((normalized / name).exists() for name in outputs):
            for name in outputs:
                shutil.copy2(normalized / name, run / name)
            continue
        start = time.monotonic()
        try:
            path = root / filename
            download(source, path)
            if target == "musicbrainz":
                musicbrainz(path, normalized)
                count = None
            else:
                count = discogs(path, normalized)
            for name in outputs:
                shutil.copy2(normalized / name, run / name)
            log(
                run,
                f"tags_ingest_{target}",
                {"status": "ok", "releases": count, "seconds": time.monotonic() - start},
            )
        except Exception as error:
            log(run, f"tags_ingest_{target}", {"status": "failed", "error": str(error)})
            raise


def vectors(tags, artists):
    tags = tags.join(artists.select("artist_mbid", "item"), on="artist_mbid")
    tags = tags.group_by("artist_mbid", "item", "tag").agg(pl.col("weight").sum())
    vocabulary = tags.select("tag").unique().sort("tag").with_row_index("column")
    tags = tags.join(vocabulary, on="tag")
    matrix = sparse.csr_matrix(
        (tags["weight"].to_numpy(), (tags["item"].to_numpy(), tags["column"].to_numpy())),
        shape=(len(artists), len(vocabulary)),
    )
    matrix.data = np.log1p(matrix.data)
    frequency = np.asarray((matrix > 0).sum(axis=0)).ravel()
    idf = np.log((1 + (matrix.getnnz(axis=1) > 0).sum()) / (1 + frequency)) + 1
    return normalize(matrix.multiply(idf).tocsr()).tocsr(), vocabulary


def agreement(matrix, items, neighbors):
    scores = np.empty(len(items), dtype=np.float32)
    for start in range(0, len(items), 100_000):
        stop = start + 100_000
        scores[start:stop] = np.asarray(
            matrix[items[start:stop]].multiply(matrix[neighbors[start:stop]]).sum(axis=1)
        ).ravel()
    return np.clip(scores, 0, 1)


def build(config, run):
    settings = config["tags"]
    base = Path(settings["base_run"])
    artists = pl.read_parquet(base / "artists.parquet")
    edges = pl.read_parquet(base / "tfidf.parquet")
    coverage = {}
    for source in settings["sources"]:
        tags = pl.read_parquet(run / f"{source}.parquet")
        matrix, vocabulary = vectors(tags, artists)
        sparse.save_npz(run / f"{source}.npz", matrix)
        vocabulary.write_parquet(run / f"{source}_vocabulary.parquet")
        scores = agreement(matrix, edges["item"].to_numpy(), edges["neighbor"].to_numpy())
        np.save(run / f"{source}_agreement.npy", scores)
        present = matrix.getnnz(axis=1) > 0
        covered = present[edges["item"].to_numpy()] & present[edges["neighbor"].to_numpy()]
        np.save(run / f"{source}_covered.npy", covered)
        coverage[source] = {
            "artists": int(present.sum()),
            "artist_fraction": float(present.mean()),
            "edge_fraction": float(covered.mean()),
            "vocabulary": len(vocabulary),
        }
    pl.concat([pl.read_parquet(run / f"{source}.parquet") for source in coverage]).join(
        artists.select("artist_mbid"), on="artist_mbid"
    ).write_parquet(run / "artist_tags.parquet")
    artists.write_parquet(run / "artists.parquet")
    (run / "coverage.json").write_text(json.dumps(coverage, indent=2))
    print(json.dumps(coverage), flush=True)


def graph_frame(edges, scores):
    return edges.with_columns(pl.Series("score", scores)).sort(
        ["item", "score", "neighbor"], descending=[False, True, False]
    )


def graph_matrix(edges, n):
    return sparse.csr_matrix(
        (edges["score"].to_numpy(), (edges["item"].to_numpy(), edges["neighbor"].to_numpy())),
        shape=(n, n),
    )


def evaluate(config, run):
    settings = config["tags"]
    base = Path(settings["base_run"])
    artists = pl.read_parquet(base / "artists.parquet")
    edges = pl.read_parquet(base / "tfidf.parquet")
    scores = edges["score"].to_numpy()
    sets = heldout_sets(base, config["seed"])
    order = np.random.default_rng(config["seed"]).permutation(len(sets))
    cut = int(len(sets) * settings["validation_fraction"])
    if not 0 < cut < len(sets):
        raise ValueError("Validation and test must both contain users")
    validation = [sets[i] for i in order[:cut]]
    test = [sets[i] for i in order[cut:]]
    coverage = json.loads((run / "coverage.json").read_text())
    signals = {name: np.load(run / f"{name}_agreement.npy") for name in settings["sources"]}
    if len(signals) > 1:
        denominator = sum(np.load(run / f"{name}_covered.npy").astype(np.int8) for name in signals)
        signals["combined"] = sum(signals.values()) / np.maximum(denominator, 1)
    results: dict[str, dict[str, Any]] = {}
    best, best_score = "tfidf", -np.inf
    candidates = [("tfidf", None, 0)] + [
        (f"tags_{source}_{weight:g}", signal, weight)
        for source, signal in signals.items()
        for weight in settings["weights"]
    ]
    for method, signal, weight in candidates:
        try:
            weighted = scores if signal is None else scores * (1 + weight * signal)
            metrics = colistening(
                graph_matrix(edges.with_columns(pl.Series("score", weighted)), len(artists)),
                validation,
            )
            results[method] = {"validation": metrics}
            if signal is not None and metrics["ndcg@50"] > best_score:
                best, best_score = method, metrics["ndcg@50"]
        except Exception as error:
            results[method] = {"status": "failed", "error": str(error)}
        log(run, method, results[method], note="validation sweep; fixed M1 top-50 candidates")
    if not np.isfinite(best_score):
        raise ValueError("No evaluated models")
    selected = next(row for row in candidates if row[0] == best)
    weighted = scores if selected[1] is None else scores * (1 + selected[2] * selected[1])
    output = graph_frame(edges, weighted)
    finalists = {"tfidf": edges, best: output}
    for method, frame in finalists.items():
        results[method]["test"] = colistening(graph_matrix(frame, len(artists)), test)
    mbids, names = artists["artist_mbid"].to_list(), artists["artist_name"].to_list()
    references = json.loads((base / "labs.json").read_text())
    probe_lines = []
    for method, frame in finalists.items():
        ordered = frame.sort(["item", "score", "neighbor"], descending=[False, True, False])
        neighbors = ordered["neighbor"].to_numpy().reshape(len(artists), -1)
        nonempty = [(index, ref) for index, ref, error in references if ref and not error]
        results[method]["labs"] = {"requested": len(references), "nonempty": len(nonempty)}
        for k in [10, 50]:
            values = [
                overlap([mbids[i] for i in neighbors[index]], reference, k)
                for index, reference in nonempty
            ]
            results[method]["labs"][f"overlap@{k}"] = float(np.mean(values)) if values else None
        probe_lines.append(method)
        for probe in PROBES:
            matches = [i for i, name in enumerate(names) if name.casefold() == probe.casefold()]
            top = ", ".join(names[i] for i in neighbors[matches[0], :10]) if matches else "absent"
            probe_lines.append(f"{probe}: {top}")
    graph_frame(finalists[best], finalists[best]["score"].to_numpy()).write_parquet(
        run / "similar.parquet"
    )
    (run / "probes.txt").write_text("\n".join(probe_lines) + "\n")
    (run / "best.json").write_text(
        json.dumps(
            {
                "method": best,
                "validation_method": best,
                "coverage": coverage,
                "metrics": results[best],
            },
            indent=2,
        )
    )
    (run / "metrics.json").write_text(json.dumps(results, indent=2))
    for method in finalists:
        log(
            run,
            f"{method}_test",
            results[method],
            method == best,
            "selected by validation nDCG; untouched test users; no candidate expansion",
        )
