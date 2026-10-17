"""Native album context derived only from verified FMA track rows."""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import TYPE_CHECKING, Any

from opennoise.deployment.fma_album_search import export_album_search

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

ALBUM_SHARDS = 128


def export_albums(
    output: Path,
    tracks: list[dict[str, Any]],
    files: dict[str, Any],
    write: Callable[[Path, str, object, dict[str, Any]], None],
) -> tuple[dict[str, Any], dict[int | None, list[list[Any]]]]:
    """Keep exact album IDs, source titles and contributors, without ownership inference.

    The caller supplies its guarded writer, so album shards obey the catalog's
    existing byte limits and hash inventory. Missing IDs do not create albums.
    """
    grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
    seen: set[int] = set()
    for track in sorted(tracks, key=lambda row: row["track_id"]):
        if track["track_id"] in seen:
            raise ValueError("duplicate native track ID in album context")
        seen.add(track["track_id"])
        album_id = track["album_id"]
        if album_id is not None:
            if type(album_id) is not int or album_id <= 0:
                raise ValueError("invalid native album ID")
            grouped[album_id].append(track)

    shards: dict[int, dict[str, Any]] = defaultdict(dict)
    artist_albums: dict[int | None, list[list[Any]]] = defaultdict(list)
    search_rows: list[list[Any]] = []
    for album_id, members in sorted(grouped.items()):
        titles = {row.get("album_title") for row in members if row.get("album_title")}
        if len(titles) > 1:
            raise ValueError("conflicting native titles for one album ID")
        title = next(iter(titles), None)
        contributors = Counter(row["artist_id"] for row in members)
        search_rows.append(
            [
                album_id,
                title,
                len(members),
                sum(artist_id is not None for artist_id in contributors),
            ]
        )
        shards[album_id % ALBUM_SHARDS][str(album_id)] = {
            "album_id": album_id,
            "title": title,
            "track_ids": [row["track_id"] for row in members],
            "artist_ids": sorted(contributors, key=lambda value: value or 0),
        }
        for artist_id, count in contributors.items():
            artist_albums[artist_id].append([album_id, title, count])
    for shard in range(ALBUM_SHARDS):
        write(output, f"albums/{shard}.json", {"shard": shard, "albums": shards[shard]}, files)
    for albums in artist_albums.values():
        albums.sort(key=lambda row: ((row[1] or "").casefold(), row[0]))
    return {
        "revision": "fma-native-albums-v1",
        "shards": ALBUM_SHARDS,
        "album_count": len(grouped),
        "search": export_album_search(output, search_rows, files, write),
        "track_count": sum(len(rows) for rows in grouped.values()),
        "missing_album_tracks": len(tracks) - sum(len(rows) for rows in grouped.values()),
        "track_order": "native_track_id_not_release_sequence",
    }, dict(artist_albums)
