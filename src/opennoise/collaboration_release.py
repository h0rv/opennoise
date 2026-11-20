import argparse
import json
import tomllib
from pathlib import Path

import polars as pl

from opennoise.artist_identity import (
    artist_alias_table,
    canonicalize,
    collaboration_table,
    identity_table,
    write,
)
from opennoise.graph import heldout_users


def listener_updates(raw, credited, published, config):
    users = raw.select("user").unique().sort("user").collect()["user"]
    heldout = pl.Series(heldout_users(users.to_numpy(), config))
    training = ~pl.col("user").is_in(heldout.implode())
    pair = ["user", "artist_mbid"]
    extra = (
        credited.filter(training & pl.col("collaboration_credit"))
        .join(published.lazy(), on="artist_mbid", how="semi")
        .select(pair)
        .unique()
        .collect(engine="streaming")
    )
    direct = (
        raw.filter(training)
        .join(extra.select("artist_mbid").unique().lazy(), on="artist_mbid", how="semi")
        .select(pair)
        .unique()
        .collect(engine="streaming")
    )
    changes = (
        extra.join(direct, on=pair, how="anti")
        .group_by("artist_mbid")
        .len("added")
        .join(direct.group_by("artist_mbid").len("baseline"), on="artist_mbid", how="left")
        .join(published, on="artist_mbid")
    )
    updates = {}
    for artist, added, baseline, current in changes.iter_rows():
        baseline = baseline or 0
        updated = baseline + added
        if current not in {baseline, updated}:
            raise ValueError(f"Could not reproduce the published listener count for {artist}")
        if updated != current:
            updates[artist] = updated
    return updates


def refresh(root: Path, release_id: str, raw, credited, config) -> dict[str, int]:
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    search_path = root / manifest["search"]
    search = json.loads(search_path.read_text())
    published = pl.DataFrame(
        [(row["id"], row.get("listeners")) for row in search if row["kind"] == "artist"],
        schema={"artist_mbid": pl.String, "listeners": pl.Int64},
        orient="row",
    )
    updates = listener_updates(raw, credited, published, config)
    if updates:
        for directory, feature in [("artists", "similar"), ("genres", "members")]:
            for path in (root / directory).glob("*.json"):
                detail = json.loads(path.read_bytes())
                artists = [row["artist"] for row in detail[feature] or []]
                if directory == "artists":
                    artists.append(detail["artist"])
                changed = False
                for artist in artists:
                    if artist["id"] in updates:
                        artist["listeners"] = updates[artist["id"]]
                        changed = True
                if changed:
                    write(path, detail)
        for row in search:
            if row["kind"] == "artist" and row["id"] in updates:
                row["listeners"] = updates[row["id"]]
        write(search_path, search)
    manifest["release_id"] = release_id
    write(manifest_path, manifest)
    return updates


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("release", type=Path)
    parser.add_argument("release_id")
    parser.add_argument("--config", type=Path, default=Path("configs/m1.toml"))
    args = parser.parse_args()
    raw = pl.scan_parquet("data/listens.parquet")
    credited = canonicalize(raw, identity_table(), collaboration_table(), artist_alias_table())
    updates = refresh(
        args.release, args.release_id, raw, credited, tomllib.loads(args.config.read_text())
    )
    print(json.dumps({"artists_updated": len(updates)}))


if __name__ == "__main__":
    main()
