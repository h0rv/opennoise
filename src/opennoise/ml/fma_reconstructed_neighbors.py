"""Versioned attached-pool inference from the reconstructed original-training baseline."""

# ruff: noqa: SLF001, PLR0913, PLR0917 -- shared custody/ranking internals and explicit independent input paths.
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import numpy as np

from opennoise.common import canonical_json
from opennoise.deployment.fma_playback import validate_playback_export
from opennoise.ml import fma_acoustic_baseline as baseline
from opennoise.ml import fma_playable_neighbors as shared
from opennoise.ml import fma_related_tracks

REVISION = "fma-reconstructed-component-neighbors-v3"
NATIVE_DECLARATION_SHA256 = "96647a4ae15a9c0c1c20592128f2c75361599d899ede77414a17f45925f37041"
MODEL_SHA256 = "eb5e8091837dff54c1d373c660f7c722ad5f8a7eb6393493f972e2e7878bbb38"
POLICY = {
    **shared.POLICY,
    "revision": REVISION,
    "normalization": (
        "unchanged frozen original-training model; finite absolute standardized offset <=12"
    ),
}


def verify_feature_pins(features: Path) -> None:
    """Require the exact restored descriptor arrays, regardless of rewritten receipt hashes."""
    receipt = shared._json(features / "projection-receipt.json")
    for name, expected in (
        ("features.float32", shared.FEATURE_SHA),
        ("track_ids.uint32", shared.ID_SHA),
    ):
        binding = shared._binding(features / name)
        if binding != receipt["files"][name] or binding["sha256"] != expected:
            raise ValueError("reconstructed native feature array pin differs")


def _load(pack: Path, features: Path, metadata: Path, native_declaration: Path) -> tuple[Any, ...]:
    """Verify reconstruction custody and native components without fitting any model."""
    declaration = shared._json(native_declaration)
    evaluation = shared._json(pack / "evaluation.json")
    verify_feature_pins(features)
    if (
        shared._binding(native_declaration)["sha256"] != NATIVE_DECLARATION_SHA256
        or shared._binding(pack / "model.npz")["sha256"] != MODEL_SHA256
    ):
        raise ValueError("reconstructed original-training identity differs")
    for name, binding in evaluation["artifacts"].items():
        if Path(name).name != name or shared._binding(pack / name) != binding:
            raise ValueError("reconstructed baseline artifact differs")
    if (
        evaluation["declaration_sha256"] != shared._binding(native_declaration)["sha256"]
        or (pack / "declaration.json").read_bytes() != native_declaration.read_bytes()
        or evaluation["revision"] != declaration["revision"]
        or evaluation["metadata_receipt_sha256"]
        != shared._binding(metadata / "corpus-receipt.json")["sha256"]
        or evaluation["feature_receipt_sha256"]
        != shared._binding(features / "projection-receipt.json")["sha256"]
    ):
        raise ValueError("reconstructed source association differs")
    tracks, _, _ = baseline.load_metadata(metadata, declaration)
    ids, values, duplicates, _ = baseline.load_features(features, native_declaration)
    components = baseline.native_components(tracks, duplicates)
    roles = list(baseline._json_rows(pack / "native-folds.jsonl.zst"))
    expected = [
        {
            "track_id": t.track_id,
            "artist_id": t.artist_id,
            "artist_known": t.artist_known,
            "album_id": t.album_id,
            "component_id": components.get(t.artist_id),
            "fold": baseline.artist_group_fold(components[t.artist_id]) if t.artist_id else -1,
        }
        for t in tracks
    ]
    if roles != expected:
        raise ValueError("reconstructed native folds/components differ")
    with np.load(pack / "model.npz", allow_pickle=False) as archive:
        model = {key: archive[key] for key in ("center", "scale", "active_columns")}
    if (
        model["center"].shape != (44,)
        or model["scale"].shape != (44,)
        or not np.isfinite(model["center"]).all()
        or not np.isfinite(model["scale"]).all()
        or np.any(model["scale"] <= 0)
    ):
        raise ValueError("reconstructed normalization differs")
    return roles, ids, values, model


def _protocol(
    audio: Path, pack: Path, features: Path, metadata: Path, native_declaration: Path
) -> tuple[dict[str, Any], tuple[Any, ...]]:
    loaded = _load(pack, features, metadata, native_declaration)
    roles, _, _, _ = loaded
    attached = validate_playback_export(audio)
    native = {row["track_id"]: row for row in roles}
    roster = sorted(map(int, attached["tracks"]))
    if any(
        i not in native or attached["tracks"][str(i)]["artist_id"] != native[i]["artist_id"]
        for i in roster
    ):
        raise ValueError("attached native artist differs")
    receipt = shared._json(features / "projection-receipt.json")
    frozen = {
        "policy": POLICY,
        "audio_manifest": shared._binding(audio / "manifest.json"),
        "roster": roster,
        "components": {str(i): native[i]["component_id"] for i in roster},
        "model_sha256": shared._binding(pack / "model.npz")["sha256"],
        "roles_sha256": shared._binding(pack / "native-folds.jsonl.zst")["sha256"],
        "feature_receipt": shared._binding(features / "projection-receipt.json"),
        "features": {
            name: receipt["files"][name] for name in ("features.float32", "track_ids.uint32")
        },
        "baseline_evaluation": shared._binding(pack / "evaluation.json"),
        "native_declaration": shared._binding(native_declaration),
        "metadata_receipt": shared._binding(metadata / "corpus-receipt.json"),
        "implementation": {
            name: shared._binding(Path(module.__file__))
            for name, module in (
                ("ranking", shared),
                ("normalization", fma_related_tracks),
                ("native_custody", baseline),
                ("feature_custody", baseline.fma_features),
                ("split_custody", baseline.fma_split_audit),
            )
        },
    }
    frozen["implementation"]["producer"] = shared._binding(Path(__file__))
    return frozen, loaded


