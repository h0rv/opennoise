"""Offline assembly of a bounded expanded collection without changing original captures."""

from __future__ import annotations

import hashlib
import json
import re
import tempfile
from pathlib import Path
from typing import Any

from opennoise.common import canonical_json
from opennoise.deployment import fma_playback
from opennoise.serving.metadata import fma_large32, fma_listening64

REVISION = "fma-local-playback-collection-v1"
POLICY = (
    "all expanded clips; up to 32 original clips by marginal direct-genre gain then native ID, "
    "subject to 64 clips and 64000000 bytes"
)
MAX_ORIGINAL = 32


def _safe(path: Path) -> None:
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError("symlinked collection path")


def _sha(path: Path) -> str:
    _safe(path)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _digest(value: object) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def _track(row: dict[str, Any], duration: float) -> dict[str, Any]:
    source = row["source"]
    title, artist = source["track_title"], source["artist_name"]
    return {
        "track_id": row["track_id"],
        "artist_id": row["artist_id"],
        "title": title,
        "artist_name": artist,
        "audio_path": row["audio_path"],
        "audio_sha256": row["audio_sha256"],
        "audio_bytes": row["audio_bytes"],
        "duration_seconds": duration,
        "decode": {
            "protocol": fma_playback.DECODE_PROTOCOL,
            "audio_sha256": row["audio_sha256"],
            "full_decode": True,
        },
        "license_title": source["license_title"],
        "license_url": source["license_url"],
        "source_url": source["track_url"],
        "attribution": f"{title} — {artist}; {source['license_title']}; {source['track_url']}",
        "copyright_c": source["track_copyright_c"],
        "copyright_p": source["track_copyright_p"],
        "composer": source["track_composer"],
    }


def _inventory(tracks: dict[str, Any], native: dict[int, Any]) -> dict[str, Any]:
    return {
        key: {
            "record_sha256": _digest(track),
            "audio_sha256": track["audio_sha256"],
            "audio_bytes": track["audio_bytes"],
            "artist_id": track["artist_id"],
            "genre_ids": sorted(set(native[int(key)]["genre_ids"])),
        }
        for key, track in sorted(tracks.items(), key=lambda item: int(item[0]))
    }


def select_original(expanded: dict[str, Any], original: dict[str, Any]) -> list[int]:
    """Keep every new clip, then greedily add fitting original source-genre coverage."""
    total = sum(row["audio_bytes"] for row in expanded.values())
    if (
        not 0 < len(expanded) <= fma_large32.MAX_CLIPS
        or total > fma_large32.AUDIO_BYTES
        or set(expanded) & set(original)
    ):
        raise ValueError("expanded clip scope or source overlap differs")
    covered = {genre for row in expanded.values() for genre in row["genre_ids"]}
    remaining = {int(key): value for key, value in original.items()}
    chosen = []
    while len(chosen) < MAX_ORIGINAL and len(chosen) + len(expanded) < fma_listening64.MAX_CLIPS:
        fitting = [
            identity
            for identity, row in remaining.items()
            if total + row["audio_bytes"] <= fma_listening64.MAX_AUDIO_BYTES
        ]
        if not fitting:
            break
        identity = min(
            fitting, key=lambda value: (-len(set(remaining[value]["genre_ids"]) - covered), value)
        )
        row = remaining.pop(identity)
        chosen.append(identity)
        covered.update(row["genre_ids"])
        total += row["audio_bytes"]
    return chosen


def validate_collection_metadata(manifest: dict[str, Any]) -> None:  # noqa: C901, PLR0912 -- independent source and record bindings.
    """Check explicit origin inventories, frozen selection and complete new-clip inclusion."""
    sources = manifest.get("sources", {})
    if set(sources) != {"original", "expanded"} or manifest.get("selection_policy") != POLICY:
        raise ValueError("collection source inventory differs")
    for name, limit, revision in (
        ("original", fma_listening64.MAX_CLIPS, fma_listening64.REVISION),
        ("expanded", fma_large32.MAX_CLIPS, fma_large32.REVISION),
    ):
        source = sources[name]
        records = source.get("tracks")
        if (
            source.get("capture_revision") != revision
            or not isinstance(records, dict)
            or not 0 < len(records) <= limit
        ):
            raise ValueError("collection source scope differs")
        for key in ("capture_sha256", "metadata_source_receipt_sha256"):
            if not isinstance(source.get(key), str) or not re.fullmatch(
                r"[0-9a-f]{64}", source[key]
            ):
                raise ValueError("collection source hash differs")
        for key, record in records.items():
            if (
                not re.fullmatch(r"[1-9][0-9]*", key)
                or type(record.get("audio_bytes")) is not int
                or not 0 < record["audio_bytes"] <= fma_listening64.MAX_RANGE_BYTES
                or type(record.get("artist_id")) is not int
                or record["artist_id"] <= 0
                or not isinstance(record.get("genre_ids"), list)
                or any(type(value) is not int or value <= 0 for value in record["genre_ids"])
                or record["genre_ids"] != sorted(set(record["genre_ids"]))
            ):
                raise ValueError("collection native source record differs")
            for field in ("record_sha256", "audio_sha256"):
                if not isinstance(record.get(field), str) or not re.fullmatch(
                    r"[0-9a-f]{64}", record[field]
                ):
                    raise ValueError("collection record hash differs")
    old, new = sources["original"], sources["expanded"]
    if sum(row["audio_bytes"] for row in old["tracks"].values()) > fma_listening64.MAX_AUDIO_BYTES:
        raise ValueError("original source inventory exceeds its audio bound")
    if (
        old["metadata_source_receipt_sha256"] != new["metadata_source_receipt_sha256"]
        or new.get("baseline_sha256") != old["capture_sha256"]
        or not isinstance(old.get("manifest_sha256"), str)
        or not re.fullmatch(r"[0-9a-f]{64}", old["manifest_sha256"])
    ):
        raise ValueError("collection capture association differs")
    chosen = select_original(new["tracks"], old["tracks"])
    if manifest.get("original_track_ids") != chosen or manifest.get("expanded_track_ids") != sorted(
        map(int, new["tracks"])
    ):
        raise ValueError("collection deterministic selection differs")
    expected = set(new["tracks"]) | {str(value) for value in chosen}
    if set(manifest["tracks"]) != expected:
        raise ValueError("collection omitted expanded clips or added unselected clips")
    for key, row in manifest["tracks"].items():
        bound = new["tracks"].get(key, old["tracks"].get(key))
        if (
            _digest(row) != bound["record_sha256"]
            or row["audio_sha256"] != bound["audio_sha256"]
            or row["audio_bytes"] != bound["audio_bytes"]
            or row["artist_id"] != bound["artist_id"]
        ):
            raise ValueError("collection selected source/decode record differs")


