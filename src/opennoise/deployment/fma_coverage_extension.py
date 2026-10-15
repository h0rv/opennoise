"""Separately reviewed five-clip extension preserving the original twelve coverage clips."""

from __future__ import annotations

import hashlib
import json
import math
import re
import tempfile
from pathlib import Path
from typing import Any

from opennoise.common import canonical_json
from opennoise.deployment import fma_bounded_extension as bounded
from opennoise.deployment import fma_listening_collection as collection
from opennoise.deployment import fma_playback

REVISION = "fma-local-coverage-extension-v2"
RECIPE_REVISION = "fma-reviewed-coverage-extension-recipe-v2"
MAX_CLIPS = 17
MAX_NEW_CLIPS = 5
PRIOR_CLIPS = 12
MAX_UNION = 133
APPROVED_RECIPES: frozenset[str] = frozenset(
    {"38733b8ea19f9b8305913cff9ffdf8b958f3745b5131693a87c4a12389af96f0"}
)


def _inputs(
    original_audio: Path,
    parent_audio: Path,
    coverage_audio: Path,
    capture_root: Path,
    proposal: Path,
) -> tuple[
    dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, str], dict[str, Any]
]:
    original, parent, capture, proposed, hashes = bounded._inputs(  # noqa: SLF001 -- unchanged source validation.
        original_audio, parent_audio, capture_root, proposal
    )
    previous = fma_playback.validate_playback_export(coverage_audio)
    body = bounded._read(coverage_audio / "manifest.json")  # noqa: SLF001
    if json.loads(body) != previous:
        raise ValueError("coverage parent changed after validation")
    hashes["coverage_manifest"] = hashlib.sha256(body).hexdigest()
    return original, parent, capture, proposed, hashes, previous


def _core(  # noqa: PLR0913, PLR0917 -- explicit frozen source boundaries.
    original: dict[str, Any],
    parent: dict[str, Any],
    capture: dict[str, Any],
    proposal: dict[str, Any],
    hashes: dict[str, str],
    previous: dict[str, Any],
) -> dict[str, Any]:
    plan = proposal["coverage_view_plan"]
    ids = bounded._ids(plan["new_ids"])  # noqa: SLF001 -- same strict native ID boundary.
    prior = set(original["tracks"]) | set(parent["tracks"])
    native = {str(row["track_id"]): row for row in capture["tracks"]}
    proposed = {str(row["track_id"]): row for row in proposal["tracks"]}
    source = parent["sources"]["original"]
    retained = bounded._ids(plan["retained_ids"])  # noqa: SLF001
    if (
        plan.get("key") != "coverage"
        or not 0 < len(ids) <= MAX_NEW_CLIPS
        or previous["revision"] != fma_playback.COVERAGE_REVISION
        or len(previous["tracks"]) != PRIOR_CLIPS
        or set(map(str, retained)) != set(previous["tracks"])
        or set(bounded._ids(plan["track_ids"])) != set(ids + retained)  # noqa: SLF001
        or len(native) != len(capture["tracks"])
        or len(proposed) != len(proposal["tracks"])
        or set(native) != set(map(str, ids))
        or set(proposed) != set(native)
        or set(native) & (prior | set(previous["tracks"]))
        or len(native) + len(previous["tracks"]) > MAX_CLIPS
        or len(prior | set(previous["tracks"]) | set(native)) > MAX_UNION
        or previous["prior_track_ids"] != sorted(map(int, prior))
        or previous["metadata_source_receipt_sha256"] != source["metadata_source_receipt_sha256"]
        or previous["source_bindings"]["original_manifest"] != hashes["original_manifest"]
        or previous["source_bindings"]["parent_manifest"] != hashes["parent_manifest"]
        or original["revision"] != fma_playback.REVISION
        or source["manifest_sha256"] != hashes["original_manifest"]
        or source["capture_sha256"] != original["source_pack_sha256"]
        or set(source["tracks"]) != set(original["tracks"])
        or capture.get("source_receipt_sha256") != source["metadata_source_receipt_sha256"]
        or capture.get("proposal_sha256") != hashes["proposal"]
        or capture.get("test_only") is True
        or capture.get("public_deployment_authorized") is not False
        or capture.get("musical_quality_validated") is not False
    ):
        raise ValueError("coverage extension source, preserved roster or parent binding differs")
    tracks = {}
    for key, row in native.items():
        if (
            type(row["track_id"]) is not int
            or row["track_id"] <= 0
            or type(row["artist_id"]) is not int
            or row["artist_id"] <= 0
            or bounded._ids(row["genre_ids"]) != sorted(row["genre_ids"])  # noqa: SLF001
            or any(
                row[field] != proposed[key][field]
                for field in ("artist_id", "genre_ids", "source", "member")
            )
            or row["audio_path"] != f"{key}.mp3"
            or type(row["audio_bytes"]) is not int
            or not 0 < row["audio_bytes"] <= bounded.MAX_INPUT_BYTES
            or row["source"]["license_url"] not in fma_playback.LICENSES
            or type(row["duration_seconds"]) not in (int, float)
            or not math.isfinite(row["duration_seconds"])
            or not 0 < row["duration_seconds"] <= fma_playback.MAX_DURATION_SECONDS
            or not re.fullmatch(r"[0-9a-f]{64}", row["audio_sha256"])
        ):
            raise ValueError("coverage native source, license or audio bounds differ")
        tracks[key] = collection._track(row, row["duration_seconds"])  # noqa: SLF001 -- identical source/decode representation.
    new_bytes = sum(row["audio_bytes"] for row in tracks.values())
    inventory = {
        **previous["native_inventory"],
        **collection._inventory(  # noqa: SLF001 -- flat native records.
            tracks, {int(k): v for k, v in native.items()}
        ),
    }
    tracks = {**previous["tracks"], **tracks}
    total = sum(row["audio_bytes"] for row in tracks.values())
    if (
        new_bytes > plan["new_audio_bytes_bound"]
        or total > bounded.MAX_AUDIO_BYTES
        or total > plan["audio_bytes_bound"]
    ):
        raise ValueError("coverage audio budget exceeded")
    return {
        "revision": REVISION,
        "test_only": False,
        "metadata_license": "CC-BY-4.0",
        "public_deployment_authorized": False,
        "source_bindings": hashes,
        "metadata_source_receipt_sha256": source["metadata_source_receipt_sha256"],
        "native_inventory": inventory,
        "retained_coverage_track_ids": sorted(retained),
        "prior_track_ids": sorted(map(int, prior)),
        "audio_bytes": total,
        "tracks": tracks,
    }


