"""Complete, static source-artist navigation with bounded page responses."""

from __future__ import annotations

import json
import re
from collections import defaultdict
from typing import TYPE_CHECKING

from opennoise.common import canonical_json

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Mapping
    from pathlib import Path

PAGE_SIZE = 100
PREFIX_LENGTH = 3
_SAFE_ID = re.compile(r"^[a-zA-Z0-9_-]+$")


def write_direct_artist_shards(
    connection: sqlite3.Connection,
    output: Path,
    *,
    display_names: Mapping[str, str] | None = None,
) -> dict[str, object]:
    """Write every exact source artist and pair, without inferred membership."""
    profiles: dict[str, dict[str, object]] = {}
    overlay = display_names or {}
    for artist, name, status in connection.execute(
        "SELECT artist_mbid,display_name,name_status FROM artist ORDER BY artist_mbid"
    ):
        if not _SAFE_ID.fullmatch(artist):
            raise ValueError("unsafe artist identity in static source projection")
        profiles[artist] = {
            "name": overlay.get(artist) or name or artist,
            "name_status": "exact_official_name_overlay" if artist in overlay else status,
            "genre_ids": [],
        }
    by_genre: dict[str, list[str]] = defaultdict(list)
    pair_count = 0
    for genre, artist in connection.execute(
        "SELECT seed_id,artist_mbid FROM seed_artist ORDER BY seed_id,artist_mbid"
    ):
        if not _SAFE_ID.fullmatch(genre):
            raise ValueError("unsafe genre identity in static source projection")
        profile = profiles[artist]
        genre_ids = profile["genre_ids"]
        if not isinstance(genre_ids, list):
            raise TypeError("invalid source genre projection")
        genre_ids.append(genre)
        by_genre[genre].append(artist)
        pair_count += 1
    profile_dir = output / "artists"
    profile_dir.mkdir()
    groups: dict[str, dict[str, dict[str, object]]] = defaultdict(dict)
    for artist, profile in profiles.items():
        groups[artist[:PREFIX_LENGTH]][artist] = profile
    for prefix, artists in sorted(groups.items()):
        (profile_dir / f"{prefix}.json").write_bytes(canonical_json({"artists": artists}) + b"\n")
    page_counts: dict[str, int] = {}
    for genre, ids in sorted(by_genre.items()):
        ids.sort(key=lambda artist: (str(profiles[artist]["name"]).casefold(), artist))
        directory = output / "genre-artists" / genre
        directory.mkdir(parents=True)
        page_counts[genre] = (len(ids) + PAGE_SIZE - 1) // PAGE_SIZE
        for offset in range(0, len(ids), PAGE_SIZE):
            page = offset // PAGE_SIZE
            payload = {
                "genre_id": genre,
                "page": page,
                "total_count": len(ids),
                "role": "direct_source_observation",
                "order": "display_name_casefold_then_exact_mbid_not_relevance",
                "artists": [
                    {"id": artist, **profiles[artist]}
                    for artist in ids[offset : offset + PAGE_SIZE]
                ],
            }
            (directory / f"{page}.json").write_bytes(canonical_json(payload) + b"\n")
    search_rows = [
        [artist, profile["name"], profile["name_status"]]
        for artist, profile in sorted(
            profiles.items(), key=lambda item: (str(item[1]["name"]).casefold(), item[0])
        )
    ]
    (output / "artist-search.json").write_bytes(canonical_json({"artists": search_rows}) + b"\n")
    return {
        "revision": "direct-source-artist-shards-v1",
        "profile_path_template": "artists/{prefix}.json",
        "prefix_length": PREFIX_LENGTH,
        "genre_pages_path_template": "genre-artists/{genre_id}/{page}.json",
        "page_size": PAGE_SIZE,
        "search_path": "artist-search.json",
        "artist_count": len(profiles),
        "direct_pair_count": pair_count,
        "genre_page_counts": page_counts,
        "profile_shard_count": len(groups),
        "genre_page_count": sum(page_counts.values()),
        "membership_role": "direct_source_observation",
        "artist_order": "display_name_casefold_then_exact_mbid_not_relevance",
    }


def write_genre_detail_shards(payload: dict[str, object], output: Path) -> None:
    """Keep overview metadata small and defer complete detail to exact genre routes."""
    rows = payload["genres"]
    if not isinstance(rows, list):
        raise TypeError("invalid genre detail projection")
    directory = output / "genre-details"
    directory.mkdir()
    overview = []
    profiles = payload["artists"]
    if not isinstance(profiles, dict):
        raise TypeError("invalid detailed artist projection")
    for genre in rows:
        identifier = genre["id"]
        if not _SAFE_ID.fullmatch(identifier):
            raise ValueError("unsafe genre detail identity")
        relative = f"genre-details/{identifier}.json"
        genre["artist_profiles"] = {
            artist: profiles[artist]
            for artist in sorted(
                set(genre["direct_artist_ids"])
                | {proposal["artist_mbid"] for proposal in genre["proposals"]}
            )
        }
        (output / relative).write_bytes(canonical_json(genre) + b"\n")
        overview.append(
            {
                key: genre[key]
                for key in (
                    "id",
                    "name",
                    "x",
                    "y",
                    "observed_artist_count",
                    "direct_artist_page_count",
                    "direct_artist_page_size",
                )
            }
            | {
                "modeled_neighbor_count": len(genre["peers"]),
                "peers": [],
                "proposals": [],
                "direct_artist_ids": [],
                "detail_path": relative,
            }
        )
    payload["genres"] = overview
    payload["artists"] = {}
    payload["genre_details_revision"] = "direct-source-genre-details-v1"


def join_artist_map_labels(payload: dict[str, object], output: Path) -> None:
    """Join source display names and profiles after offline artist geometry is fixed."""
    profiles = {}
    for shard in sorted((output / "artists").glob("*.json")):
        profiles.update(json.loads(shard.read_bytes())["artists"])
    rows = payload["genres"]
    if not isinstance(rows, list):
        raise TypeError("invalid artist map genre projection")
    for genre in rows:
        relative = f"genre-artist-maps/{genre['id']}.json"
        file = output / relative
        artist_map = json.loads(file.read_bytes())
        if artist_map["genre_id"] != genre["id"]:
            raise ValueError("artist map source genre differs from route")
        for artist in artist_map["artists"]:
            if genre["id"] not in profiles[artist["id"]]["genre_ids"]:
                raise ValueError("artist map cohort contains a non-source member")
            artist.update(profiles[artist["id"]])
        file.write_bytes(canonical_json(artist_map) + b"\n")
        genre["artist_map_path"] = relative