def freeze_protocol(
    audio: Path,
    pack: Path,
    features: Path,
    metadata: Path,
    native_declaration: Path,
    declaration: Path,
) -> dict[str, Any]:
    """Seal exact source, model, code and audio roster before computing neighbors."""
    frozen, _ = _protocol(audio, pack, features, metadata, native_declaration)
    shared._safe(declaration)
    declaration.parent.mkdir(parents=True, exist_ok=True)
    with declaration.open("xb") as stream:
        stream.write(canonical_json(frozen) + b"\n")
    return frozen


def _direct_replay(  # noqa: C901 -- independent abstention and component replay.
    roster: list[int],
    roles: dict[int, Any],
    features: dict[int, np.ndarray],
    model: dict[str, np.ndarray],
    rows: list[dict[str, Any]],
) -> None:
    """Independently subtract each standardized pair; never use dot-product distances."""
    vectors, reasons = {}, {}
    for identity in roster:
        role = roles[identity]
        if not role["artist_known"] or not role["component_id"]:
            reasons[identity] = "unresolved_artist"
        elif identity not in features:
            reasons[identity] = "missing_feature_row"
        else:
            active = model["active_columns"]
            vector = (
                features[identity].astype(np.float64)[active] - model["center"][active]
            ) / model["scale"][active]
            if not np.isfinite(vector).all() or np.any(
                np.abs(vector) > fma_related_tracks.MAX_OFFSET
            ):
                reasons[identity] = "outside_training_support"
            else:
                vectors[identity] = vector
    expected = []
    for identity in sorted(roster):
        chosen, seen = [], {roles[identity]["component_id"]}
        if identity in vectors:
            ordered = sorted(
                vectors,
                key=lambda other: (float(np.sum((vectors[identity] - vectors[other]) ** 2)), other),
            )
            for other in ordered:
                component = roles[other]["component_id"]
                if component not in seen:
                    seen.add(component)
                    chosen.append(other)
                    if len(chosen) == POLICY["neighbors"]:
                        break
        expected.append(
            {
                "track_id": identity,
                "neighbor_ids": chosen,
                "reason": reasons.get(identity)
                or (None if chosen else "no_cross_component_candidates"),
            }
        )
    if expected != rows:
        raise ValueError("independent squared-difference neighbor replay differs")


def derive(
    audio: Path,
    pack: Path,
    features: Path,
    metadata: Path,
    native_declaration: Path,
    declaration: Path,
) -> dict[str, Any]:
    """Infer under the frozen v3 policy and independently verify every selected edge."""
    frozen, loaded = _protocol(audio, pack, features, metadata, native_declaration)
    if frozen != shared._json(declaration):
        raise ValueError("reconstructed neighbor declaration differs")
    role_rows, ids, values, model = loaded
    roles = {row["track_id"]: row for row in role_rows}
    wanted = set(frozen["roster"])
    feature_rows = {
        int(identity): values[i] for i, identity in enumerate(ids) if int(identity) in wanted
    }
    rows = shared.rank_playable(frozen["roster"], roles, feature_rows, model)
    _direct_replay(frozen["roster"], roles, feature_rows, model, rows)
    return {
        "revision": REVISION,
        "audio_manifest_sha256": frozen["audio_manifest"]["sha256"],
        "rows": rows,
        "components": frozen["components"],
        **shared.CLAIMS,
        "pool": POLICY["pool"],
        "counts": shared._counts(rows),
        "provenance": {
            "declaration_sha256": shared._binding(declaration)["sha256"],
            "model_sha256": frozen["model_sha256"],
            "roles_sha256": frozen["roles_sha256"],
            "feature_receipt_sha256": frozen["feature_receipt"]["sha256"],
            "features_sha256": frozen["features"]["features.float32"]["sha256"],
            "track_ids_sha256": frozen["features"]["track_ids.uint32"]["sha256"],
        },
    }


def build(
    audio: Path,
    pack: Path,
    features: Path,
    metadata: Path,
    native_declaration: Path,
    declaration: Path,
    output: Path,
) -> dict[str, Any]:
    """Write an independently replayed closed pack below the unchanged one-MB limit."""
    shared._safe(output)
    if output.exists():
        raise FileExistsError("reconstructed neighbor output exists")
    manifest = derive(audio, pack, features, metadata, native_declaration, declaration)
    blobs = {
        "manifest.json": canonical_json(manifest) + b"\n",
        "declaration.json": declaration.read_bytes(),
    }
    receipt = {
        "revision": REVISION,
        "files": {
            name: {"sha256": hashlib.sha256(body).hexdigest(), "bytes": len(body)}
            for name, body in blobs.items()
        },
    }
    blobs["receipt.json"] = canonical_json(receipt) + b"\n"
    if sum(map(len, blobs.values())) > shared.MAX_OUTPUT_BYTES:
        raise ValueError("reconstructed neighbor output budget exceeded")
    output.mkdir(parents=True)
    for name, body in blobs.items():
        (output / name).write_bytes(body)
    return shared.validate_playable_neighbors(output)


def replay(
    audio: Path, pack: Path, features: Path, metadata: Path, native_declaration: Path, output: Path
) -> dict[str, Any]:
    """Revalidate custody and numerical ordering independently of norm/dot ranking."""
    actual = shared.validate_playable_neighbors(output)
    if (
        derive(audio, pack, features, metadata, native_declaration, output / "declaration.json")
        != actual
    ):
        raise ValueError("reconstructed playable replay differs")
    return actual
