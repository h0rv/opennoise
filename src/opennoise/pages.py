import argparse
import gzip
import json
from multiprocessing import get_context
from pathlib import Path


def rounded(value: str) -> float:
    return round(float(value), 4)


def pack_file(paths: tuple[Path, Path]) -> None:
    source, target = paths
    data = json.loads(source.read_bytes(), parse_float=rounded)
    if source.parent.name == "artists" and isinstance(data, dict):
        data["similar"] = data["similar"][:20]
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
