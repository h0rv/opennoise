import hashlib
import json
import re
import subprocess
import tomllib
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

import polars as pl


class MapParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows = []
        self.active = False
        self.xy = (0, 0)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "div" and attrs.get("class") == "genre scanme":
            self.active = True
            style = attrs["style"]
            self.xy = tuple(
                int(re.findall(f"{axis}: ([0-9]+)px", style)[0]) for axis in ["left", "top"]
            )
        elif tag == "a":
            self.active = False

    def handle_data(self, data):
        if self.active and data.strip():
            self.rows.append((data.strip(), *self.xy))
            self.active = False


def table(name, columns, names):
    data = pl.read_csv(
        Path("data/m2/mbdump") / name,
        separator="\t",
        has_header=False,
        quote_char=None,
        infer_schema=False,
        columns=columns,
        null_values="\\N",
    )
    return data.rename(dict(zip(data.columns, names, strict=True)))


def ingest_reference(config):
    root = Path("data/m2")
    root.mkdir(parents=True, exist_ok=True)
    if (root / "coverage.json").exists():
        return
    sources = tomllib.loads(Path("sources.toml").read_text())["sources"]
    for source, filename in zip(sources[1:3], ["enao.json", "map.html"], strict=True):
        path = root / filename
        if not path.exists():
            urllib.request.urlretrieve(source["url"], path.with_suffix(".part"))
            path.with_suffix(".part").rename(path)
        if hashlib.sha256(path.read_bytes()).hexdigest() != source["sha256"]:
            raise ValueError(f"Checksum mismatch: {filename}")
    for source, tables in zip(
        sources[3:5], [["artist", "url", "l_artist_url"], ["artist_tag", "tag"]], strict=True
    ):
        marker = root / (tables[0] + ".done")
        if not marker.exists():
            members = " ".join(f"mbdump/{name}" for name in tables)
            subprocess.run(
                [
                    "bash",
                    "-c",
                    f"set -o pipefail; curl -fL '{source['url']}' | "
                    f"bzip2 -dc | tar -xf - -C '{root}' {members}",
                ],
                check=True,
            )
            marker.touch()
    parser = MapParser()
    parser.feed((root / "map.html").read_text())
    pl.DataFrame(parser.rows, schema=["genre", "x", "y"], orient="row").write_parquet(
        root / "map.parquet"
    )
    rows = [
        (genre["genre"], artist["artist_id"])
        for genre in json.loads((root / "enao.json").read_text())
        for artist in genre["artists"]
    ]
    reference = pl.DataFrame(rows, schema=["genre", "spotify"], orient="row").unique()
    artists = table("artist", [0, 1], ["mb_artist", "artist_mbid"])
    urls = (
        table("url", [0, 2], ["url_id", "url"])
        .with_columns(
            pl.col("url")
            .str.extract(
                r"^https?://open\.spotify\.com/(?:intl-[^/]+/)?artist/([A-Za-z0-9]{22})(?:[/?#]|$)",
                1,
            )
            .alias("spotify")
        )
        .filter(pl.col("spotify").is_not_null())
        .select("url_id", "spotify")
    )
    links = table("l_artist_url", [2, 3], ["mb_artist", "url_id"])
    crosswalk = (
        links.join(urls, on="url_id")
        .join(artists, on="mb_artist")
        .select("spotify", "artist_mbid")
        .unique()
    )
    crosswalk.write_parquet(root / "crosswalk.parquet")
    m1 = pl.read_parquet(Path(config["m1"]) / "artists.parquet")
    mapped = reference.join(crosswalk, on="spotify")
    in_graph = mapped.join(m1.select("artist_mbid", "item"), on="artist_mbid")
    in_graph.select("genre", "item").unique().sort(["genre", "item"]).write_parquet(
        root / "labels.parquet"
    )
    tags = table("artist_tag", [0, 1, 2], ["mb_artist", "tag_id", "count"]).filter(
        pl.col("count").cast(pl.Int64) > 0
    )
    tags = (
        tags.join(artists, on="mb_artist")
        .join(m1.select("artist_mbid", "item"), on="artist_mbid")
        .join(table("tag", [0, 1], ["tag_id", "tag"]), on="tag_id")
    )
    tags.select("item", "tag").unique().sort(["tag", "item"]).write_parquet(root / "tags.parquet")
    total = reference["spotify"].n_unique()
    coverage = {
        "reference_genres": reference["genre"].n_unique(),
        "map_genres": len(parser.rows),
        "reference_artists": total,
        "mapped_artists": mapped["spotify"].n_unique(),
        "in_graph_artists": in_graph["spotify"].n_unique(),
    }
    coverage["mapped_share"] = coverage["mapped_artists"] / total
    coverage["in_graph_share"] = coverage["in_graph_artists"] / total
    coverage["mapped_in_graph_share"] = coverage["in_graph_artists"] / coverage["mapped_artists"]
    (root / "coverage.json").write_text(json.dumps(coverage, indent=2))
    print(json.dumps(coverage), flush=True)
