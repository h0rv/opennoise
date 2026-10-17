"""Exact same-recording genre intersections, without inferred genre membership."""

from __future__ import annotations

from collections import defaultdict
from itertools import combinations
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path


def export_cotags(  # noqa: PLR0913, PLR0917 - shared guarded export callbacks.
    output: Path,
    tracks: list[dict[str, Any]],
    artist_ids: set[int],
    genre_ids: set[int],
    files: dict[str, Any],
    write: Callable[[Path, str, object, dict[str, Any]], None],
    cohort: Callable[[Path, str, list[int], dict[str, Any]], None],
) -> dict[str, Any]:
    """Export complete direct intersections using the caller's unchanged shard guards.

    Artist support counts distinct native IDs present in the source artist table.
    Unresolved artist records count tracks instead; neither count implies independent
    musicians, artist genre membership, or acoustic similarity.
    """
    pairs: dict[tuple[int, int], list[dict[str, Any]]] = defaultdict(list)
    seen: set[int] = set()
    for track in sorted(tracks, key=lambda row: row["track_id"]):
        track_id = track["track_id"]
        if type(track_id) is not int or track_id <= 0 or track_id in seen:
            raise ValueError("invalid or duplicate co-tag track ID")
        seen.add(track_id)
        tags = set(track["genre_ids"] or [])
        if any(type(tag) is not int or tag <= 0 or tag not in genre_ids for tag in tags):
            raise ValueError("co-tag annotation references an unknown native genre")
        for pair in combinations(sorted(tags), 2):
            pairs[pair].append(track)

    connections: dict[int, list[dict[str, int]]] = defaultdict(list)
    for (left, right), members in sorted(pairs.items()):
        known = {row["artist_id"] for row in members if row["artist_id"] in artist_ids}
        counts = {
            "shared_tracks": len(members),
            "known_artist_count": len(known),
            "unresolved_artist_tracks": sum(row["artist_id"] not in artist_ids for row in members),
        }
        connections[left].append({"genre_id": right, **counts})
        connections[right].append({"genre_id": left, **counts})
        cohort(output, f"pair-{left}-{right}", [row["track_id"] for row in members], files)
    for genre_id in sorted(genre_ids):
        write(
            output,
            f"connections/{genre_id}.json",
            {
                "genre_id": genre_id,
                "connections": sorted(
                    connections[genre_id], key=lambda row: (-row["shared_tracks"], row["genre_id"])
                ),
            },
            files,
        )
    return {
        "revision": "fma-direct-cotags-v1",
        "pair_count": len(pairs),
        "directed_connections": 2 * len(pairs),
        "genre_count": len(genre_ids),
        "ordering": "shared_tracks_desc_native_id_asc",
        "evidence": "same_track_source_annotations",
    }
