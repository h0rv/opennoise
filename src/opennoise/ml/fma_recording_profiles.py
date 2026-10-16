"""Frozen recording-supported artist profiles and descriptive source co-tags."""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np

from opennoise.ml import fma_waveform_pipeline as waveform

REVISION = "fma55-recording-profile-discovery-v1"
PROTOCOL_SHA = "fe45d4b90779ead2e096f54a6d7ab3e8440b1ebdb3982133b09beada47e02cbd"
SOURCE_SHA = "829f3f80308149fe03adfd582c45a50168b67eb61fe5ce82e2556e5ce208f729"
MAX_BYTES = 100_000_000
VIEW_BYTES = 200_000
ZERO_NORM = 1e-12
NEIGHBORS = 6
FILES = {"protocol.json", "declaration.json", "discovery.json", "receipt.json", "inventory.json"}


def evidence(ids: list[int], tracks: dict[int, Any], roster: dict[int, Any]) -> dict[str, Any]:
    """Retain exact recording support rather than inventing artist-union evidence."""
    artists = sorted({tracks[i]["artist_id"] for i in ids})
    components = sorted({roster[i]["component_id"] for i in ids})
    return {
        "track_ids": ids,
        "artist_ids": artists,
        "component_ids": components,
        "track_count": len(ids),
        "artist_count": len(artists),
        "component_count": len(components),
    }


def source_genres(manifest: dict[str, Any], roster: dict[int, Any]) -> list[dict[str, Any]]:
    """Describe same-recording source annotations across the complete visible catalog."""
    tracks = {row["track_id"]: row for row in manifest["tracks"]}
    tags = {row["genre_id"]: set() for row in manifest["genres"]}
    for identity, track in tracks.items():
        for tag in set(track["genre_ids"]):
            tags[tag].add(identity)
    rows = []
    for tag, members in sorted(tags.items()):
        links = [
            {"genre_id": other, **evidence(sorted(members & values), tracks, roster)}
            for other, values in tags.items()
            if other != tag and members & values
        ]
        links.sort(key=lambda row: (-row["track_count"], row["genre_id"]))
        rows.append(
            {
                "genre_id": tag,
                **evidence(sorted(members), tracks, roster),
                "relationships": links,
            }
        )
    return rows


def artist_rows(
    manifest: dict[str, Any],
    roster: list[dict[str, Any]],
    values: np.ndarray,
    model: dict[str, np.ndarray],
) -> list[dict[str, Any]]:
    """Aggregate all members without fitting or rehabilitating unsupported recordings."""
    tracks = manifest["tracks"]
    if len(tracks) != len(roster) or len(tracks) != len(values):
        raise ValueError("profile member roster differs")
    if [r["track_id"] for r in tracks] != [r["track_id"] for r in roster]:
        raise ValueError("profile member ordering differs")
    if len({r["track_id"] for r in tracks}) != len(tracks) or not np.isfinite(values).all():
        raise ValueError("duplicate or nonfinite profile member")
    standardized, _, reasons = waveform.transform(values, model)
    groups: dict[int, list[int]] = defaultdict(list)
    for i, track in enumerate(tracks):
        groups[track["artist_id"]].append(i)
    rows = []
    for identity, indices in sorted(groups.items()):
        indices.sort(key=lambda i: tracks[i]["track_id"])
        components = {roster[i]["component_id"] for i in indices}
        folds = {roster[i]["fold"] for i in indices}
        if len(components) != 1 or len(folds) != 1:
            raise ValueError("artist crosses frozen components or folds")
        invalid = any(reasons[i] is not None for i in indices)
        mean = None if invalid else np.mean(standardized[indices], axis=0)
        if mean is not None and not np.isfinite(mean).all():
            raise ValueError("nonfinite artist profile")
        projection_reason = (
            "unsupported_member"
            if invalid
            else None
            if bool(model["projection_usable"])
            else "projection_degenerate"
        )
        neighbor_reason = (
            "unsupported_member"
            if invalid
            else "zero_mean_norm"
            if mean is not None and np.linalg.norm(mean) <= ZERO_NORM
            else None
        )
        tags = sorted({tag for i in indices for tag in tracks[i]["genre_ids"]})
        tag_rows = []
        for tag in tags:
            members = [tracks[i]["track_id"] for i in indices if tag in tracks[i]["genre_ids"]]
            tag_rows.append({"genre_id": tag, "track_ids": members, "track_count": len(members)})
        rows.append(
            {
                "artist_id": identity,
                "track_ids": [tracks[i]["track_id"] for i in indices],
                "track_count": len(indices),
                "singleton": len(indices) == 1,
                "component_id": next(iter(components)),
                "fold": next(iter(folds)),
                "tag_evidence": tag_rows,
                "member_reasons": [
                    {"track_id": tracks[i]["track_id"], "reason": reasons[i]} for i in indices
                ],
                "vector": None if mean is None else mean.tolist(),
                "position": (mean @ model["axes"]).tolist() if projection_reason is None else None,
                "projection_reason": projection_reason,
                "neighbor_reason": neighbor_reason,
                "neighbors": [],
                "eligible_candidate_artists": 0,
                "eligible_candidate_components": 0,
            }
        )
    rank_artists(rows)
    return rows


