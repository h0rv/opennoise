"""Bounded lazy album-title index from the existing native album groups."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from opennoise.common import canonical_json

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

MAX_SHARD_BYTES = 200_000
MAX_SEARCH_BYTES = 2_000_000


def export_album_search(
    output: Path,
    rows: list[list[Any]],
    files: dict[str, Any],
    write: Callable[[Path, str, object, dict[str, Any]], None],
) -> dict[str, Any]:
    """Keep native IDs separate even when their source titles are identical."""
    chunks: list[list[list[Any]]] = []
    chunk: list[list[Any]] = []
    size = 3
    total = 0
    previous = 0
    for row in sorted(rows, key=lambda item: item[0]):
        if type(row[0]) is not int or row[0] <= previous:
            raise ValueError("invalid or duplicate native album search ID")
        previous = row[0]
        length = len(canonical_json(row))
        if length + 3 > MAX_SHARD_BYTES:
            raise ValueError("album search row exceeds 200 KB")
        if size + length + bool(chunk) > MAX_SHARD_BYTES:
            chunks.append(chunk)
            total += size
            chunk = []
            size = 3
        size += length + bool(chunk)
        chunk.append(row)
    if chunk:
        chunks.append(chunk)
        total += size
    if total > MAX_SEARCH_BYTES:
        raise ValueError("album search index exceeds 2 MB")
    paths = []
    for index, chunk in enumerate(chunks):
        relative = f"album-search/{index}.json"
        write(output, relative, chunk, files)
        paths.append(relative)
    return {
        "revision": "fma-native-album-search-v1",
        "columns": ["album_id", "title", "track_count", "artist_count"],
        "row_count": len(rows),
        "shards": paths,
        "bytes": total,
    }
