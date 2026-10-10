"""Attach descriptor neighbors from the exact local audio pool, never training results."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from opennoise.common import canonical_json, sha256_file
from opennoise.ml.fma_playable_neighbors import validate_playable_neighbors

if TYPE_CHECKING:
    from pathlib import Path


MAX_VIEW_BYTES = 200_000


def export_playable_neighbors(
    source: Path, output: Path, files: dict[str, Any], playback: dict[str, Any] | None
) -> dict[str, Any]:
    """Require complete exact attachment coverage before copying a validated manifest."""
    if playback is None:
        raise ValueError("playable neighbors require an audio attachment")
    manifest = validate_playable_neighbors(source, playback["manifest_sha256"])
    attached = {row["track_id"]: row for row in playback["tracks"]}
    rows = manifest["rows"]
    if {row["track_id"] for row in rows} != set(attached) or len(rows) != len(attached):
        raise ValueError("playable neighbor attachment coverage differs")
    for row in rows:
        if any(
            neighbor not in attached
            or attached[neighbor]["artist_id"] == attached[row["track_id"]]["artist_id"]
            for neighbor in row["neighbor_ids"]
        ):
            raise ValueError("playable neighbor native artist isolation differs")
    data = canonical_json(manifest) + b"\n"
    if len(data) > MAX_VIEW_BYTES:
        raise ValueError("playable neighbor view exceeds 200 KB")
    relative = "playable-neighbors/manifest.json"
    target = output / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("xb") as stream:
        stream.write(data)
    digest, size = sha256_file(target)
    files[relative] = {"sha256": digest, "bytes": size}
    return {"manifest_path": relative, "manifest_sha256": digest, "counts": manifest["counts"]}
