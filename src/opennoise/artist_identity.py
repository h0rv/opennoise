import argparse
import json
import tarfile
import tomllib
import unicodedata
import urllib.request
from pathlib import Path

import polars as pl


def extract_dump(root, url, names):
    members = {f"mbdump/{name}" for name in names}
    found = set()
    with urllib.request.urlopen(url, timeout=180) as response:
        with tarfile.open(fileobj=response, mode="r|bz2") as archive:
            for member in archive:
                if member.name in members:
                    archive.extract(member, root, filter="data")
                    found.add(member.name)
                    if found == members:
                        return
    raise ValueError(f"MusicBrainz tables missing: {members - found}")


def identity_table(root=Path("data/artist_identity")):
    root.mkdir(parents=True, exist_ok=True)
    cached = root / "identities.parquet"
    if cached.exists():
        return pl.read_parquet(cached)
    if not all((root / "mbdump" / name).exists() for name in ["artist", "artist_gid_redirect"]):
        sources = tomllib.loads(Path("sources.toml").read_text())["sources"]
        source = next(s for s in sources if s.get("name") == "artist_identity")
        extract_dump(root, source["url"], {"artist", "artist_gid_redirect"})
    artists = pl.scan_csv(
        root / "mbdump/artist",
        separator="\t",
        has_header=False,
        quote_char=None,
        infer_schema=False,
        null_values="\\N",
    ).select(
        pl.col("column_0").alias("mb_artist"),
        pl.col("column_1").alias("canonical_mbid"),
        pl.col("column_2").alias("canonical_name"),
        pl.col("column_13").alias("disambiguation"),
    )
    redirects = pl.scan_csv(
        root / "mbdump/artist_gid_redirect",
        separator="\t",
        has_header=False,
        quote_char=None,
        infer_schema=False,
    ).select(pl.col("column_0").alias("artist_mbid"), pl.col("column_1").alias("mb_artist"))
    merged = redirects.join(artists, on="mb_artist", how="left")
    if merged.filter(pl.col("canonical_mbid").is_null()).select(pl.len()).collect().item():
        raise ValueError("Unknown MusicBrainz redirect target")
    columns = ["artist_mbid", "canonical_mbid", "canonical_name", "disambiguation"]
    result = pl.concat(
        [
            artists.with_columns(pl.col("canonical_mbid").alias("artist_mbid")).select(columns),
            merged.select(columns),
        ]
    ).collect()
    if result["artist_mbid"].n_unique() != len(result):
        raise ValueError("Duplicate MusicBrainz artist identity")
    result.write_parquet(cached.with_suffix(".part"))
    cached.with_suffix(".part").rename(cached)
    return result


def popularity_redirects(artists):
    groups = {}
    for id_, artist in artists.items():
        name = " ".join(unicodedata.normalize("NFKC", artist["name"]).casefold().split())
        groups.setdefault(name, []).append(id_)
    redirects = {}
    for ids in groups.values():
        target = min(ids, key=lambda i: (-(artists[i]["listeners"] or 0), i))
        for id_ in ids:
            if (artists[id_]["listeners"] or 0) * 10 < (artists[target]["listeners"] or 0):
                redirects[id_] = target
    return redirects


