import hashlib
import json
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from itertools import batched
from pathlib import Path

import numpy as np
import polars as pl

ROOT = Path("data/deezer")
RAW = ROOT / "responses.jsonl"


@dataclass(frozen=True)
class Artist:
    item: int
    name: str


def name_key(name: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", name).casefold().split())


def catalog(path: Path) -> dict[str, Artist]:
    artists = {}
    rows = pl.read_parquet(path).sort(["listeners", "item"], descending=[True, False])
    for item, name in rows.select("item", "artist_name").iter_rows():
        key = name_key(name)
        if key:
            artists.setdefault(key, Artist(item, name))
    return artists


def seeds(artists: dict[str, Artist], top: int, mid: int) -> list[Artist]:
    ordered = list(artists.values())
    tail = ordered[top : top + 15000]
    indices = np.random.default_rng(42).choice(len(tail), size=min(mid, len(tail)), replace=False)
    return [*ordered[:top], *(tail[i] for i in sorted(indices))]


def fetch(path: str) -> dict:
    request = urllib.request.Request(
        f"https://api.deezer.com/{path}", headers={"User-Agent": "OpenNoise local research"}
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        result = json.load(response)
    if "data" not in result:
        raise ValueError(f"Deezer {path}: {result.get('error', 'missing data')}")
    return result


def cached() -> dict[str, dict]:
    if not RAW.exists():
        return {}
    return {
        parsed["path"]: parsed["response"]
        for row in RAW.read_text().splitlines()
        if (parsed := json.loads(row))
    }


def search(name: str) -> str:
    return "search/artist?" + urllib.parse.urlencode({"q": name, "limit": 10})


def fetch_all(paths: Iterable[str], responses: dict[str, dict]) -> None:
    pending = [p for p in dict.fromkeys(paths) if p not in responses]
    with ThreadPoolExecutor(max_workers=8) as pool, RAW.open("a") as raw:
        for attempt in range(2):
            failed = []
            for batch in batched(pending, 8, strict=False):
                started = time.monotonic()
                before = len(responses)
                for path, future in [(p, pool.submit(fetch, p)) for p in batch]:
                    try:
                        value = future.result()
                    except (TimeoutError, urllib.error.URLError) as error:
                        print(f"Deezer request failed for {path}: {error}", flush=True)
                        failed.append(path)
                        continue
                    raw.write(json.dumps({"path": path, "response": value}) + "\n")
                    raw.flush()
                    responses[path] = value
                if before // 200 != len(responses) // 200:
                    print(f"{len(responses)} cached Deezer responses", flush=True)
                time.sleep(max(0.0, 1.15 - (time.monotonic() - started)))
            if not failed:
                return
            pending = failed
            if not attempt:
                time.sleep(5.1)
        raise RuntimeError(f"{len(pending)} Deezer requests failed twice")


def artist_ids(artists: list[Artist], responses: dict[str, dict]) -> dict[int, Artist]:
    matched = {}
    for artist in artists:
        for record in responses[search(artist.name)]["data"]:
            if name_key(record["name"]) == name_key(artist.name):
                matched.setdefault(record["id"], artist)
                break
    return matched


def related(deezer_id: int) -> str:
    return f"artist/{deezer_id}/related?limit=20"


def albums(deezer_id: int) -> str:
    return f"artist/{deezer_id}/albums?limit=10"


def ingest(path: Path, top: int, mid: int) -> None:
    ROOT.mkdir(parents=True, exist_ok=True)
    artists = seeds(catalog(path), top, mid)
    responses = cached()
    fetch_all((search(a.name) for a in artists), responses)
    matched = artist_ids(artists, responses)
    print(f"{len(matched)}/{len(artists)} seed artists matched", flush=True)
    fetch_all(("genre", *(p for id_ in matched for p in (related(id_), albums(id_)))), responses)
    (ROOT / "sample.json").write_text(
        json.dumps(
            {
                "seeds": len(artists),
                "top": top,
                "mid": mid,
                "artists_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "matched": {id_: a.item for id_, a in matched.items()},
            },
            indent=2,
        )
    )
