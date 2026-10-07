"""Compact, lazy-loaded title search rows for the native FMA catalog."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from opennoise.common import canonical_json, sha256_hex

if TYPE_CHECKING:
    from pathlib import Path

MAX_SHARD_BYTES = 200_000
MAX_SEARCH_BYTES = 8_000_000


def export_track_search(
    output: Path, tracks: list[dict[str, Any]], files: dict[str, Any]
) -> dict[str, Any]:
    """Write bounded ID-sorted search shards, retaining missing native fields as null.

    Shards are JSON arrays of ``[track_id, title, artist_id]`` rows. Artist names
    are resolved from the catalog's existing artist index, not duplicated here.
    ``files`` receives the same byte/hash bindings as the main static exporter.
    """
    shards: list[str] = []
    chunks: list[bytes] = []
    chunk_bytes = 3  # Opening/closing brackets and terminal newline.
    total_bytes = 0
    previous_id = None

    def flush() -> None:
        nonlocal total_bytes
        if not chunks:
            return
        payload = b"[" + b",".join(chunks) + b"]\n"
        total_bytes += len(payload)
        if total_bytes > MAX_SEARCH_BYTES:
            raise ValueError("FMA search index exceeds 8 MB")
        relative = f"track-search/{len(shards)}.json"
        path = output / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as stream:
            stream.write(payload)
        files[relative] = {"sha256": sha256_hex(payload), "bytes": len(payload)}
        shards.append(relative)

    for track in sorted(tracks, key=lambda row: row["track_id"]):
        track_id = track["track_id"]
        if track_id == previous_id:
            raise ValueError("duplicate native FMA track ID in search index")
        previous_id = track_id
        row = canonical_json([track_id, track["title"], track["artist_id"]])
        if len(row) + 3 > MAX_SHARD_BYTES:
            raise ValueError("native FMA search row exceeds 200 KB")
        additional = len(row) + bool(chunks)
        if chunk_bytes + additional > MAX_SHARD_BYTES:
            flush()
            chunks = []
            chunk_bytes = 3
            additional = len(row)
        chunks.append(row)
        chunk_bytes += additional
    flush()
    return {
        "columns": ["track_id", "title", "artist_id"],
        "row_count": len(tracks),
        "shards": shards,
        "bytes": total_bytes,
    }
