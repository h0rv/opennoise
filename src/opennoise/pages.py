import argparse
import gzip
import json
from collections import Counter
from functools import lru_cache
from math import log1p
from multiprocessing import get_context
from pathlib import Path
from typing import TypedDict


class Artist(TypedDict):
    id: str
    listeners: int | None


class Member(TypedDict):
    artist: Artist
    score: float


def rounded(value: str) -> float:
    return round(float(value), 4)


@lru_cache(maxsize=8192)
def artist_neighbors(root: Path, artist_id: str) -> tuple[tuple[str, float], ...]:
    data = json.loads((root / "artists" / f"{artist_id}.json").read_bytes())
    return tuple((row["artist"]["id"], row["score"]) for row in data["similar"] or ())


def rank_members(root: Path, members: list[Member]) -> None:
    scores = {row["artist"]["id"]: row["score"] for row in members}
    counts = Counter(scores.values())

    def rank(row: Member) -> tuple[float, float, int, str]:
        artist, score = row["artist"], row["score"]
        support = (
            sum(
                weight * scores.get(neighbor, 0.0)
                for neighbor, weight in artist_neighbors(root, artist["id"])
            )
            if counts[score] > 1
            else 0.0
        )
        listeners = artist["listeners"] or 0
        return -score, -support * log1p(listeners), -listeners, artist["id"]

    members.sort(key=rank)


def pack_file(paths: tuple[Path, Path]) -> None:
    source, target = paths
    data = json.loads(source.read_bytes(), parse_float=rounded)
    if source.parent.name == "artists" and data.get("similar"):
        data["similar"] = data["similar"][:20]
    if source.parent.name == "genres" and data.get("members"):
        # Break ties at the precision the site serves, without changing the release.
        rank_members(source.parent.parent, data["members"])
    payload = json.dumps(data, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    target.write_bytes(gzip.compress(payload.encode(), compresslevel=9, mtime=0))


def pack(source: Path, target: Path) -> None:
    if not source.is_dir():
        raise NotADirectoryError(source)
    if target.resolve().is_relative_to(source.resolve()):
        raise ValueError("Output must be outside the release directory")
    files = list(source.rglob("*.json"))
    for directory in {path.parent.relative_to(source) for path in files}:
        (target / directory).mkdir(parents=True, exist_ok=True)
    with get_context("spawn").Pool() as pool:
        for _ in pool.imap_unordered(
            pack_file, ((path, target / path.relative_to(source)) for path in files), chunksize=128
        ):
            pass


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("target", type=Path)
    args = parser.parse_args()
    pack(args.source, args.target)


if __name__ == "__main__":
    main()
