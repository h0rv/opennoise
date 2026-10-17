"""Reverse native track annotations without classifying artists."""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections import Counter
    from collections.abc import Callable
    from pathlib import Path

PAGE_SIZE = 100


def export_genre_artists(
    output: Path,
    counts: dict[int | None, Counter[int]],
    genre_ids: set[int],
    files: dict[str, Any],
    write: Callable[[Path, str, object, dict[str, Any]], None],
) -> dict[str, Any]:
    """Reuse validated per-artist direct track counts; do not copy track memberships."""
    groups: dict[int, list[tuple[int | None, int]]] = defaultdict(list)
    for artist_id, genres in counts.items():
        if artist_id is not None and (type(artist_id) is not int or artist_id <= 0):
            raise ValueError("invalid genre-artist native ID")
        for genre_id, count in genres.items():
            if (
                type(genre_id) is not int
                or genre_id not in genre_ids
                or type(count) is not int
                or count <= 0
            ):
                raise ValueError("invalid direct genre-artist count")
            groups[genre_id].append((artist_id, count))
    summaries = []
    for genre_id in sorted(genre_ids):
        rows = sorted(groups[genre_id], key=lambda row: (-row[1], row[0] or 0))
        summaries.append([genre_id, len(rows), sum(row[1] for row in rows)])
        for page, start in enumerate(range(0, max(1, len(rows)), PAGE_SIZE)):
            write(
                output,
                f"genre-artists/{genre_id}/{page}.json",
                {
                    "genre_id": genre_id,
                    "page": page,
                    "total": len(rows),
                    "artists": rows[start : start + PAGE_SIZE],
                },
                files,
            )
    return {
        "revision": "fma-genre-track-artists-v1",
        "page_size": PAGE_SIZE,
        "genres": summaries,
        "pair_count": sum(len(rows) for rows in groups.values()),
        "ordering": "direct_track_count_desc_native_id_asc_null_first",
    }
