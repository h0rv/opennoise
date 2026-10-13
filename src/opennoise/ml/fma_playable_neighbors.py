"""Bounded attached-clip inference; no refitting or musical quality evaluation."""

from __future__ import annotations

import hashlib
import io
import json
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np

from opennoise.common import canonical_json, sha256_file
from opennoise.deployment.fma_playback import validate_playback_export
from opennoise.ml import fma_related_tracks
from opennoise.ml.fma_inference import FEATURE_RECEIPT_SHA256, MANIFEST_BYTES, _read_pinned
from opennoise.ml.fma_sonic_map import FEATURE_SHA, ID_SHA

LEGACY_REVISION = "fma-playable-descriptor-neighbors-v1"
REVISION = "fma-playable-component-neighbors-v2"
MAX_OUTPUT_BYTES = 1_000_000
MAX_CLIPS = 64
LIMITS = {"seconds": 120, "memory_bytes": 1_000_000_000, "output_bytes": MAX_OUTPUT_BYTES}
REASONS = {
    "unresolved_artist",
    "missing_feature_row",
    "outside_training_support",
    "no_cross_component_candidates",
}
CLAIMS = {
    "labels_used": False,
    "fitted": False,
    "musical_relevance_established": False,
    "evaluation_status": "product inference only; no new quality evaluation",
}
LEGACY_POLICY: dict[str, Any] = {
    "revision": LEGACY_REVISION,
    "limits": LIMITS,
    "neighbors": 6,
    "max_clips": MAX_CLIPS,
    "pool": "only exact attached audio roster; supported rows only; no replacements",
    "normalization": "unchanged frozen inner-fit model; finite absolute standardized offset <=12",
    "ranking": "float64 squared Euclidean norm/dot identity; exact computed ties by native ID",
    "isolation": "exclude whole native artist/album/exact-feature component",
    **CLAIMS,
}
POLICY: dict[str, Any] = {
    **LEGACY_POLICY,
    "revision": REVISION,
    "ranking": (
        "float64 squared Euclidean norm/dot identity; exact computed ties by native ID; "
        "first candidate per native component, continuing to six distinct components"
    ),
}


def _safe(path: Path) -> None:
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError("symlinked playable-neighbor path")


def _binding(path: Path) -> dict[str, Any]:
    _safe(path)
    digest, size = sha256_file(path)
    return {"sha256": digest, "bytes": size}


def _json(path: Path) -> dict[str, Any]:
    _safe(path)
    if not path.is_file() or path.stat().st_size > MAX_OUTPUT_BYTES:
        raise ValueError("playable-neighbor control missing or oversized")
    return json.loads(path.read_bytes())


def _protocol(audio: Path, pack: Path, features: Path) -> dict[str, Any]:
    attached = validate_playback_export(audio)
    _, saved, roles = fma_related_tracks._pack(pack)  # noqa: SLF001 -- reuse unchanged frozen pack validator.
    native = {row["track_id"]: row for row in roles}
    if len(native) != len(roles):
        raise ValueError("duplicate frozen role identity")
    roster = sorted(int(key) for key in attached["tracks"])
    for identity in roster:
        row = native.get(identity)
        if row is None or row["artist_id"] != attached["tracks"][str(identity)]["artist_id"]:
            raise ValueError("attached track artist differs from frozen native role")
    receipt = json.loads(
        _read_pinned(features / "projection-receipt.json", FEATURE_RECEIPT_SHA256, MANIFEST_BYTES)
    )
    if (
        receipt["license"] != "CC-BY-4.0"
        or receipt["audio_downloaded"] is not False
        or receipt["echo_nest_consumed"] is not False
    ):
        raise ValueError("descriptor provenance outside approved scope")
    pins = {}
    for name, digest in (("features.float32", FEATURE_SHA), ("track_ids.uint32", ID_SHA)):
        binding = _binding(features / name)
        if binding != receipt["files"][name] or binding["sha256"] != digest:
            raise ValueError("frozen descriptor bytes differ")
        pins[name] = binding
    return {
        "policy": POLICY,
        "audio_manifest": _binding(audio / "manifest.json"),
        "roster": roster,
        "components": {str(i): native[i]["component_id"] for i in roster},
        "model_sha256": hashlib.sha256(saved["model.npz"]).hexdigest(),
        "roles_sha256": hashlib.sha256(saved["native-roles.jsonl.zst"]).hexdigest(),
        "feature_receipt": _binding(features / "projection-receipt.json"),
        "features": pins,
        "implementation": {
            "producer": _binding(Path(__file__)),
            "frozen_ranking": _binding(Path(fma_related_tracks.__file__)),
        },
    }


def freeze_protocol(audio: Path, pack: Path, features: Path, declaration: Path) -> dict[str, Any]:
    """Freeze exact attached IDs, custody and implementation before computing any distances."""
    frozen = _protocol(audio, pack, features)
    _safe(declaration)
    declaration.parent.mkdir(parents=True, exist_ok=True)
    with declaration.open("xb") as stream:
        stream.write(canonical_json(frozen) + b"\n")
    return frozen


