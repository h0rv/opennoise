import argparse
import json
import tomllib
from collections import defaultdict
from pathlib import Path

import polars as pl

from opennoise.genres import heldout_genres
from opennoise.metrics import sealed
from opennoise.names import canonical, key
from opennoise.reference import MapParser, table
from opennoise.tags import log


def priority(score, count, size):
    return score if size is None else score * count**0.5 / (count + size)


def everynoise(cache, release, config):
    crosswalk = cache / "crosswalk.parquet"
    if not crosswalk.exists():
        artists = table("artist", [0, 1], ["mb_artist", "artist_mbid"], cache / "mbdump")
        urls = (
            table("url", [0, 2], ["url_id", "url"], cache / "mbdump")
            .with_columns(
                pl.col("url")
                .str.extract(
                    r"^https?://open\.spotify\.com/(?:intl-[^/]+/)?artist/([A-Za-z0-9]{22})(?:[/?#]|$)",
                    1,
                )
                .alias("spotify")
            )
            .filter(pl.col("spotify").is_not_null())
        )
        links = table("l_artist_url", [2, 3], ["mb_artist", "url_id"], cache / "mbdump")
        links.join(urls, on="url_id").join(artists, on="mb_artist").select(
            "spotify", "artist_mbid"
        ).unique().write_parquet(crosswalk)
    manifest = json.loads((release / "manifest.json").read_text())
    catalog = pl.DataFrame(
        [
            {"artist_mbid": e["id"]}
            for e in json.loads((release / manifest["search"]).read_text())
            if e["kind"] == "artist"
        ]
    )
    labels = (
        pl.DataFrame(
            [
                (g["genre"], a["artist_id"])
                for g in json.loads((cache / "enao.json").read_text())
                for a in g["artists"]
            ],
            schema=["genre", "spotify"],
            orient="row",
        )
        .join(pl.read_parquet(crosswalk), on="spotify")
        .join(catalog, on="artist_mbid")
        .select("artist_mbid", "genre")
        .unique()
    )
    parser = MapParser()
    parser.feed((cache / "map.html").read_text())
    eligible = (
        labels.group_by("genre")
        .len()
        .filter(
            (pl.col("len") >= config["min_artists"])
            & pl.col("genre").is_in([row[0] for row in parser.rows])
        )["genre"]
        .sort()
        .to_list()
    )
    hidden = heldout_genres(config, eligible)
    return labels.filter(pl.col("genre").is_in(sorted(hidden)))


def evaluate(root, references, sizes=(None, 10000)):
    manifest = json.loads((root / "manifest.json").read_text())
    genres = {g["id"]: g for g in json.loads((root / manifest["genres"]).read_text())}
    names = defaultdict(set)
    for i, g in genres.items():
        for name in [g["name"], *g["aliases"]]:
            names[key(canonical(name))].add(i)
    labels = {}
    for name, reference in references.items():
        labels[name] = defaultdict(set)
        for artist, genre in reference.select("artist_mbid", "genre").unique().iter_rows():
            labels[name][artist].update(names.get(key(canonical(genre)), set()))
    artists = {
        e["id"]
        for e in json.loads((root / manifest["search"]).read_text())
        if e["kind"] == "artist"
    }
    results = {
        str(size): {
            name: {"artists": 0, "matchable": 0, "top1": 0, "top3": 0} for name in references
        }
        for size in sizes
    }
    for artist in sorted(artists & set().union(*(set(ref) for ref in labels.values()))):
        memberships = json.loads((root / "artists" / f"{artist}.json").read_text())["genres"] or []
        for size in sizes:
            ranked = sorted(
                memberships,
                key=lambda m: (
                    -priority(m["score"], genres[m["id"]]["member_count"] or 0, size),
                    m["id"],
                ),
            )
            for name, reference in labels.items():
                if artist not in reference:
                    continue
                truth = reference[artist]
                result = results[str(size)][name]
                result["artists"] += 1
                result["matchable"] += bool(truth)
                result["top1"] += any(m["id"] in truth for m in ranked[:1])
                result["top3"] += any(m["id"] in truth for m in ranked[:3])
    return {
        size: {
            name: result
            | {
                k: result[k] / result["artists"] if result["artists"] else None
                for k in ["top1", "top3"]
            }
            for name, result in candidates.items()
        }
        for size, candidates in results.items()
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("release", type=Path)
    parser.add_argument("wikidata", type=Path)
    parser.add_argument("everynoise", type=Path)
    parser.add_argument("--config", type=Path, default=Path("configs/m2.toml"))
    args = parser.parse_args()
    wikidata = pl.read_parquet(args.wikidata).filter(
        pl.col("artist_mbid").map_elements(sealed, return_dtype=pl.Boolean)
    )
    results = evaluate(
        args.release,
        {
            "wikidata_sealed": wikidata,
            "everynoise_heldout": everynoise(
                args.everynoise, args.release, tomllib.loads(args.config.read_text())
            ),
        },
    )
    for candidate, result in results.items():
        log(
            args.release,
            f"genre_order/{'None' if candidate == 'None' else 'sqrt_' + candidate}",
            result,
            kept=False,
            note="Evaluation only: score*sqrt(n)/(n+size); None=score; UI retains score order",
        )


if __name__ == "__main__":
    main()
