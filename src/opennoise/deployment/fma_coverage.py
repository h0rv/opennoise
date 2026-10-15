"""Reviewed, disjoint coverage additions beside two unchanged listening collections."""

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

REVISION = "fma-local-coverage-v1"
RECIPE_REVISION = "fma-reviewed-coverage-recipe-v1"
MAX_CLIPS = 12
MAX_UNION = 128
APPROVED_RECIPES: frozenset[str] = frozenset(
    {
        "a3a15f7134fbaea3c1a19b0ac10fd1e00179dc7421bc2aab34dad8b89cb4d950",
    }
)


def _core(
    original: dict[str, Any],
    parent: dict[str, Any],
    capture: dict[str, Any],
    proposal: dict[str, Any],
    hashes: dict[str, str],
) -> dict[str, Any]:
    plan = proposal["third_view_plan"]
    ids = bounded._ids(plan["new_ids"])  # noqa: SLF001 -- same strict native ID boundary.
    prior = set(original["tracks"]) | set(parent["tracks"])
    native = {str(row["track_id"]): row for row in capture["tracks"]}
    proposed = {str(row["track_id"]): row for row in proposal["tracks"]}
    source = parent["sources"]["original"]
    if (
        plan.get("key") != "coverage"
        or plan.get("original_and_expanded_unchanged") is not True
        or plan.get("disjoint_from_prior_collections") is not True
        or not 0 < len(ids) <= MAX_CLIPS
        or set(bounded._ids(plan["track_ids"])) != set(ids)  # noqa: SLF001
        or len(native) != len(capture["tracks"])
        or len(proposed) != len(proposal["tracks"])
        or set(native) != set(map(str, ids))
        or set(proposed) != set(native)
        or set(native) & prior
        or len(prior | set(native)) > MAX_UNION
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
        raise ValueError("coverage source, disjoint roster or unchanged parent binding differs")
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
    total = sum(row["audio_bytes"] for row in tracks.values())
    if total > bounded.MAX_AUDIO_BYTES or total > plan["audio_bytes_bound"]:
        raise ValueError("coverage audio budget exceeded")
    return {
        "revision": REVISION,
        "test_only": False,
        "metadata_license": "CC-BY-4.0",
        "public_deployment_authorized": False,
        "source_bindings": hashes,
        "metadata_source_receipt_sha256": source["metadata_source_receipt_sha256"],
        "native_inventory": collection._inventory(tracks, {int(k): v for k, v in native.items()}),  # noqa: SLF001
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


def freeze(
    original_audio: Path, parent_audio: Path, capture_root: Path, proposal: Path, output: Path
) -> dict[str, Any]:
    """Freeze a review candidate without approving it or writing any playback audio."""
    collection._safe(output)  # noqa: SLF001
    if output.exists():
        raise ValueError("coverage recipe output must be fresh")
    inputs = bounded._inputs(original_audio, parent_audio, capture_root, proposal)  # noqa: SLF001
    core = _core(*inputs)
    recipe = {
        "revision": RECIPE_REVISION,
        "source_bindings": inputs[-1],
        "manifest_core_sha256": bounded._digest(core),  # noqa: SLF001
        "limits": {
            "new_clips": MAX_CLIPS,
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
        **_core(*bounded._inputs(original_audio, parent_audio, capture_root, proposal)),  # noqa: SLF001
        "recipe": recipe,
    }
    validate_coverage_metadata(manifest)
    encoded = canonical_json(manifest) + b"\n"
    if len(encoded) > fma_playback.MAX_MANIFEST_BYTES:
        raise ValueError("coverage manifest exceeds existing byte bound")
    blobs = {}
    for row in manifest["tracks"].values():
        body = bounded._read(capture_root / row["audio_path"])  # noqa: SLF001
        if (
            len(body) != row["audio_bytes"]
            or hashlib.sha256(body).hexdigest() != row["audio_sha256"]
        ):
            raise ValueError("coverage audio differs from frozen capture")
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
