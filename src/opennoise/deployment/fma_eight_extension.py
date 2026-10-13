"""Offline, closed-cohort extension adding eight verified native excerpts.

The original collection protocol and its transfer limits remain unchanged.
This revision binds the exact parent and acquired source receipts, retains all
40 added excerpts, and selects 24 shared originals within the same 64-clip cap.
"""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

from opennoise.common import canonical_json
from opennoise.deployment import fma_listening_collection as collection
from opennoise.deployment import fma_playback

REVISION = "fma-local-eight-extension-v2"
MAX_SOURCE_FILE_BYTES = 2_000_000
PARENT_SHA256 = "198d86146d50bf60eaefeda3d8c7b38da66ab8340c8711f39ebc654e6c6d5dc4"
CAPTURE_SHA256 = "23c3623d0f0a0ce15d7d38de954bd64c6cb8078aab8ed9033601515031116ee8"
POLICY = "all 40 added clips and first 24 frozen original selections; same 64-clip/64MB bounds"


def _digest(value: object) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def _manifest(parent: dict[str, Any], capture: dict[str, Any]) -> dict[str, Any]:
    if _digest(parent) != PARENT_SHA256 or _digest(capture) != CAPTURE_SHA256:
        raise ValueError("eight-clip source receipt differs from reviewed cohort")
    collection.validate_collection_metadata(parent)
    added = {
        str(row["track_id"]): collection._track(row, row["duration_seconds"])  # noqa: SLF001 -- same source/decode record contract.
        for row in capture["tracks"]
    }
    original_ids = parent["original_track_ids"][:24]
    expanded_ids = sorted([*parent["expanded_track_ids"], *map(int, added)])
    tracks = {
        **{
            str(i): parent["tracks"][str(i)] for i in [*original_ids, *parent["expanded_track_ids"]]
        },
        **added,
    }
    sources = json.loads(json.dumps(parent["sources"]))
    native = {row["track_id"]: row for row in capture["tracks"]}
    sources["expanded"]["tracks"].update(collection._inventory(added, native))  # noqa: SLF001 -- unchanged canonical source inventory.
    sources["expanded"]["capture_revision"] = REVISION
    sources["expanded"]["parent_capture_sha256"] = sources["expanded"]["capture_sha256"]
    sources["expanded"]["capture_sha256"] = CAPTURE_SHA256
    return {
        "revision": REVISION,
        "test_only": False,
        "metadata_license": "CC-BY-4.0",
        "public_deployment_authorized": False,
        "selection_policy": POLICY,
        "original_track_ids": original_ids,
        "expanded_track_ids": expanded_ids,
        "sources": sources,
        "audio_bytes": sum(row["audio_bytes"] for row in tracks.values()),
        "tracks": tracks,
        "source_evidence": {"parent": parent, "capture": capture},
    }


def validate_extension_metadata(manifest: dict[str, Any]) -> None:
    """Reconstruct every field from two immutable, separately reviewed source receipts."""
    evidence = manifest.get("source_evidence", {})
    if set(evidence) != {"parent", "capture"} or manifest != _manifest(
        evidence["parent"], evidence["capture"]
    ):
        raise ValueError("eight-clip source, selection or playback record differs")


def build(parent_audio: Path, capture_root: Path, output: Path) -> dict[str, Any]:
    """Verify parent audio and fresh full decodes, then create a new bounded export."""
    for path in (parent_audio, capture_root, output):
        collection._safe(path)  # noqa: SLF001 -- same path custody boundary.
    if output.exists():
        raise ValueError("eight-clip export must be fresh")
    parent = fma_playback.validate_playback_export(parent_audio)
    capture_path = capture_root / "listening.json"
    collection._safe(capture_path)  # noqa: SLF001 -- retained control file custody.
    if not capture_path.is_file() or not 0 < capture_path.stat().st_size <= MAX_SOURCE_FILE_BYTES:
        raise ValueError("eight-clip receipt missing or oversized")
    capture = json.loads(capture_path.read_bytes())
    manifest = _manifest(parent, capture)
    encoded = canonical_json(manifest) + b"\n"
    if len(encoded) > fma_playback.MAX_MANIFEST_BYTES:
        raise ValueError("eight-clip manifest exceeds existing bound")
    blobs = {}
    for identity, row in manifest["tracks"].items():
        source = capture_root if identity not in parent["tracks"] else parent_audio
        path = source / row["audio_path"]
        collection._safe(path)  # noqa: SLF001
        if not path.is_file() or not 0 < path.stat().st_size <= MAX_SOURCE_FILE_BYTES:
            raise ValueError("eight-clip member missing or oversized")
        body = path.read_bytes()
        if (
            len(body) != row["audio_bytes"]
            or hashlib.sha256(body).hexdigest() != row["audio_sha256"]
        ):
            raise ValueError("eight-clip audio differs from frozen receipt")
        if source == capture_root and fma_playback.decode_duration(path) != row["duration_seconds"]:
            raise ValueError("eight-clip full decode differs")
        blobs[path.name] = body
    output.mkdir(parents=True)
    for name, body in {**blobs, "manifest.json": encoded}.items():
        (output / name).write_bytes(body)
    return fma_playback.validate_playback_export(output)