def _component_neighbors(
    ids: np.ndarray, components: np.ndarray, values: np.ndarray
) -> list[list[int]]:
    """Keep each component's nearest clip, in the unchanged distance/native-ID order."""
    distances = np.maximum(
        np.sum(values * values, axis=1)[:, None]
        + np.sum(values * values, axis=1)[None, :]
        - 2 * (values @ values.T),
        0,
    )
    neighbors = []
    for index, row in enumerate(distances):
        seen = {components[index]}
        selected = []
        for candidate in np.lexsort((ids, row)):
            component = components[candidate]
            if component in seen:
                continue
            seen.add(component)
            selected.append(int(ids[candidate]))
            if len(selected) == POLICY["neighbors"]:
                break
        neighbors.append(selected)
    return neighbors


def rank_playable(
    roster: list[int],
    roles: dict[int, dict[str, Any]],
    feature_rows: dict[int, np.ndarray],
    model: dict[str, np.ndarray],
) -> list[dict[str, Any]]:
    """Rank only supported attached clips, retaining every query and explicit abstention."""
    if not roster or len(roster) > MAX_CLIPS or len(set(roster)) != len(roster):
        raise ValueError("attached roster exceeds unique clip bound")
    supported_ids, standardized = [], []
    reasons = {}
    for identity in sorted(roster):
        role = roles.get(identity)
        if role is None or not role["artist_known"] or not role["component_id"]:
            reasons[identity] = "unresolved_artist"
        elif identity not in feature_rows:
            reasons[identity] = "missing_feature_row"
        else:
            values, supported = fma_related_tracks.normalize(feature_rows[identity][None, :], model)
            if not supported[0]:
                reasons[identity] = "outside_training_support"
            else:
                supported_ids.append(identity)
                standardized.append(values[0])
    ranked = {}
    if supported_ids:
        ids = np.asarray(supported_ids, dtype=np.uint32)
        components = np.asarray([roles[i]["component_id"] for i in supported_ids], dtype=np.int64)
        values = np.asarray(standardized)
        neighbors = _component_neighbors(ids, components, values)
        ranked = dict(zip(supported_ids, neighbors, strict=True))
    return [
        {
            "track_id": i,
            "neighbor_ids": ranked.get(i, []),
            "reason": reasons.get(i)
            or (None if ranked.get(i) else "no_cross_component_candidates"),
        }
        for i in sorted(roster)
    ]


def derive(audio: Path, pack: Path, features: Path, declaration: Path) -> dict[str, Any]:
    """Replay custody before applying the unchanged fitted model to the separate audio pool."""
    frozen = _json(declaration)
    if frozen != _protocol(audio, pack, features):
        raise ValueError("playable-neighbor frozen declaration differs")
    _, saved, role_rows = fma_related_tracks._pack(pack)  # noqa: SLF001
    roles = {row["track_id"]: row for row in role_rows}
    receipt = json.loads(
        _read_pinned(features / "projection-receipt.json", FEATURE_RECEIPT_SHA256, MANIFEST_BYTES)
    )
    data = {
        name: _read_pinned(features / name, binding["sha256"], binding["bytes"])
        for name, binding in frozen["features"].items()
    }
    ids = np.frombuffer(data["track_ids.uint32"], dtype="<u4")
    values = np.frombuffer(data["features.float32"], dtype="<f4").reshape(
        receipt["rows"], len(receipt["columns"])
    )
    if len(ids) != len(values) or len(set(map(int, ids))) != len(ids):
        raise ValueError("duplicate or misaligned feature identities")
    wanted = set(frozen["roster"])
    feature_rows = {
        int(identity): values[index]
        for index, identity in enumerate(ids)
        if int(identity) in wanted
    }
    with np.load(io.BytesIO(saved["model.npz"]), allow_pickle=False) as archive:
        model = {key: archive[key] for key in ("center", "scale", "active_columns")}
    rows = rank_playable(frozen["roster"], roles, feature_rows, model)
    return {
        "revision": REVISION,
        "audio_manifest_sha256": frozen["audio_manifest"]["sha256"],
        "rows": rows,
        "components": frozen["components"],
        **CLAIMS,
        "pool": POLICY["pool"],
        "counts": _counts(rows),
        "provenance": {
            "declaration_sha256": sha256_file(declaration)[0],
            "model_sha256": frozen["model_sha256"],
            "roles_sha256": frozen["roles_sha256"],
            "feature_receipt_sha256": frozen["feature_receipt"]["sha256"],
            "features_sha256": FEATURE_SHA,
            "track_ids_sha256": ID_SHA,
        },
    }


def _counts(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "queries": len(rows),
        "supported_queries": sum(row["reason"] is None for row in rows),
        "directed_edges": sum(len(row["neighbor_ids"]) for row in rows),
        "abstentions": dict(
            sorted(Counter(row["reason"] for row in rows if row["reason"]).items())
        ),
    }