def rank_artists(rows: list[dict[str, Any]]) -> None:
    """Use training profiles, exclude entire components, and preserve native-ID ties."""
    candidates = [r for r in rows if r["fold"] == 0 and r["neighbor_reason"] is None]
    units = {}
    for row in rows:
        if row["neighbor_reason"] is None:
            vector = np.asarray(row["vector"])
            units[row["artist_id"]] = vector / np.linalg.norm(vector)
    for row in rows:
        pool = [r for r in candidates if r["component_id"] != row["component_id"]]
        row["eligible_candidate_artists"] = len(pool)
        row["eligible_candidate_components"] = len({r["component_id"] for r in pool})
        if row["neighbor_reason"] is not None:
            continue
        ordered = sorted(
            pool,
            key=lambda other: (
                float(1 - np.dot(units[row["artist_id"]], units[other["artist_id"]])),
                other["artist_id"],
            ),
        )
        seen = set()
        for other in ordered:
            if other["component_id"] not in seen:
                row["neighbors"].append(other["artist_id"])
                seen.add(other["component_id"])
            if len(row["neighbors"]) == NEIGHBORS:
                break
        if not row["neighbors"]:
            row["neighbor_reason"] = "no_eligible_components"


def calculate(source: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    """Reuse immutable saved waveform values and training-only parameters."""
    declaration = json.loads(waveform.read(source / "declaration.json"))
    roster = declaration["roster"]
    with (
        np.load(source / "features.npz", allow_pickle=False) as saved,
        np.load(source / "model.npz", allow_pickle=False) as fitted,
    ):
        artists = artist_rows(manifest, roster, saved["values"], dict(fitted))
    genres = source_genres(manifest, {r["track_id"]: r for r in roster})
    eligible = [
        r
        for r in artists
        if r["fold"] == 0 and r["neighbor_reason"] in (None, "no_eligible_components")
    ]
    return {
        "revision": REVISION,
        "candidate_manifest_sha256": waveform.MANIFEST_SHA,
        "waveform_inventory_sha256": SOURCE_SHA,
        "protocol_sha256": PROTOCOL_SHA,
        "claims": {
            "musical_quality_validated": False,
            "new_fit": False,
            "new_evaluation": False,
            "artist_style_inference": False,
            "genre_relationships": (
                "All visible catalog source co-tags, not training/evaluation input"
            ),
        },
        "counts": {
            "tracks": len(manifest["tracks"]),
            "artists": len(artists),
            "genres": len(genres),
            "observed_genres": sum(r["track_count"] > 0 for r in genres),
            "singleton_artists": sum(r["singleton"] for r in artists),
            "eligible_training_artists": len(eligible),
            "eligible_training_components": len({r["component_id"] for r in eligible}),
        },
        "artists": artists,
        "genres": genres,
    }


def inputs(source: Path, manifest: Path) -> dict[str, Any]:
    """Require reviewed input identity and the original closed waveform validation."""
    if waveform.digest(waveform.read(source / "inventory.json")) != SOURCE_SHA:
        raise ValueError("unreviewed waveform inventory")
    waveform.validate_waveform_pack(source, manifest)
    return waveform.candidate(manifest)


def freeze(source: Path, manifest: Path, protocol: Path, output: Path) -> dict[str, Any]:
    """Bind exact input bytes, implementation and tools before deriving profiles."""
    inputs(source, manifest)
    if waveform.digest(waveform.read(protocol)) != PROTOCOL_SHA or output.exists():
        raise ValueError("protocol or fresh declaration path differs")
    base = Path(__file__).parents[3]
    code = [
        Path(__file__),
        Path(waveform.__file__),
        base / "scripts/build_fma_recording_profiles.py",
        base / "tests/test_fma_recording_profiles.py",
    ]
    result = {
        "revision": "fma55-recording-profile-declaration-v1",
        "protocol_sha256": PROTOCOL_SHA,
        "waveform_inventory_sha256": SOURCE_SHA,
        "candidate_manifest_sha256": waveform.MANIFEST_SHA,
        "source": str(source.resolve()),
        "candidate_manifest": str(manifest.resolve()),
        "protocol": str(protocol.resolve()),
        "inputs": {
            str(p.resolve()): waveform.binding(p)
            for p in (source / "inventory.json", manifest, protocol)
        },
        "implementation": {str(p.resolve()): waveform.binding(p) for p in code},
        "tools": {"numpy": np.__version__, "python": sys.version},
        "limits": {"wall_seconds": 120, "memory_bytes": 1_000_000_000, "output_bytes": MAX_BYTES},
    }
    waveform.write(output, result)
    return result


def check_declaration(value: dict[str, Any]) -> None:
    """Validate portable declaration scope without requiring original absolute paths."""
    if (
        value["revision"] != "fma55-recording-profile-declaration-v1"
        or value["protocol_sha256"] != PROTOCOL_SHA
        or value["waveform_inventory_sha256"] != SOURCE_SHA
        or value["candidate_manifest_sha256"] != waveform.MANIFEST_SHA
        or value["limits"]
        != {"wall_seconds": 120, "memory_bytes": 1_000_000_000, "output_bytes": MAX_BYTES}
    ):
        raise ValueError("profile declaration scope differs")
    expected = {
        str(Path(value["source"]) / "inventory.json"): SOURCE_SHA,
        value["candidate_manifest"]: waveform.MANIFEST_SHA,
        value["protocol"]: PROTOCOL_SHA,
    }
    if {name: row["sha256"] for name, row in value["inputs"].items()} != expected:
        raise ValueError("profile declaration input bindings differ")


def inventory(pack: Path) -> dict[str, Any]:
    """Bind the fixed four noninventory files, without external path traversal."""
    return {name: waveform.binding(pack / name) for name in sorted(FILES - {"inventory.json"})}


def run(declaration_path: Path, output: Path) -> dict[str, Any]:
    """Build once under the frozen protocol, leaving old artifacts unchanged."""
    declaration = json.loads(waveform.read(declaration_path))
    check_declaration(declaration)
    if declaration["tools"] != {"numpy": np.__version__, "python": sys.version}:
        raise ValueError("profile tools differ")
    for group in ("inputs", "implementation"):
        for name, expected in declaration[group].items():
            if waveform.binding(Path(name)) != expected:
                raise ValueError("frozen profile input or code changed")
    source, manifest = Path(declaration["source"]), Path(declaration["candidate_manifest"])
    result = calculate(source, inputs(source, manifest))
    if output.exists() or any(p.is_symlink() for p in (output, *output.parents)):
        raise ValueError("profile output must be fresh and nonsymlinked")
    output.mkdir(parents=True)
    (output / "declaration.json").write_bytes(waveform.read(declaration_path))
    (output / "protocol.json").write_bytes(waveform.read(Path(declaration["protocol"])))
    waveform.write(output / "discovery.json", result)
    if (output / "discovery.json").stat().st_size > VIEW_BYTES:
        raise ValueError("profile view exceeds bound")
    waveform.write(
        output / "receipt.json",
        {
            "revision": "fma55-recording-profile-receipt-v1",
            "files": {
                name: waveform.binding(output / name)
                for name in ("protocol.json", "declaration.json", "discovery.json")
            },
            "waveform_inventory_sha256": SOURCE_SHA,
            "candidate_manifest_sha256": waveform.MANIFEST_SHA,
            "protocol_sha256": PROTOCOL_SHA,
        },
    )
    waveform.write(output / "inventory.json", inventory(output))
    return validate_discovery_pack(
        output, manifest, source, waveform.digest(waveform.read(output / "inventory.json"))
    )


def validate_discovery_pack(
    pack: Path, candidate_manifest: Path, waveform_pack: Path, inventory_sha256: str
) -> dict[str, Any]:
    """Verify a reviewed closed pack against exact external inputs and deterministic replay."""
    body = waveform.read(pack / "inventory.json", VIEW_BYTES)
    if waveform.digest(body) != inventory_sha256:
        raise ValueError("profile inventory review pin differs")
    if {p.name for p in pack.iterdir()} != FILES or pack.is_symlink():
        raise ValueError("profile inventory not closed")
    recorded = json.loads(body)
    if (
        inventory(pack) != recorded
        or sum(r["bytes"] for r in recorded.values()) + len(body) > MAX_BYTES
    ):
        raise ValueError("profile inventory bindings differ")
    if waveform.digest(waveform.read(pack / "protocol.json")) != PROTOCOL_SHA:
        raise ValueError("profile protocol differs")
    check_declaration(json.loads(waveform.read(pack / "declaration.json")))
    receipt = json.loads(waveform.read(pack / "receipt.json"))
    expected_receipt = {
        "revision": "fma55-recording-profile-receipt-v1",
        "files": {
            name: waveform.binding(pack / name)
            for name in ("protocol.json", "declaration.json", "discovery.json")
        },
        "waveform_inventory_sha256": SOURCE_SHA,
        "candidate_manifest_sha256": waveform.MANIFEST_SHA,
        "protocol_sha256": PROTOCOL_SHA,
    }
    if receipt != expected_receipt:
        raise ValueError("profile receipt differs")
    manifest = inputs(waveform_pack, candidate_manifest)
    actual = json.loads(waveform.read(pack / "discovery.json", VIEW_BYTES))
    if actual != calculate(waveform_pack, manifest):
        raise ValueError("profiles differ from frozen replay")
    return actual
