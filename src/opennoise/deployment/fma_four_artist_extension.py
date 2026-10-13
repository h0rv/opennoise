"""Closed, offline four-artist expansion with twelve paired native genre examples.

Immutable input and output pins keep the manifest compact without nesting every
historical manifest. Each view retains the existing 64-clip and 64 MB limits.
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

REVISION = "fma-local-four-artist-extension-v3"
MAX_FILE_BYTES = 2_000_000
PINS = {
    "original": "c6030de172b0dd633b27b3ae767d00b1fecec0b7b9c89f32bd5eb56cb3b46db8",
    "parent": "5f8427df9f2b2fd581f920e9c2f852ab75314c11d50bbb9fa67be25625b739b5",
    "capture": "49866cf2be560743694d6d901a4c8857f1546340247f64f41b558531825d700f",
    "proposal": "f055a7ac9a8a7959826364748c86878acfe98a3c44459548ab40c56f0e4b8bee",
}
MANIFEST_SHA256 = "b83aa9198b08cf8263463b7b667aaa64f3a112e4cd181bc96f6611b8a18bc104"
POLICY = "all 44 added clips; 20 frozen originals including every paired example; 64 clips/64MB"


def _digest(value: object) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def _read(path: Path) -> bytes:
    collection._safe(path)  # noqa: SLF001 -- shared path custody boundary.
    if not path.is_file() or not 0 < path.stat().st_size <= MAX_FILE_BYTES:
        raise ValueError("four-artist source missing or oversized")
    return path.read_bytes()


def _derive(
    original: dict[str, Any],
    parent: dict[str, Any],
    capture: dict[str, Any],
    proposal: dict[str, Any],
) -> dict[str, Any]:
    inputs = {"original": original, "parent": parent, "capture": capture, "proposal": proposal}
    if any(_digest(value) != PINS[key] for key, value in inputs.items()):
        raise ValueError("four-artist input differs from approved source")
    original_ids = proposal["expanded_view_plan"]["selected_original_ids"]
    expanded_ids = sorted(
        [*parent["expanded_track_ids"], *[r["track_id"] for r in capture["tracks"]]]
    )
    added = {
        str(row["track_id"]): collection._track(row, row["duration_seconds"])  # noqa: SLF001 -- canonical source/decode contract.
        for row in capture["tracks"]
    }
    tracks = {
        **{str(i): original["tracks"][str(i)] for i in original_ids},
        **{str(i): parent["tracks"][str(i)] for i in parent["expanded_track_ids"]},
        **added,
    }
    sources = json.loads(json.dumps(parent["sources"]))
    native = {row["track_id"]: row for row in capture["tracks"]}
    sources["expanded"]["tracks"].update(collection._inventory(added, native))  # noqa: SLF001
    sources["expanded"]["capture_revision"] = REVISION
    sources["expanded"]["parent_capture_sha256"] = sources["expanded"]["capture_sha256"]
    sources["expanded"]["capture_sha256"] = PINS["capture"]
    return {
        "revision": REVISION,
        "test_only": False,
        "metadata_license": "CC-BY-4.0",
        "public_deployment_authorized": False,
        "selection_policy": POLICY,
        "original_track_ids": original_ids,
        "expanded_track_ids": expanded_ids,
        "sources": sources,
        "source_bindings": PINS,
        "audio_bytes": sum(row["audio_bytes"] for row in tracks.values()),
        "tracks": tracks,
    }


def validate_four_artist_metadata(manifest: dict[str, Any]) -> None:
    """Reject any semantic change to the reviewed closed-cohort playback snapshot."""
    if _digest(manifest) != MANIFEST_SHA256:
        raise ValueError("four-artist manifest differs from reviewed source and selection")


def build(
    original_audio: Path, parent_audio: Path, capture_root: Path, proposal: Path, output: Path
) -> dict[str, Any]:
    """Revalidate both retained exports and fresh full decodes before writing a new view."""
    collection._safe(output)  # noqa: SLF001
    if output.exists():
        raise ValueError("four-artist output must be fresh")
    original = fma_playback.validate_playback_export(original_audio)
    parent = fma_playback.validate_playback_export(parent_audio)
    capture = json.loads(_read(capture_root / "listening.json"))
    manifest = _derive(original, parent, capture, json.loads(_read(proposal)))
    validate_four_artist_metadata(manifest)
    encoded = canonical_json(manifest) + b"\n"
    if len(encoded) > fma_playback.MAX_MANIFEST_BYTES:
        raise ValueError("four-artist manifest exceeds existing bound")
    blobs = {}
    added_ids = {str(row["track_id"]) for row in capture["tracks"]}
    for identity, row in manifest["tracks"].items():
        source = original_audio if identity in original["tracks"] else parent_audio
        if identity in added_ids:
            source = capture_root
        path = source / row["audio_path"]
        body = _read(path)
        if (
            len(body) != row["audio_bytes"]
            or hashlib.sha256(body).hexdigest() != row["audio_sha256"]
        ):
            raise ValueError("four-artist audio source differs")
        if identity in added_ids and fma_playback.decode_duration(path) != row["duration_seconds"]:
            raise ValueError("four-artist full decode differs")
        blobs[path.name] = body
    output.mkdir(parents=True)
    for name, body in {**blobs, "manifest.json": encoded}.items():
        (output / name).write_bytes(body)
    return fma_playback.validate_playback_export(output)