def collaboration_table(root=Path("data/artist_identity")):
    cached = root / "collaborations.parquet"
    if cached.exists():
        return pl.read_parquet(cached)
    names = {"l_artist_artist", "link", "link_type"}
    if not all((root / "mbdump" / name).exists() for name in names):
        sources = tomllib.loads(Path("sources.toml").read_text())["sources"]
        source = next(s for s in sources if s.get("name") == "artist_identity")
        extract_dump(root, source["url"], names)

    def table(name, columns):
        return pl.scan_csv(
            root / "mbdump" / name,
            separator="\t",
            has_header=False,
            quote_char=None,
            infer_schema=False,
            null_values="\\N",
        ).select(pl.col(f"column_{i}").alias(label) for i, label in columns.items())

    types = table("link_type", {0: "type_id", 4: "entity0", 5: "entity1", 6: "type"}).filter(
        (pl.col("type") == "collaboration")
        & (pl.col("entity0") == "artist")
        & (pl.col("entity1") == "artist")
    )
    links = table("link", {0: "link", 1: "type_id"}).join(types, on="type_id")
    artists = table("artist", {0: "mb_artist", 1: "mbid"})
    result = (
        table("l_artist_artist", {1: "link", 2: "artist0", 3: "artist1"})
        .join(links, on="link")
        .join(
            artists.select(pl.col("mb_artist").alias("artist0"), pl.col("mbid").alias("member")),
            on="artist0",
        )
        .join(
            artists.select(
                pl.col("mb_artist").alias("artist1"), pl.col("mbid").alias("collaboration")
            ),
            on="artist1",
        )
        .select("collaboration", "member")
        .unique()
        .collect()
    )
    result.write_parquet(cached)
    return result


def cleanup_redirects(artists, collaborations=None):
    popularity = popularity_redirects(artists)
    remaining = {i: artist for i, artist in artists.items() if i not in popularity}
    members = {}
    if collaborations is not None:
        for collaboration, member in collaborations.iter_rows():
            member = popularity.get(member, member)
            if collaboration in remaining and member in remaining and collaboration != member:
                members.setdefault(collaboration, set()).add(member)
    merged = {
        collaboration: min(ids, key=lambda i: (-(remaining[i]["listeners"] or 0), i))
        for collaboration, ids in members.items()
    }
    redirects = {**popularity, **merged}
    for old in redirects:
        target, seen = redirects[old], {old}
        while target in redirects:
            if target in seen:
                raise ValueError("Cyclic MusicBrainz collaboration")
            seen.add(target)
            target = redirects[target]
        redirects[old] = target
    return redirects, len(popularity), len(merged)


def canonicalize(data, identities, collaborations=None):
    eager = isinstance(data, pl.DataFrame)
    folded = (
        (data.lazy() if eager else data)
        .with_columns(pl.col("artist_mbid").alias("source_mbid"))
        .with_columns(pl.col("artist_name").alias("source_name"))
        .join(identities.lazy(), on="artist_mbid", how="left")
        .with_columns(
            pl.coalesce("canonical_mbid", "artist_mbid").alias("artist_mbid"),
            pl.coalesce("canonical_name", "artist_name").alias("artist_name"),
        )
        .drop("canonical_mbid", "canonical_name")
    )
    artists = (
        folded.group_by("artist_mbid")
        .agg(
            pl.col("user").n_unique().alias("listeners"),
            pl.col("artist_name").first(),
            pl.col("disambiguation").first(),
        )
        .collect()
    )
    redirects, _, _ = cleanup_redirects(
        {
            row["artist_mbid"]: {"name": row["artist_name"], "listeners": row["listeners"]}
            for row in artists.iter_rows(named=True)
        },
        collaborations,
    )
    result = (
        folded.with_columns(pl.col("artist_mbid").replace(redirects))
        .drop("artist_name", "disambiguation")
        .join(
            artists.lazy().select("artist_mbid", "artist_name", "disambiguation"), on="artist_mbid"
        )
    )
    return result.collect() if eager else result


