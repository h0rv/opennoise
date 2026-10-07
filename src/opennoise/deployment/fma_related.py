"""Import a bounded, byte-verified descriptor suggestion pack into the native catalog."""

from __future__ import annotations

import json
from collections import Counter
from typing import TYPE_CHECKING, Any

from opennoise.common import sha256_file
from opennoise.ml.fma_inference import EVALUATION_SHA256, FEATURE_RECEIPT_SHA256

if TYPE_CHECKING:
    from pathlib import Path

TRACK_SPAN = 500
NEIGHBORS = 6
ABSTENTIONS = {
    "unresolved_artist",
    "missing_feature_row",
    "outside_training_support",
    "no_cross_component_candidates",
}
MAX_BYTES = 8_000_000
MAX_SHARD_BYTES = 200_000


def export_related_music(  # noqa: C901, PLR0912 - complete pack checked before any write.
    source: Path, output: Path, files: dict[str, Any], native_track_ids: set[int]
) -> dict[str, Any]:
    """Validate all native query and neighbor IDs before copying any immutable input."""
    manifest_path = source / "manifest.json"
    if manifest_path.is_symlink() or manifest_path.stat().st_size > MAX_SHARD_BYTES:
        raise ValueError("unsupported related music manifest")
    manifest = json.loads(manifest_path.read_bytes())
    if (
        manifest["revision"] != "fma-frozen-descriptor-neighbors-v1"
        or manifest["track_id_span"] != TRACK_SPAN
        or manifest["neighbor_count"] != NEIGHBORS
    ):
        raise ValueError("unsupported related music shard contract")
    provenance = manifest["provenance"]
    if (
        manifest["labels_used"] is not False
        or manifest["musical_relevance_established"] is not False
        or provenance["evaluation_sha256"] != EVALUATION_SHA256
        or provenance["feature_receipt_sha256"] != FEATURE_RECEIPT_SHA256
    ):
        raise ValueError("related music frozen source contract differs")
    payloads = {"manifest.json": manifest_path.read_bytes()}
    seen: set[int] = set()
    reasons: Counter[str] = Counter()
    supported = 0
    total = len(payloads["manifest.json"])
    for name, binding in manifest["files"].items():
        if not name.endswith(".json") or not name[:-5].isdigit():
            raise ValueError("unsafe related music shard path")
        path = source / name
        if (
            path.is_symlink()
            or path.stat().st_size != binding["bytes"]
            or binding["bytes"] > MAX_SHARD_BYTES
            or sha256_file(path) != (binding["sha256"], binding["bytes"])
        ):
            raise ValueError("related music shard binding differs")
        data = path.read_bytes()
        total += len(data)
        if total > MAX_BYTES:
            raise ValueError("related music exceeds 8 MB")
        for identity, neighbors, reason in json.loads(data)["rows"]:
            if (
                type(identity) is not int
                or identity not in native_track_ids
                or identity in seen
                or identity // TRACK_SPAN != int(name[:-5])
                or not isinstance(neighbors, list)
                or len(neighbors) > NEIGHBORS
                or len(set(neighbors)) != len(neighbors)
                or any(type(i) is not int or i not in native_track_ids for i in neighbors)
                or identity in neighbors
                or (
                    reason is not None
                    and (not isinstance(reason, str) or reason not in ABSTENTIONS)
                )
                or bool(neighbors) != (reason is None)
            ):
                raise ValueError("related music native identity or abstention differs")
            seen.add(identity)
            if reason is None:
                supported += 1
            else:
                reasons[reason] += 1
        payloads[name] = data
    if seen != native_track_ids:
        raise ValueError("related music omits native query IDs")
    counts = manifest["counts"]
    if (
        counts["queries"] != len(seen)
        or counts["supported_queries"] != supported
        or counts["abstentions"] != dict(reasons)
    ):
        raise ValueError("related music coverage accounting differs")
    for name, data in payloads.items():
        relative = f"related-tracks/{name}"
        path = output / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as stream:
            stream.write(data)
        digest, length = sha256_file(path)
        files[relative] = {"sha256": digest, "bytes": length}
    return {
        "manifest_path": "related-tracks/manifest.json",
        "track_id_span": manifest["track_id_span"],
        "neighbor_count": manifest["neighbor_count"],
        "counts": manifest["counts"],
        "method": manifest["method"],
    }
