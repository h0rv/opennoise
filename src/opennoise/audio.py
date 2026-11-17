import concurrent.futures
import datetime
import importlib
import json
import subprocess
import tarfile
import tempfile
import time
import tomllib
import urllib.parse
import urllib.request
from pathlib import Path

import numpy as np
import polars as pl
from scipy import sparse

from opennoise.evaluate import PROBES, colistening, heldout_sets
from opennoise.graph import neighbors, normalize

ROOT = Path("data/audio")
LOWLEVEL = {
    "lowlevel": ["average_loudness", "dynamic_complexity", "mfcc_zero_mean"],
    "rhythm": ["bpm", "danceability", "onset_rate"],
    "tonal": ["tuning_frequency", "tuning_equal_tempered_deviation"],
}


def source(name):
    return next(
        s
        for s in tomllib.loads(Path("sources.toml").read_text())["sources"]
        if s.get("name") == name
    )


def download(url):
    target = ROOT / Path(urllib.parse.urlparse(url).path).name
    if not target.exists():
        subprocess.run(["curl", "-fsSL", "-o", f"{target}.part", url], check=True)
        Path(f"{target}.part").rename(target)
    return target


def extract(archive, pattern, target):
    command = (
        f"zstd -dc '{archive}' | tar --occurrence=1 -xOf - --wildcards '{pattern}' > '{target}'"
    )
    subprocess.run(["bash", "-c", command], check=True)


def recordings():
    target = ROOT / "recordings.parquet"
    if target.exists():
        return target
    archive = download(source("canonical")["url"])
    raw = ROOT / "canonical.csv"
    extract(archive, "*canonical_musicbrainz_data.csv", raw)
    (
        pl.scan_csv(raw, infer_schema=False)
        .select("recording_mbid", pl.col("artist_mbids").str.split(",").alias("artist_mbid"))
        .unique("recording_mbid")
        .explode("artist_mbid")
        .sink_parquet(target)
    )
    raw.unlink()
    return target


def lowlevel():
    target = ROOT / "lowlevel.parquet"
    if target.exists():
        return target
    url = source("acousticbrainz_lowlevel")["url"]
    frames = []
    for part, columns in LOWLEVEL.items():
        raw = ROOT / f"{part}.csv"
        if not raw.exists():
            extract(download(url.format(part=part)), "*.csv", raw)
        frames.append(
            pl.scan_csv(raw, infer_schema=False).select(
                "mbid", "submission_offset", *[pl.col(c).cast(pl.Float64) for c in columns]
            )
        )
    data = frames[0]
    for frame in frames[1:]:
        data = data.join(frame, on=["mbid", "submission_offset"])
    data.drop("submission_offset").group_by("mbid").mean().sink_parquet(target)
    for part in LOWLEVEL:
        (ROOT / f"{part}.csv").unlink()
    return target


def highlevel_part(index):
    target = ROOT / "highlevel" / f"{index:02d}.parquet"
    if target.exists():
        return target
    url = source("acousticbrainz_highlevel")["url"].format(part=index)
    process = subprocess.Popen(
        ["bash", "-c", f"curl -fsSL '{url}' | zstd -dc"], stdout=subprocess.PIPE
    )
    mbids, rows, columns = [], [], None
    with tarfile.open(fileobj=process.stdout, mode="r|") as archive:
        for member in archive:
            if not member.isfile() or not member.name.endswith(".json"):
                continue
            file = archive.extractfile(member)
            if file is None:
                continue
            models = json.load(file)["highlevel"]
            values = {
                f"{model}_{name}": value["all"][name]
                for model, value in models.items()
                for name in sorted(value["all"])[: -1 if len(value["all"]) == 2 else None]
            }
            columns = columns or sorted(values)
            mbids.append(Path(member.name).name[:36])
            rows.append([values.get(c, np.nan) for c in columns])
    if process.wait() != 0:
        raise RuntimeError(f"highlevel part {index} failed")
    frame = pl.DataFrame(np.array(rows, dtype=np.float32), schema=columns, orient="row")
    frame = frame.with_columns(pl.Series("mbid", mbids)).group_by("mbid").mean()
    frame.write_parquet(target.with_suffix(".part"))
    target.with_suffix(".part").rename(target)
    return target


