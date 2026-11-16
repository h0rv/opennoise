import json
import subprocess
import tomllib
from pathlib import Path

import polars as pl


def ingest():
    root = Path("data")
    root.mkdir(exist_ok=True)
    target = root / "listens.parquet"
    if target.exists():
        return
    raw = root / "artists_all_time.jsonl"
    if not raw.exists():
        url = tomllib.loads(Path("sources.toml").read_text())["sources"][0]["url"]
        command = (
            f"curl -fL '{url}' | zstd -dc | "
            "tar --occurrence=1 -xOf - --wildcards '*/lbdump/statistics/artists_all_time.jsonl' "
            f"> '{raw}.part'"
        )
        subprocess.run(["bash", "-c", command], check=True)
        Path(f"{raw}.part").rename(raw)
    parts = root / "parts"
    parts.mkdir(exist_ok=True)
    rows = []
    index = 0
    with raw.open() as stream:
        for line in stream:
            record = json.loads(line)
            for artist in record["data"]:
                if artist.get("artist_mbid") and artist["listen_count"] > 0:
                    rows.append(
                        (
                            record["user_id"],
                            artist["artist_mbid"],
                            artist["artist_name"],
                            artist["listen_count"],
                        )
                    )
            if len(rows) >= 250_000:
                write_part(rows, parts, index)
                rows = []
                index += 1
    if rows:
        write_part(rows, parts, index)
    pl.scan_parquet(parts / "*.parquet").sink_parquet(target.with_suffix(".part"))
    target.with_suffix(".part").rename(target)
    for part in parts.iterdir():
        part.unlink()
    parts.rmdir()


def write_part(rows, parts, index):
    pl.DataFrame(
        rows,
        schema=[
            ("user", pl.Int64),
            ("artist_mbid", pl.String),
            ("artist_name", pl.String),
            ("count", pl.Int64),
        ],
        orient="row",
    ).write_parquet(parts / f"{index:05d}.parquet")