def release(root, release_id, identities, collaborations=None):
    mapping = {
        mbid: (canonical, comment)
        for mbid, canonical, comment in identities.select(
            "artist_mbid", "canonical_mbid", "disambiguation"
        ).iter_rows()
    }
    manifest = json.loads((root / "manifest.json").read_text())
    search = json.loads((root / manifest["search"]).read_text())
    entries = {e["id"]: e for e in search if e["kind"] == "artist"}
    canonical = {i: mapping.get(i, (i, None))[0] for i in entries}
    survivors = {}
    for old, target in canonical.items():
        if target not in survivors or old == target:
            survivors[target] = old
    summaries = {}
    for target, old in survivors.items():
        data = json.loads((root / "artists" / f"{old}.json").read_text())
        summaries[target] = {
            **data["artist"],
            "id": target,
            "disambiguation": mapping.get(old, (old, None))[1],
        }
    dropped, popularity_count, collaboration_count = cleanup_redirects(summaries, collaborations)
    membership_ids = {old for old, target in canonical.items() if target not in dropped}
    canonical = {old: dropped.get(target, target) for old, target in canonical.items()}
    survivors = {target: old for target, old in survivors.items() if target not in dropped}
    summaries = {target: summary for target, summary in summaries.items() if target not in dropped}

    def references(rows, self_id=None):
        if rows is None:
            return None
        selected = {}
        for row in sorted(rows, key=lambda r: r["artist"]["id"] != canonical[r["artist"]["id"]]):
            id_ = canonical[row["artist"]["id"]]
            if id_ != self_id and id_ not in selected:
                selected[id_] = {"artist": summaries[id_], "score": row["score"]}
        return sorted(selected.values(), key=lambda r: (-r["score"], r["artist"]["id"]))

    genres = json.loads((root / manifest["genres"]).read_text())
    memberships = {i: [] for i in summaries}
    for genre in genres:
        path = root / "genres" / f"{genre['id']}.json"
        data = json.loads(path.read_text())
        if data["members"] is not None:
            data["members"] = [
                row for row in data["members"] if row["artist"]["id"] in membership_ids
            ]
        data["members"] = references(data["members"])
        genre["member_count"] = None if data["members"] is None else len(data["members"])
        data["genre"] = genre
        for row in data["members"] or []:
            memberships[row["artist"]["id"]].append({"id": genre["id"], "score": row["score"]})
        write(path, data)
    for target, old in survivors.items():
        data = json.loads((root / "artists" / f"{old}.json").read_text())
        data["artist"] = summaries[target]
        if data["genres"] is not None:
            data["genres"] = sorted(memberships[target], key=lambda r: (-r["score"], r["id"]))
        data["similar"] = references(data["similar"], target)
        write(root / "artists" / f"{target}.json", data)
    for old, target in canonical.items():
        if old != target:
            (root / "artists" / f"{old}.json").unlink()
    redirects = {
        old: canonical.get(target, target)
        for old, target in manifest.get("artist_redirects", {}).items()
    }
    redirects.update({old: target for old, target in canonical.items() if old != target})
    manifest.update(release_id=release_id, artist_redirects=redirects)
    aliases = {target: set() for target in survivors}
    for old, entry in entries.items():
        target = canonical[old]
        aliases[target].update(
            name for name in [entry["name"], *entry["aliases"]] if name != summaries[target]["name"]
        )
    artist_search = [
        {
            **entries[old],
            "id": target,
            "listeners": summaries[target]["listeners"],
            "disambiguation": summaries[target]["disambiguation"],
            "aliases": sorted(aliases[target]),
        }
        for target, old in sorted(survivors.items())
    ]
    write(root / manifest["genres"], genres)
    write(root / manifest["search"], [e for e in search if e["kind"] == "genre"] + artist_search)
    write(root / "manifest.json", manifest)
    return {
        "artists_before": len(entries),
        "artists_after": len(survivors),
        "redirects": len(redirects),
        "genres": len(genres),
        "popularity_dropped": popularity_count,
        "collaboration_folded": collaboration_count,
    }


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("release", type=Path)
    parser.add_argument("release_id")
    parser.add_argument("--musicbrainz", type=Path, default=Path("data/artist_identity"))
    args = parser.parse_args()
    print(
        json.dumps(
            release(
                args.release,
                args.release_id,
                identity_table(args.musicbrainz),
                collaboration_table(args.musicbrainz),
            )
        )
    )


if __name__ == "__main__":
    main()
