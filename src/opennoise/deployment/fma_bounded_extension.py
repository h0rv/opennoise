"""Offline extensions authorized by individually reviewed, immutable recipe hashes.

The generic format keeps flat native inventories instead of embedding earlier
manifests. A generated recipe is only a review candidate until its exact hash is
registered here; freezing a recipe does not authorize an arbitrary collection.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import tempfile
from pathlib import Path
from typing import Any, cast

from opennoise.common import canonical_json
from opennoise.deployment import fma_listening_collection as collection
from opennoise.deployment import fma_playback

REVISION = "fma-local-bounded-extension-v1"
RECIPE_REVISION = "fma-reviewed-extension-recipe-v1"
MAX_ADDITIONS = 12
ORIGINAL_CLIPS = 60
MAX_CLIPS = 64
MAX_AUDIO_BYTES = 64_000_000
MAX_INPUT_BYTES = 2_000_000
MAX_RECIPE_BYTES = 20_000
# Add only a custody-reviewed recipe; never accept an arbitrary command-line pin.
APPROVED_RECIPES: frozenset[str] = frozenset(
    {
        "9ebbe4940e3e806bfcfdd7724fdd4b37dbc1a51978d788d8a40b908b863e3d24",
    }
)
POLICY = (
    "retain every prior added clip and frozen paired originals; at most 12 new clips; 64 clips/64MB"
)


def _digest(value: object) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def _read(path: Path, limit: int = MAX_INPUT_BYTES) -> bytes:
    collection._safe(path)  # noqa: SLF001 -- unchanged path custody boundary.
    if not path.is_file() or not 0 < path.stat().st_size <= limit:
        raise ValueError("bounded extension input missing or oversized")
    return path.read_bytes()


def _ids(values: object) -> list[int]:
    if (
        not isinstance(values, list)
        or any(type(value) is not int or value <= 0 for value in values)
        or len(set(values)) != len(values)
    ):
        raise ValueError("bounded extension native IDs differ")
    return cast("list[int]", values)


def _inputs(
    original_audio: Path, parent_audio: Path, capture_root: Path, proposal: Path
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, str]]:
    original = fma_playback.validate_playback_export(original_audio)
    parent = fma_playback.validate_playback_export(parent_audio)
    paths = {
        "original_manifest": original_audio / "manifest.json",
        "parent_manifest": parent_audio / "manifest.json",
        "capture": capture_root / "listening.json",
        "proposal": proposal,
    }
    bodies = {key: _read(path) for key, path in paths.items()}
    if (
        json.loads(bodies["original_manifest"]) != original
        or json.loads(bodies["parent_manifest"]) != parent
    ):
        raise ValueError("bounded extension source changed after verification")
    hashes = {key: hashlib.sha256(body).hexdigest() for key, body in bodies.items()}
    return original, parent, json.loads(bodies["capture"]), json.loads(bodies["proposal"]), hashes


def _core(
    original: dict[str, Any],
    parent: dict[str, Any],
    capture: dict[str, Any],
    proposal: dict[str, Any],
    hashes: dict[str, str],
) -> dict[str, Any]:
    plan = proposal["expanded_view_plan"]
    originals = _ids(plan["retained_original_ids"])
    prior = _ids(plan["retained_added_ids"])
    added_ids = _ids(plan["new_ids"])
    wanted = _ids(plan["track_ids"])
    required = _ids(proposal["protected_original_ids"])
    parent_added = _ids(parent["expanded_track_ids"])
    if (
        original["revision"] != fma_playback.REVISION
        or len(original["tracks"]) != ORIGINAL_CLIPS
        or set(prior) != set(parent_added)
        or not 1 <= len(added_ids) <= MAX_ADDITIONS
        or set(added_ids) & (set(map(int, original["tracks"])) | set(parent_added))
        or not set(required) <= set(originals)
        or not set(originals) <= set(map(int, original["tracks"]))
        or set(originals) & set(prior)
        or set(wanted) != set(originals + prior + added_ids)
        or len(wanted) > MAX_CLIPS
    ):
        raise ValueError("bounded extension selection or preserved cohort differs")
    origin = parent["sources"]["original"]
    if (
        origin["manifest_sha256"] != hashes["original_manifest"]
        or origin["capture_sha256"] != original["source_pack_sha256"]
        or set(origin["tracks"]) != set(original["tracks"])
        or any(
            origin["tracks"][key]["record_sha256"] != _digest(row)
            for key, row in original["tracks"].items()
        )
        or capture.get("source_receipt_sha256") != origin["metadata_source_receipt_sha256"]
        or capture.get("proposal_sha256") != hashes["proposal"]
        or capture.get("test_only") is True
        or capture.get("public_deployment_authorized") is not False
        or capture.get("musical_quality_validated") is not False
    ):
        raise ValueError("bounded extension source or proposal association differs")
    native = {row["track_id"]: row for row in capture["tracks"]}
    proposed = {row["track_id"]: row for row in proposal["tracks"]}
    if (
        len(native) != len(capture["tracks"])
        or len(proposed) != len(proposal["tracks"])
        or set(native) != set(added_ids)
        or set(proposed) != set(added_ids)
    ):
        raise ValueError("bounded extension capture roster differs")
    added = {}
    for identity, row in native.items():
        if (
            type(row["track_id"]) is not int
            or type(row["artist_id"]) is not int
            or row["artist_id"] <= 0
            or _ids(row["genre_ids"]) != sorted(row["genre_ids"])
            or any(
                row[field] != proposed[identity][field]
                for field in ("artist_id", "genre_ids", "source", "member")
            )
            or row["audio_path"] != f"{identity}.mp3"
            or type(row["audio_bytes"]) is not int
            or not 0 < row["audio_bytes"] <= MAX_INPUT_BYTES
            or row["source"]["license_url"] not in fma_playback.LICENSES
            or type(row["duration_seconds"]) not in (int, float)
            or not math.isfinite(row["duration_seconds"])
            or not 0 < row["duration_seconds"] <= fma_playback.MAX_DURATION_SECONDS
            or not re.fullmatch(r"[0-9a-f]{64}", row["audio_sha256"])
        ):
            raise ValueError("bounded extension native source or license differs")
        added[str(identity)] = collection._track(row, row["duration_seconds"])  # noqa: SLF001 -- unchanged native credit/decode contract.
    tracks = {
        **{str(identity): original["tracks"][str(identity)] for identity in originals},
        **{str(identity): parent["tracks"][str(identity)] for identity in prior},
        **added,
    }
    total = sum(row["audio_bytes"] for row in tracks.values())
    if total > MAX_AUDIO_BYTES or total > plan["audio_bytes_bound"]:
        raise ValueError("bounded extension audio budget exceeded")
    sources = json.loads(json.dumps(parent["sources"]))
    sources["expanded"]["tracks"].update(collection._inventory(added, native))  # noqa: SLF001
    sources["expanded"]["capture_revision"] = REVISION
    sources["expanded"]["capture_sha256"] = hashes["capture"]
    # Immediate parent binding replaces history, rather than recursively growing it.
    sources["expanded"].pop("parent_capture_sha256", None)
    return {
        "revision": REVISION,
        "test_only": False,
        "metadata_license": "CC-BY-4.0",
        "public_deployment_authorized": False,
        "selection_policy": POLICY,
        "original_track_ids": originals,
        "expanded_track_ids": sorted(prior + added_ids),
        "sources": sources,
        "source_bindings": hashes,
        "audio_bytes": total,
        "tracks": tracks,
    }


def freeze(
    original_audio: Path, parent_audio: Path, capture_root: Path, proposal: Path, output: Path
) -> dict[str, Any]:
    """Write an unapproved review recipe; this operation cannot authorize export."""
    collection._safe(output)  # noqa: SLF001
    if output.exists():
        raise ValueError("recipe output must be fresh")
    original, parent, capture, proposed, hashes = _inputs(
        original_audio, parent_audio, capture_root, proposal
    )
    core = _core(original, parent, capture, proposed, hashes)
    recipe = {
        "revision": RECIPE_REVISION,
        "source_bindings": hashes,
        "manifest_core_sha256": _digest(core),
        "new_track_ids": proposed["expanded_view_plan"]["new_ids"],
        "limits": {
            "new_clips": MAX_ADDITIONS,
            "clips": 64,
            "audio_bytes": 64_000_000,
            "clip_bytes": 2_000_000,
            "manifest_bytes": 200_000,
        },
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(canonical_json(recipe) + b"\n")
    return recipe


def validate_bounded_metadata(manifest: dict[str, Any]) -> None:
    """Require a reviewed recipe and exact flat manifest, including every source field."""
    recipe = manifest.get("recipe")
    if not isinstance(recipe, dict) or _digest(recipe) not in APPROVED_RECIPES:
        raise ValueError("bounded extension recipe has not been approved")
    core = {key: value for key, value in manifest.items() if key != "recipe"}
    if (
        recipe.get("revision") != RECIPE_REVISION
        or recipe.get("manifest_core_sha256") != _digest(core)
        or recipe.get("source_bindings") != manifest.get("source_bindings")
        or manifest.get("revision") != REVISION
    ):
        raise ValueError("bounded extension differs from reviewed source records")


def build(  # noqa: PLR0913, PLR0917 -- explicit immutable source and fresh destination paths.
    original_audio: Path,
    parent_audio: Path,
    capture_root: Path,
    proposal: Path,
    recipe_path: Path,
    output: Path,
) -> dict[str, Any]:
    """Reverify source hashes and full new-clip decodes before creating an approved view."""
    collection._safe(output)  # noqa: SLF001
    if output.exists():
        raise ValueError("bounded extension output must be fresh")
    recipe = json.loads(_read(recipe_path, MAX_RECIPE_BYTES))
    if _digest(recipe) not in APPROVED_RECIPES:
        raise ValueError("bounded extension recipe has not been approved")
    original, parent, capture, proposed, hashes = _inputs(
        original_audio, parent_audio, capture_root, proposal
    )
    manifest = {**_core(original, parent, capture, proposed, hashes), "recipe": recipe}
    validate_bounded_metadata(manifest)
    encoded = canonical_json(manifest) + b"\n"
    if len(encoded) > fma_playback.MAX_MANIFEST_BYTES:
        raise ValueError("bounded extension manifest exceeds 200KB")
    blobs = {}
    new_ids = set(map(str, recipe["new_track_ids"]))
    for identity, row in manifest["tracks"].items():
        directory = original_audio if identity in original["tracks"] else parent_audio
        if identity in new_ids:
            directory = capture_root
        path = directory / row["audio_path"]
        body = _read(path)
        if (
            len(body) != row["audio_bytes"]
            or hashlib.sha256(body).hexdigest() != row["audio_sha256"]
        ):
            raise ValueError("bounded extension audio differs from frozen source")
        if identity in new_ids:
            with tempfile.TemporaryDirectory(prefix="fma-extension-decode-") as temporary:
                snapshot = Path(temporary) / path.name
                snapshot.write_bytes(body)
                if fma_playback.decode_duration(snapshot) != row["duration_seconds"]:
                    raise ValueError("bounded extension full decode differs")
        blobs[path.name] = body
    output.mkdir(parents=True)
    for name, body in {**blobs, "manifest.json": encoded}.items():
        (output / name).write_bytes(body)
    return fma_playback.validate_playback_export(output)