def highlevel():
    (ROOT / "highlevel").mkdir(parents=True, exist_ok=True)
    with concurrent.futures.ProcessPoolExecutor(max_workers=6) as pool:
        return list(pool.map(highlevel_part, range(30)))


def ingest():
    ROOT.mkdir(parents=True, exist_ok=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        jobs = [pool.submit(f) for f in (recordings, lowlevel, highlevel)]
        return [job.result() for job in jobs]


def get_json(url):
    for attempt in range(5):
        with urllib.request.urlopen(url, timeout=30) as response:
            data = json.load(response)
        if data.get("error", {}).get("code") != 4:
            return data
        time.sleep(2 + attempt * 2)
    return data


def preview_urls(name, limit):
    query = urllib.parse.urlencode({"q": name, "limit": 10})
    matches = [
        a
        for a in get_json(f"https://api.deezer.com/search/artist?{query}").get("data", [])
        if a["name"].casefold() == name.casefold()
    ]
    if not matches:
        return []
    best = max(matches, key=lambda a: a.get("nb_fan", 0))
    top = get_json(f"https://api.deezer.com/artist/{best['id']}/top?limit={limit}")
    return [t["preview"] for t in top.get("data", []) if t.get("preview")]


def load_model():
    global MODEL, MEL
    import essentia
    import onnxruntime

    es = importlib.import_module("essentia.standard")
    essentia.log.infoActive = False
    essentia.log.warningActive = False
    options = onnxruntime.SessionOptions()
    options.intra_op_num_threads = 2
    MODEL = onnxruntime.InferenceSession(str(download(source("effnet")["url"])), options)
    MEL = es.TensorflowInputMusiCNN()


def embed(url):
    es = importlib.import_module("essentia.standard")
    with tempfile.NamedTemporaryFile(suffix=".mp3") as clip:
        with urllib.request.urlopen(url, timeout=30) as response:
            clip.write(response.read())
        clip.flush()
        audio = es.MonoLoader(filename=clip.name, sampleRate=16000, resampleQuality=4)()
    frames = np.array(
        [MEL(f) for f in es.FrameGenerator(audio, frameSize=512, hopSize=256, startFromZero=True)]
    )
    if len(frames) < 128:
        return None
    starts = np.linspace(0, len(frames) - 128, 8).astype(int)
    patches = np.stack([frames[s : s + 128] for s in starts]).astype(np.float32)
    styles, embeddings = MODEL.run(["activations", "embeddings"], {"melspectrogram": patches})
    return np.asarray(embeddings).mean(0), np.asarray(styles).mean(0)


def preview_artist(args):
    mbid, name, limit = args
    try:
        results = [r for r in map(embed, preview_urls(name, limit)) if r is not None]
    except Exception as error:
        return mbid, None, None, 0, str(error)
    if not results:
        return mbid, None, None, 0, None
    embeddings, styles = zip(*results, strict=True)
    return mbid, np.mean(embeddings, 0), np.mean(styles, 0), len(results), None


def previews(artists, config):
    folder = ROOT / "previews"
    folder.mkdir(parents=True, exist_ok=True)
    done = set()
    if any(folder.iterdir()):
        done = set(pl.read_parquet(folder / "*.parquet")["artist_mbid"].to_list())
    rng = np.random.default_rng(config["seed"])
    strata = np.array_split(np.arange(len(artists)), 3)
    size = config["audio"]["preview_artists"] // 3
    sample = np.concatenate([rng.choice(s, min(len(s), size), replace=False) for s in strata])
    probes = artists.with_row_index("row").filter(
        pl.col("artist_name").str.to_lowercase().is_in([p.lower() for p in PROBES])
    )["row"]
    rows = artists[np.unique(np.concatenate([probes.to_numpy(), sample]))]
    todo = [
        (m, n, config["audio"]["preview_tracks"])
        for m, n in rows.select("artist_mbid", "artist_name").iter_rows()
        if m not in done
    ]
    with concurrent.futures.ProcessPoolExecutor(max_workers=4, initializer=load_model) as pool:
        for start in range(0, len(todo), 200):
            results = list(pool.map(preview_artist, todo[start : start + 200]))
            pl.DataFrame(
                {
                    "artist_mbid": [r[0] for r in results],
                    "embedding": [None if r[1] is None else r[1].tolist() for r in results],
                    "styles": [None if r[2] is None else r[2].tolist() for r in results],
                    "tracks": [r[3] for r in results],
                    "error": [r[4] for r in results],
                },
                schema_overrides={
                    "embedding": pl.List(pl.Float32),
                    "styles": pl.List(pl.Float32),
                    "error": pl.String,
                },
            ).write_parquet(folder / f"{time.time_ns()}.parquet")
            print("previews", start + len(results), len(todo), flush=True)
    return pl.read_parquet(folder / "*.parquet").unique("artist_mbid")


def aggregate(features, artists, min_recordings):
    columns = [c for c in features.collect_schema().names() if c != "mbid"]
    return (
        features.with_columns(pl.col(columns).fill_nan(None))
        .join(pl.scan_parquet(recordings()), left_on="mbid", right_on="recording_mbid")
        .join(artists.lazy().select("artist_mbid", "item"), on="artist_mbid")
        .group_by("item", "artist_mbid")
        .agg(*[pl.col(c).mean() for c in columns], pl.len().alias("recordings"))
        .filter(pl.col("recordings") >= min_recordings)
        .sort("item")
        .collect(engine="streaming")
    )


def feature_columns(frame):
    return [c for c in frame.columns if c not in ("item", "artist_mbid", "recordings")]


def standardize(matrix):
    matrix = np.where(np.isnan(matrix), np.nanmean(matrix, axis=0), matrix)
    matrix = (matrix - matrix.mean(0)) / np.maximum(matrix.std(0), 1e-9)
    return (matrix / np.maximum(np.linalg.norm(matrix, axis=1, keepdims=True), 1e-12)).astype(
        np.float32
    )


def signals(config, graph, run):
    artists = pl.read_parquet(graph / "artists.parquet")
    minimum = config["audio"]["min_recordings"]
    low = aggregate(pl.scan_parquet(lowlevel()), artists, minimum)
    high = aggregate(
        pl.concat([pl.scan_parquet(p) for p in highlevel()], how="diagonal"), artists, minimum
    )
    high.write_parquet(run / "artist_audio.parquet")
    found = previews(artists, config).filter(pl.col("embedding").is_not_null())
    found = found.join(artists.select("artist_mbid", "item"), on="artist_mbid").sort("item")
    both = low.join(high.drop("artist_mbid", "recordings"), on="item")
    result = {
        "ab_low": (low["item"].to_numpy(), low.select(feature_columns(low)).to_numpy()),
        "ab_high": (high["item"].to_numpy(), high.select(feature_columns(high)).to_numpy()),
        "ab_all": (both["item"].to_numpy(), both.select(feature_columns(both)).to_numpy()),
        "effnet": (found["item"].to_numpy(), np.array(found["embedding"].to_list())),
        "effnet_styles": (
            found["item"].to_numpy(),
            np.log(np.array(found["styles"].to_list()) + 1e-4),
        ),
    }
    return {name: (items, standardize(matrix)) for name, (items, matrix) in result.items()}


def listening(run):
    matrix = sparse.load_npz(run / "train.npz")
    weighted = matrix.copy()
    weighted.data = np.log1p(weighted.data)
    idf = np.log1p(matrix.shape[1] / np.maximum(np.diff(matrix.indptr), 1))
    return normalize((sparse.diags(idf) @ weighted).T.tocsr())


def to_graph(items, ids, scores, n):
    return sparse.csr_matrix(
        (
            np.maximum(scores.ravel(), 0),
            (np.repeat(items, ids.shape[1]), items[ids.ravel()]),
        ),
        shape=(n, n),
    )


def rerank(vectors, ids, scores, weight, k):
    audio = np.einsum("id,ikd->ik", vectors, vectors[ids])
    fused = (1 - weight) * scores + weight * audio
    order = np.argsort(-fused, axis=1, kind="stable")[:, :k]
    return np.take_along_axis(ids, order, 1), np.take_along_axis(fused, order, 1)


def score(name, items, vectors, listen, sets, artists, config):
    n = listen.shape[0]
    k = config["neighbors"]
    rng = np.random.default_rng(config["seed"])
    mask = np.zeros(n, dtype=bool)
    mask[items] = True
    subset = [(v[mask[v]], h[mask[h]]) for v, h in sets]
    subset = [(v, h) for v, h in subset if len(v) and len(h)]
    listen_ids, listen_scores = neighbors(listen[items], 2 * k)
    audio_ids, audio_scores = neighbors(vectors, k)
    random_ids = rng.integers(0, len(items), size=(len(items), 10))
    near = np.einsum("id,ikd->ik", vectors, vectors[listen_ids[:, :10]])
    far = np.einsum("id,ikd->ik", vectors, vectors[random_ids])
    listeners = artists["listeners"].to_numpy()
    common = {
        "artists": len(items),
        "coverage": len(items) / n,
        "listen_coverage": float(listeners[items].sum() / listeners.sum()),
        "dims": vectors.shape[1],
    }
    audio = colistening(to_graph(items, audio_ids, audio_scores, n), subset)
    wins = (near[:, :, None] > far[:, None, :]).mean((1, 2))
    tail = listeners[items] <= np.quantile(listeners, 1 / 3)
    audio["listen_auc"] = float(wins.mean())
    audio["tail_auc"] = float(wins[tail].mean()) if tail.any() else None
    audio["overlap@10"] = float(
        np.mean(
            [
                len(set(a[:10]) & set(b[:10])) / 10
                for a, b in zip(audio_ids, listen_ids, strict=True)
            ]
        )
    )
    audio["random_overlap@10"] = 10 / (len(items) - 1)
    rows = {name: common | audio}
    base = colistening(to_graph(items, listen_ids[:, :k], listen_scores[:, :k], n), subset)
    rows[f"{name}_listen"] = common | base
    for weight in config["audio"]["fusion_weights"]:
        fused = colistening(
            to_graph(items, *rerank(vectors, listen_ids, listen_scores, weight, k), n), subset
        )
        rows[f"{name}_fusion_{weight}"] = common | fused
    names = artists["artist_name"].to_list()
    position = {item: i for i, item in enumerate(items)}
    probes = [name]
    for probe in PROBES:
        index = next((i for i in items if names[i].casefold() == probe.casefold()), None)
        top = (
            ", ".join(names[items[j]] for j in audio_ids[position[index], :10])
            if index is not None
            else "absent"
        )
        probes.append(f"{probe}: {top}")
    return rows, probes


def evaluate(config, run):
    graph = Path("runs") / config["audio"]["listening_run"]
    artists = pl.read_parquet(graph / "artists.parquet")
    listen = listening(graph)
    sets = heldout_sets(graph, config["seed"])
    results, probes = {}, []
    for name, (items, vectors) in signals(config, graph, run).items():
        start = time.monotonic()
        rows, lines = score(name, items, vectors, listen, sets, artists, config)
        for row in rows.values():
            row["eval_seconds"] = time.monotonic() - start
        results |= rows
        probes += lines
        print(name, json.dumps(rows[name]), flush=True)
    (run / "audio_metrics.json").write_text(json.dumps(results, indent=2))
    (run / "audio_probes.txt").write_text("\n".join(probes) + "\n")
    best = max(signals_names(results), key=lambda m: results[m]["listen_auc"])
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    with Path("experiments/results.tsv").open("a") as stream:
        for method, metrics in results.items():
            base = results.get(method.split("_fusion_")[0] + "_listen")
            kept = method == best or (
                "_fusion_" in method and base and metrics["ndcg@50"] > base["ndcg@50"]
            )
            row = [
                datetime.datetime.now(datetime.UTC).isoformat(),
                commit,
                run.name,
                method,
                json.dumps(metrics, separators=(",", ":")),
                "kept" if kept else "discarded",
                "audio vs listening on artists with that signal; held-out users restricted to them",
            ]
            stream.write("\t".join(row) + "\n")


def signals_names(results):
    return [m for m in results if not m.endswith("_listen") and "_fusion_" not in m]