def build_listening_collection(  # noqa: C901, PLR0912, PLR0915 -- offline source, byte, decode and selection gates.
    new_pack: Path, metadata_source: Path, baseline: Path, original_audio: Path, output: Path
) -> dict[str, Any]:
    """Verify both source captures, decode new clips only, and write a separate collection."""
    for path in (new_pack, metadata_source, baseline, original_audio, output):
        _safe(path)
    if output.exists():
        raise ValueError("collection output must be fresh")
    original = fma_playback.validate_playback_export(original_audio)
    if original["revision"] != fma_playback.REVISION:
        raise ValueError("original collection must be the unchanged single capture")
    verified = fma_large32.verify(new_pack, metadata_source, baseline)
    baseline_bytes = (baseline / "listening.json").read_bytes()
    baseline_sha = hashlib.sha256(baseline_bytes).hexdigest()
    if (
        original["source_pack_sha256"] != baseline_sha
        or verified["baseline_sha256"] != baseline_sha
    ):
        raise ValueError("original playback/baseline capture differs")
    captured = (new_pack / "listening.json").read_bytes()
    if json.loads(captured) != verified:
        raise ValueError("expanded capture changed after verification")
    original_rows = {row["track_id"]: row for row in json.loads(baseline_bytes)["tracks"]}
    if {str(value) for value in original_rows} != set(original["tracks"]):
        raise ValueError("original playback coverage differs from preserved capture")
    for key, row in original["tracks"].items():
        if row != _track(original_rows[int(key)], row["duration_seconds"]):
            raise ValueError("original source metadata or decode binding differs")
    expanded_rows = {row["track_id"]: row for row in verified["tracks"]}
    expanded = {}
    blobs = {}
    with tempfile.TemporaryDirectory(prefix="fma-collection-decode-") as temporary:
        for identity, row in expanded_rows.items():
            path = new_pack / f"{identity}.mp3"
            _safe(path)
            body = path.read_bytes()
            if (
                row["audio_path"] != path.name
                or hashlib.sha256(body).hexdigest() != row["audio_sha256"]
                or len(body) != row["audio_bytes"]
            ):
                raise ValueError("new audio capture bytes differ")
            snapshot = Path(temporary) / path.name
            snapshot.write_bytes(body)
            expanded[str(identity)] = _track(row, fma_playback.decode_duration(snapshot))
            blobs[path.name] = body
    old_inventory, new_inventory = (
        _inventory(original["tracks"], original_rows),
        _inventory(expanded, expanded_rows),
    )
    chosen = select_original(new_inventory, old_inventory)
    tracks = {**expanded, **{str(value): original["tracks"][str(value)] for value in chosen}}
    source_sha = _sha(metadata_source / "source-receipt.json")
    manifest = {
        "revision": REVISION,
        "test_only": False,
        "metadata_license": "CC-BY-4.0",
        "public_deployment_authorized": False,
        "selection_policy": POLICY,
        "original_track_ids": chosen,
        "expanded_track_ids": sorted(expanded_rows),
        "sources": {
            "original": {
                "capture_revision": fma_listening64.REVISION,
                "capture_sha256": baseline_sha,
                "manifest_sha256": _sha(original_audio / "manifest.json"),
                "metadata_source_receipt_sha256": source_sha,
                "tracks": old_inventory,
            },
            "expanded": {
                "capture_revision": fma_large32.REVISION,
                "capture_sha256": hashlib.sha256(captured).hexdigest(),
                "baseline_sha256": baseline_sha,
                "metadata_source_receipt_sha256": source_sha,
                "tracks": new_inventory,
            },
        },
        "audio_bytes": sum(row["audio_bytes"] for row in tracks.values()),
        "tracks": tracks,
    }
    validate_collection_metadata(manifest)
    encoded = canonical_json(manifest) + b"\n"
    if len(encoded) > fma_playback.MAX_MANIFEST_BYTES:
        raise ValueError("collection manifest exceeds 200 KB")
    for identity in chosen:
        path = original_audio / f"{identity}.mp3"
        body = path.read_bytes()
        if hashlib.sha256(body).hexdigest() != tracks[str(identity)]["audio_sha256"]:
            raise ValueError("original audio changed during collection assembly")
        blobs[path.name] = body
    output.mkdir(parents=True)
    for name, body in {**blobs, "manifest.json": encoded}.items():
        with (output / name).open("xb") as stream:
            stream.write(body)
    fma_playback.validate_playback_export(output)
    return manifest