def build(
    audio: Path, pack: Path, features: Path, declaration: Path, output: Path
) -> dict[str, Any]:
    """Write a small closed pack after complete validation and bounded inference."""
    _safe(output)
    if output.exists():
        raise FileExistsError("playable-neighbor output exists")
    manifest = derive(audio, pack, features, declaration)
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
    if sum(map(len, blobs.values())) > MAX_OUTPUT_BYTES:
        raise ValueError("playable-neighbor output budget exceeded")
    output.mkdir(parents=True)
    for name, body in blobs.items():
        (output / name).write_bytes(body)
    return validate_playable_neighbors(output)


def validate_playable_neighbors(  # noqa: C901, PLR0912 -- closed pool/receipt validation.
    output: Path, audio_manifest_sha256: str | None = None
) -> dict[str, Any]:
    """Validate closed receipts, pool scope, component exclusion and ordered query coverage."""
    _safe(output)
    receipt = _json(output / "receipt.json")
    if (
        receipt["revision"] not in (LEGACY_REVISION, REVISION)
        or set(receipt["files"]) != {"manifest.json", "declaration.json"}
        or {p.name for p in output.iterdir()}
        != {"manifest.json", "declaration.json", "receipt.json"}
        or sum(p.stat().st_size for p in output.iterdir()) > MAX_OUTPUT_BYTES
    ):
        raise ValueError("playable-neighbor inventory or byte budget differs")
    for name, binding in receipt["files"].items():
        if _binding(output / name) != binding:
            raise ValueError("playable-neighbor artifact hash differs")
    manifest, frozen = _json(output / "manifest.json"), _json(output / "declaration.json")
    policy = LEGACY_POLICY if receipt["revision"] == LEGACY_REVISION else POLICY
    if (
        frozen["policy"] != policy
        or manifest["revision"] != receipt["revision"]
        or manifest["pool"] != policy["pool"]
        or manifest["components"] != frozen["components"]
        or manifest["audio_manifest_sha256"] != frozen["audio_manifest"]["sha256"]
        or (
            audio_manifest_sha256 is not None
            and manifest["audio_manifest_sha256"] != audio_manifest_sha256
        )
        or any(
            manifest.get(key) != value or type(manifest.get(key)) is not type(value)
            for key, value in CLAIMS.items()
        )
    ):
        raise ValueError("playable-neighbor source pool or role differs")
    expected_provenance = {
        "declaration_sha256": receipt["files"]["declaration.json"]["sha256"],
        "model_sha256": frozen["model_sha256"],
        "roles_sha256": frozen["roles_sha256"],
        "feature_receipt_sha256": frozen["feature_receipt"]["sha256"],
        "features_sha256": FEATURE_SHA,
        "track_ids_sha256": ID_SHA,
    }
    if manifest["provenance"] != expected_provenance:
        raise ValueError("playable-neighbor provenance differs")
    roster = frozen["roster"]
    if (
        not 0 < len(roster) <= MAX_CLIPS
        or any(type(i) is not int or i <= 0 for i in roster)
        or roster != sorted(set(roster))
        or [row["track_id"] for row in manifest["rows"]] != roster
        or set(manifest["components"]) != set(map(str, roster))
    ):
        raise ValueError("playable-neighbor query coverage differs")
    rows = {row["track_id"]: row for row in manifest["rows"]}
    for identity, row in rows.items():
        neighbors, reason = row["neighbor_ids"], row["reason"]
        component = manifest["components"][str(identity)]
        if (
            reason not in REASONS | {None}
            or (reason is not None and neighbors)
            or (reason is None and (not neighbors or type(component) is not int or component <= 0))
            or len(neighbors) > POLICY["neighbors"]
            or len(set(neighbors)) != len(neighbors)
            or any(type(i) is not int or i not in rows or i == identity for i in neighbors)
        ):
            raise ValueError("playable-neighbor ranking shape or abstention differs")
        for neighbor in neighbors:
            if (
                rows[neighbor]["reason"] is not None
                or manifest["components"][str(neighbor)] == component
            ):
                raise ValueError("playable neighbor violates support or whole-component isolation")
        if manifest["revision"] == REVISION and reason is None:
            selected = {manifest["components"][str(i)] for i in neighbors}
            eligible = {
                manifest["components"][str(i)]
                for i, candidate in rows.items()
                if candidate["reason"] is None and manifest["components"][str(i)] != component
            }
            if len(selected) != len(neighbors) or len(neighbors) != min(
                POLICY["neighbors"], len(eligible)
            ):
                raise ValueError("playable-neighbor distinct component coverage differs")
    if manifest["counts"] != _counts(manifest["rows"]):
        raise ValueError("playable-neighbor counts differ")
    return manifest


def replay(audio: Path, pack: Path, features: Path, output: Path) -> dict[str, Any]:
    """Recompute every row from pinned local inputs; no fitting or musical quality evaluation."""
    actual = validate_playable_neighbors(output)
    if derive(audio, pack, features, output / "declaration.json") != actual:
        raise ValueError("playable-neighbor numerical replay differs")
    return actual
