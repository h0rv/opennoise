import concurrent.futures
import hashlib
import http.client
import json
import math
import shutil
import subprocess
import time
import tomllib
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import polars as pl

from opennoise.tags import log


def fetch(config, mbids, root):
    params = urllib.parse.urlencode(
        [("artist_mbids", mbid) for mbid in mbids] + [("algorithm", config["algorithm"])]
    )
    url = config["endpoint"] + "?" + params
    key = hashlib.sha256(url.encode()).hexdigest()
    path = root / f"{key}.json"
    if path.exists():
        return path
    request = urllib.request.Request(
        url, headers={"User-Agent": "opennoise/0.1 (https://github.com/h0rv/opennoise)"}
    )
    for attempt in range(config["retries"] + 1):
        delay = config["backoff"] * 2**attempt
        try:
            with urllib.request.urlopen(request, timeout=config["timeout"]) as response:
                rows = json.load(response)
            if not isinstance(rows, list):
                raise ValueError("Expected a similar-artists list")
            for row in rows:
                if not isinstance(row, dict):
                    raise ValueError("Invalid similar-artists row")
                if row.get("reference_mbid") is None:
                    continue
                score = row.get("score")
                if (
                    row["reference_mbid"] not in mbids
                    or not isinstance(row.get("artist_mbid"), str)
                    or isinstance(score, bool)
                    or not isinstance(score, (int, float))
                    or not math.isfinite(score)
                    or score < 0
                ):
                    raise ValueError("Invalid similar-artists identity or score")
            part = path.with_suffix(".part")
            part.write_text(json.dumps(rows, separators=(",", ":")))
            part.replace(path)
            return path
        except urllib.error.HTTPError as error:
            if error.code != 429 and not 500 <= error.code < 600:
                raise
            retry_after = error.headers.get("Retry-After", "")
            if retry_after.isdigit():
                delay = max(delay, float(retry_after))
            if attempt == config["retries"]:
                raise
            print(
                json.dumps({"http": error.code, "retry": attempt + 1, "delay": delay}), flush=True
            )
        except (urllib.error.URLError, TimeoutError, ConnectionError, http.client.HTTPException):
            if attempt == config["retries"]:
                raise
        time.sleep(delay)
    raise RuntimeError("Retries exhausted")


def ingest(config, run):
    artists = pl.read_parquet(Path(config["base_run"]) / "artists.parquet")
    mbids = artists.sort("item")["artist_mbid"].to_list()
    root = Path(config["cache"])
    batches = root / "batches"
    batches.mkdir(parents=True, exist_ok=True)
    size = config["batch_size"]
    chunks = [mbids[start : start + size] for start in range(0, len(mbids), size)]
    started = time.monotonic()
    paths = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=config["concurrency"]) as pool:
        remaining = iter(chunks)
        pending = set()
        while True:
            while len(pending) < config["concurrency"]:
                chunk = next(remaining, None)
                if chunk is None:
                    break
                pending.add(pool.submit(fetch, config, chunk, batches))
            if not pending:
                break
            done, pending = concurrent.futures.wait(
                pending, return_when=concurrent.futures.FIRST_COMPLETED
            )
            for future in done:
                try:
                    paths.append(future.result())
                except Exception as error:
                    print(json.dumps({"error": str(error)}), flush=True)
                    raise
                if len(paths) % 50 == 0 or len(paths) == len(chunks):
                    progress = {
                        "batches": len(paths),
                        "total": len(chunks),
                        "seconds": time.monotonic() - started,
                    }
                    (root / "progress.json").write_text(json.dumps(progress))
                    print(json.dumps(progress), flush=True)
    schema = {"reference_mbid": pl.String, "artist_mbid": pl.String, "score": pl.Float64}
    parts = []
    excluded = 0
    for start in range(0, len(paths), 100):
        rows = []
        for path in paths[start : start + 100]:
            for row in json.loads(path.read_text()):
                if row.get("reference_mbid") is None:
                    excluded += 1
                else:
                    rows.append({key: row[key] for key in schema})
        part = root / f"part-{start:05d}.parquet"
        pl.DataFrame(rows, schema=schema).write_parquet(part)
        parts.append(part)
    target = root / "similar.parquet"
    pl.scan_parquet(parts).group_by("reference_mbid", "artist_mbid").agg(
        pl.col("score").max()
    ).sink_parquet(target.with_suffix(".part"))
    target.with_suffix(".part").replace(target)
    manifest = {
        "algorithm": config["algorithm"],
        "endpoint": config["endpoint"],
        "license": "CC0",
        "artists_sha256": hashlib.sha256(
            (Path(config["base_run"]) / "artists.parquet").read_bytes()
        ).hexdigest(),
        "batches": len(paths),
        "excluded_missing_reference": excluded,
        "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
    }
    (root / "manifest.json").write_text(json.dumps(manifest, indent=2))
    log(run, "lb_sessions_ingest", manifest)


