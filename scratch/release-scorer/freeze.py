import argparse
import hashlib
import json
import shutil
from pathlib import Path

import numpy as np
import polars as pl


def main():
    parser = argparse.ArgumentParser(
        description="Rebuild frozen scorer inputs from shipping sources"
    )
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--original-release", type=Path, required=True)
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--artists", type=Path, required=True)
    parser.add_argument("--wikidata", type=Path, required=True)
    parser.add_argument("--map", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parent)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    original = json.loads((args.original_release / "genres.json").read_text())
    identifiers = {row["name"]: row["id"] for row in original if " · " not in row["name"]}
    with np.load(args.inputs, allow_pickle=False) as data:
        indices = data["eval_ids"]
        names = data["names"][indices]
        heldout = data["heldout"][indices]
        pool = [{"id": identifiers[name], "original_name": str(name)} for name in names]
        np.savez_compressed(args.output / "vectors.npz", vectors=data["vectors"][indices])
    (args.output / "pool.json").write_text(json.dumps(pool, indent=2) + "\n")
    (args.output / "heldout-ids.txt").write_text(
        "".join(row["id"] + "\n" for row, test in zip(pool, heldout, strict=True) if test)
    )
    members = (
        pl.read_parquet(args.labels)
        .join(pl.read_parquet(args.artists).select("item", "artist_mbid"), on="item")
        .select("genre", "artist_mbid")
        .unique()
    )
    members.write_parquet(args.output / "members.parquet")
    shutil.copyfile(args.wikidata, args.output / "wikidata.parquet")
    shutil.copyfile(args.map, args.output / "map.parquet")
    sources = {
        key: {
            "path": str(path),
            "bytes": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
        for key, path in {
            "inputs": args.inputs,
            "original_genres": args.original_release / "genres.json",
            "labels": args.labels,
            "artists": args.artists,
            "wikidata": args.wikidata,
            "map": args.map,
        }.items()
    }
    (args.output / "sources.json").write_text(json.dumps(sources, indent=2) + "\n")
    print(f"Frozen {len(pool)} stable IDs, {int(heldout.sum())} held-out IDs")


if __name__ == "__main__":
    main()
