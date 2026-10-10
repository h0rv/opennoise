"""Bounded static projection of independently frozen fresh FMA map artifacts."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

from opennoise.common import canonical_json, sha256_file
from opennoise.ml.fma_fresh_map import validate_fresh_map

if TYPE_CHECKING:
    from pathlib import Path

MAX_SHARD_BYTES = 200_000
MAX_MAP_BYTES = 3_000_000
SHARD_ROWS = 1500
DIMENSIONS = 2


def export_descriptor_map(
    source: Path,
    output: Path,
    files: dict[str, dict[str, Any]],
    tables: dict[str, list[dict[str, Any]]],
    metadata_receipt_sha: str,
) -> dict[str, Any]:
    """Keep all native identities and missing positions; bind to this exact metadata capture."""
    coordinates = validate_fresh_map(source)
    if coordinates["source"]["metadata/corpus-receipt.json"] != metadata_receipt_sha:
        raise ValueError("descriptor map metadata capture differs")
    rows = {}
    for kind, key in (("genres", "genre_id"), ("artists", "artist_id")):
        expected = {row[key] for row in tables[kind]}
        actual = coordinates[kind]
        if len(actual) != len(expected) or {row[key] for row in actual} != expected:
            raise ValueError("descriptor map native identity coverage differs")
        slim = []
        for row in actual:
            position = row["position"]
            if position is not None and (
                not isinstance(position, list)
                or len(position) != DIMENSIONS
                or any(type(v) not in (int, float) or not math.isfinite(v) for v in position)
            ):
                raise ValueError("descriptor map coordinate is invalid")
            slim.append({"id": row[key], "position": position})
        rows[kind] = sorted(slim, key=lambda row: row["id"])
    (output / "descriptor-map").mkdir()
    total = 0

    def write(name: str, value: object) -> None:
        nonlocal total
        body = canonical_json(value) + b"\n"
        total += len(body)
        if len(body) > MAX_SHARD_BYTES or total > MAX_MAP_BYTES:
            raise ValueError("descriptor map exceeds bounded static budget")
        path = output / name
        with path.open("xb") as stream:
            stream.write(body)
        digest, length = sha256_file(path)
        files[name] = {"sha256": digest, "bytes": length}

    shards = []
    for start in range(0, len(rows["artists"]), SHARD_ROWS):
        name = f"descriptor-map/artists-{start // SHARD_ROWS}.json"
        write(name, rows["artists"][start : start + SHARD_ROWS])
        shards.append(name)
    manifest = {
        "revision": "fma-descriptor-map-view-v1",
        "genres": rows["genres"],
        "artist_shards": shards,
        "axes": coordinates["axes"],
        "counts": coordinates["denominators"],
        "source_receipt_sha256": sha256_file(source / "receipt.json")[0],
        "metadata_receipt_sha256": metadata_receipt_sha,
        "musical_validation_established": False,
        "files": {name: files[name] for name in shards},
    }
    write("descriptor-map/manifest.json", manifest)
    return {"manifest": "descriptor-map/manifest.json", "bytes": total}