def fuse(artists, edges, similar, weight, k=50):
    if not 0 <= weight <= 1:
        raise ValueError("Weight must be between zero and one")
    base = edges.select("item", "neighbor", pl.col("score").alias("tfidf"))
    if base.group_by("item").len().filter(pl.col("len") < k).height:
        raise ValueError("Not enough TF-IDF neighbors for padding")
    lb = (
        similar.with_columns(
            (pl.col("score") / pl.col("score").max().over("reference_mbid").clip(1e-12)).alias("lb")
        )
        .join(
            artists.select("artist_mbid", "item"), left_on="reference_mbid", right_on="artist_mbid"
        )
        .join(
            artists.select("artist_mbid", pl.col("item").alias("neighbor")),
            on="artist_mbid",
        )
        .filter(pl.col("item") != pl.col("neighbor"))
        .group_by("item", "neighbor")
        .agg(pl.col("lb").max())
    )
    return (
        base.join(lb, on=["item", "neighbor"], how="full", coalesce=True)
        .with_columns(pl.col("tfidf", "lb").fill_null(0))
        .with_columns(((1 - weight) * pl.col("tfidf") + weight * pl.col("lb")).alias("score"))
        .sort(["item", "score", "tfidf", "neighbor"], descending=[False, True, True, False])
        .group_by("item", maintain_order=True)
        .head(k)
        .select("item", "neighbor", "score")
    )


def build_weight(config, run, weight):
    path = run / f"w{weight:g}"
    path.mkdir(exist_ok=True)
    base = Path(config["base_run"])
    manifest = json.loads((Path(config["cache"]) / "manifest.json").read_text())
    if (
        manifest["algorithm"] != config["algorithm"]
        or manifest["endpoint"] != config["endpoint"]
        or manifest["artists_sha256"]
        != hashlib.sha256((base / "artists.parquet").read_bytes()).hexdigest()
    ):
        raise ValueError("LB cache does not match configured source and artists")
    artists = pl.read_parquet(base / "artists.parquet")
    edges = pl.read_parquet(base / "tfidf.parquet")
    similar = pl.read_parquet(Path(config["cache"]) / "similar.parquet")
    fused = fuse(artists, edges, similar, weight)
    if fused.height != artists.height * 50:
        raise ValueError("Expected exactly 50 neighbors per artist")
    shutil.copyfile(base / "artists.parquet", path / "artists.parquet")
    fused.write_parquet(path / "tfidf.parquet")
    log(run, f"lb_sessions_build_w{weight:g}", {"weight": weight, "edges": fused.height})


def evaluate(config, run):
    gen_text = Path(config["gen_config"]).read_text()
    gen = tomllib.loads(gen_text)
    reference = Path(gen["reference"]) / "wikidata.parquet"
    if hashlib.sha256(reference.read_bytes()).hexdigest() != config["reference_sha256"]:
        raise ValueError("Wikidata reference differs from the frozen baseline")
    m2_text = Path(config["m2_config"]).read_text()
    m2 = tomllib.loads(m2_text)
    results = {}

    def score(weight):
        fused = run / f"w{weight:g}"
        if not (fused / "tfidf.parquet").exists():
            build_weight(config, run, weight)
        text = m2_text.replace(f'"{m2["m1"]}"', f'"{fused}"')
        path = run / f"m2-w{weight:g}.toml"
        path.write_text(text)
        for stage in ["build", "eval"]:
            subprocess.run(["uv", "run", "on", stage, str(path)], check=True)
        digest = hashlib.sha256(text.encode() + Path("sources.toml").read_bytes()).hexdigest()[:12]
        m2_run = Path("runs") / digest
        metrics = json.loads((m2_run / "fine_k20" / "metrics.json").read_text())
        results[weight] = {"m2_run": str(m2_run), "metrics": metrics}
        log(run, f"lb_sessions_en_w{weight:g}", metrics)

    for weight in config["weights"]:
        score(weight)
    best = max(results, key=lambda w: results[w]["metrics"]["genre_match"])
    if (
        best in {0.5, 1.0}
        and results[best]["metrics"]["genre_match"] > results[0.25]["metrics"]["genre_match"]
    ):
        score(0.75)
        best = max(results, key=lambda w: results[w]["metrics"]["genre_match"])
    selected = Path(results[best]["m2_run"]) / "fine_k20"
    gen_text = gen_text.replace(gen["m1"]["edges"], str(run / f"w{best:g}" / "tfidf.parquet"))
    for key in ["memberships", "genres"]:
        gen_text = gen_text.replace(gen["m2"][key], str(selected / f"{key}.parquet"))
    path = run / "gen-selected.toml"
    path.write_text(gen_text)
    subprocess.run(["uv", "run", "on", "eval", str(path)], check=True)
    digest = hashlib.sha256(gen_text.encode() + Path("sources.toml").read_bytes()).hexdigest()[:12]
    generalization = json.loads((Path("runs") / digest / "metrics.json").read_text())
    summary = {"weight": best, "weights": results, "generalization": generalization}
    (run / "metrics.json").write_text(json.dumps(summary, indent=2))
    log(run, "lb_sessions_selected", summary, note="selected on Every Noise genre match only")


def execute(stage, config, run):
    if stage == "ingest":
        ingest(config, run)
    elif stage == "build":
        for weight in config["weights"]:
            build_weight(config, run, weight)
    elif stage == "eval":
        evaluate(config, run)
    else:
        raise ValueError("LB sessions supports ingest, build and eval only")