def validate_coverage_metadata(manifest: dict[str, Any]) -> None:
    """Only an individually reviewed exact core may enter a collection export."""
    recipe = manifest.get("recipe")
    if not isinstance(recipe, dict) or bounded._digest(recipe) not in APPROVED_RECIPES:  # noqa: SLF001
        raise ValueError("coverage recipe has not been approved")
    core = {key: value for key, value in manifest.items() if key != "recipe"}
    if (
        recipe.get("revision") != RECIPE_REVISION
        or manifest.get("revision") != REVISION
        or recipe.get("manifest_core_sha256") != bounded._digest(core)  # noqa: SLF001
        or recipe.get("source_bindings") != manifest.get("source_bindings")
        or not 0 < len(manifest["tracks"]) <= MAX_CLIPS
    ):
        raise ValueError("coverage differs from reviewed source records")


def freeze(  # noqa: PLR0913, PLR0917 -- explicit sources and fresh destination.
    original_audio: Path,
    parent_audio: Path,
    coverage_audio: Path,
    capture_root: Path,
    proposal: Path,
    output: Path,
) -> dict[str, Any]:
    """Freeze a review candidate without approving it or writing any playback audio."""
    collection._safe(output)  # noqa: SLF001
    if output.exists():
        raise ValueError("coverage recipe output must be fresh")
    inputs = _inputs(original_audio, parent_audio, coverage_audio, capture_root, proposal)
    core = _core(*inputs)
    recipe = {
        "revision": RECIPE_REVISION,
        "source_bindings": inputs[4],
        "manifest_core_sha256": bounded._digest(core),  # noqa: SLF001
        "limits": {
            "new_clips": MAX_NEW_CLIPS,
            "coverage_clips": MAX_CLIPS,
            "union_clips": MAX_UNION,
            "clip_bytes": bounded.MAX_INPUT_BYTES,
            "manifest_bytes": 200_000,
        },
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(canonical_json(recipe) + b"\n")
    return recipe


def build(  # noqa: PLR0913, PLR0917 -- explicit source and fresh destination paths.
    original_audio: Path,
    parent_audio: Path,
    coverage_audio: Path,
    capture_root: Path,
    proposal: Path,
    recipe_path: Path,
    output: Path,
) -> dict[str, Any]:
    """Replay frozen bindings and decode exact local snapshots before writing coverage."""
    collection._safe(output)  # noqa: SLF001
    if output.exists():
        raise ValueError("coverage output must be fresh")
    recipe = json.loads(bounded._read(recipe_path, bounded.MAX_RECIPE_BYTES))  # noqa: SLF001
    if bounded._digest(recipe) not in APPROVED_RECIPES:  # noqa: SLF001
        raise ValueError("coverage recipe has not been approved")
    manifest = {
        **_core(*_inputs(original_audio, parent_audio, coverage_audio, capture_root, proposal)),
        "recipe": recipe,
    }
    validate_coverage_metadata(manifest)
    encoded = canonical_json(manifest) + b"\n"
    if len(encoded) > fma_playback.MAX_MANIFEST_BYTES:
        raise ValueError("coverage manifest exceeds existing byte bound")
    blobs = {}
    retained = set(manifest["retained_coverage_track_ids"])
    for row in manifest["tracks"].values():
        source = coverage_audio if row["track_id"] in retained else capture_root
        body = bounded._read(source / row["audio_path"])  # noqa: SLF001
        if (
            len(body) != row["audio_bytes"]
            or hashlib.sha256(body).hexdigest() != row["audio_sha256"]
        ):
            raise ValueError("coverage audio differs from frozen capture")
        if row["track_id"] not in retained:
            with tempfile.TemporaryDirectory(prefix="fma-coverage-decode-") as temporary:
                snapshot = Path(temporary) / row["audio_path"]
                snapshot.write_bytes(body)
                if fma_playback.decode_duration(snapshot) != row["duration_seconds"]:
                    raise ValueError("coverage full decode differs")
        blobs[row["audio_path"]] = body
    output.mkdir(parents=True)
    for name, body in {**blobs, "manifest.json": encoded}.items():
        (output / name).write_bytes(body)
    return fma_playback.validate_playback_export(output)
