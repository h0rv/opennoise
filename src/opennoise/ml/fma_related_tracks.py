"""Frozen-normalization FMA descriptor neighbors, never musical relevance judgments."""

from __future__ import annotations

import hashlib
import io
import json
import time
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np
import zstandard

from opennoise.common import canonical_json, sha256_hex
from opennoise.ml import fma_acoustic_baseline, fma_memberships, fma_training_memberships
from opennoise.ml.fma_inference import (
    EVALUATION_SHA256,
    FEATURE_RECEIPT_SHA256,
    MANIFEST_BYTES,
    MAX_INPUT_BYTES,
    PACK_FILES,
    _read_pinned,
)

REVISION = "fma-frozen-descriptor-neighbors-v1"
MAX_SECONDS = 120
MEMORY_BYTES = 1_000_000_000
MAX_OUTPUT_BYTES = 8_000_000
MAX_SHARD_BYTES = 200_000
MAX_CANDIDATES = 5000
NEIGHBORS = 6
TRACK_SPAN = 500
BATCH = 128
MAX_OFFSET = 12.0


def _pack(pack: Path) -> tuple[dict[str, Any], dict[str, bytes], list[dict[str, Any]]]:
    evaluation = json.loads(
        _read_pinned(pack / "evaluation.json", EVALUATION_SHA256, MANIFEST_BYTES)
    )
    bindings = evaluation["artifacts"]
    for module in (fma_acoustic_baseline, fma_memberships, fma_training_memberships):
        path = Path(module.__file__)
        _read_pinned(path, bindings[path.name]["sha256"], bindings[path.name]["bytes"])
    saved = {
        name: _read_pinned(pack / name, bindings[name]["sha256"], bindings[name]["bytes"])
        for name in PACK_FILES
    }
    seal = json.loads(saved["pre-diagnostic-seal.json"])
    if any(
        seal["artifacts"][name] != bindings[name]["sha256"]
        for name in ("model.npz", "thresholds.json")
    ):
        raise ValueError("frozen model/threshold seal differs")
    with zstandard.ZstdDecompressor().stream_reader(
        io.BytesIO(saved["native-roles.jsonl.zst"])
    ) as raw:
        roles = [json.loads(line) for line in io.TextIOWrapper(raw)]
    return evaluation, saved, roles


def candidate_roster(roles: list[dict[str, Any]]) -> list[int]:
    """Pick one inner-fit track per component from IDs only, before descriptors are read."""
    chosen = {}
    for row in roles:
        if row["role"] != "inner_fit" or not row["artist_known"]:
            continue
        identity, component = row["track_id"], row["component_id"]
        if not component:
            raise ValueError("inner-fit track lacks a resolved component")
        key = (hashlib.sha256(f"{REVISION}\0{identity}".encode()).digest(), identity)
        if component not in chosen or key < chosen[component]:
            chosen[component] = key
    if not chosen or len(chosen) > MAX_CANDIDATES:
        raise ValueError("candidate component count exceeds frozen bounds")
    return sorted(value[1] for value in chosen.values())


def _protocol(pack: Path) -> dict[str, Any]:
    _, _, roles = _pack(pack)
    return {
        "revision": REVISION,
        "evaluation_sha256": EVALUATION_SHA256,
        "feature_receipt_sha256": FEATURE_RECEIPT_SHA256,
        "query_ids": sorted(row["track_id"] for row in roles),
        "candidate_ids": candidate_roster(roles),
        "candidate_policy": (
            "one seeded-hash minimum native ID per inner-fit component before reading "
            "descriptors; unsupported candidates dropped without replacement"
        ),
        "normalization": (
            "existing sealed inner-fit model center, scale and active columns; no fitting"
        ),
        "ranking": (
            "float64 squared Euclidean via norm/dot identity, clamped nonnegative; "
            "exact computed-distance ties by native ID"
        ),
        "isolation": "exclude query artist/album/full-native-feature-duplicate component",
        "max_standardized_offset": MAX_OFFSET,
        "neighbors": NEIGHBORS,
        "max_candidates": MAX_CANDIDATES,
        "max_seconds": MAX_SECONDS,
        "memory_bytes": MEMORY_BYTES,
        "max_output_bytes": MAX_OUTPUT_BYTES,
        "max_shard_bytes": MAX_SHARD_BYTES,
        "labels_used": False,
        "musical_relevance_established": False,
        "evaluation_status": (
            "product inference only; outer validation/test previously inspected, "
            "no new quality evaluation"
        ),
    }


def freeze_protocol(pack: Path, output: Path) -> dict[str, Any]:
    """Save a new immutable roster and recipe without reading descriptor files."""
    protocol = _protocol(pack)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("xb") as stream:
        stream.write(canonical_json(protocol) + b"\n")
    return protocol


def normalize(values: np.ndarray, model: dict[str, np.ndarray]) -> tuple[np.ndarray, np.ndarray]:
    """Apply existing training normalization and its unchanged finite/range support gate."""
    active = model["active_columns"]
    normalized = (
        np.asarray(values[:, active], dtype=np.float64) - model["center"][active]
    ) / model["scale"][active]
    supported = np.isfinite(normalized).all(axis=1) & (np.abs(normalized) <= MAX_OFFSET).all(axis=1)
    return normalized, supported


def nearest_batch(
    queries: np.ndarray,
    components: np.ndarray,
    candidates: np.ndarray,
    candidate_ids: np.ndarray,
    candidate_components: np.ndarray,
) -> list[list[int]]:
    """Rank a bounded batch with exact computed-distance ties and whole-component isolation."""
    if len(queries) > BATCH or len(candidates) > MAX_CANDIDATES:
        raise ValueError("distance matrix exceeds frozen block bounds")
    distances = np.maximum(
        np.sum(queries * queries, axis=1)[:, None]
        + np.sum(candidates * candidates, axis=1)[None, :]
        - 2 * (queries @ candidates.T),
        0,
    )
    distances[components[:, None] == candidate_components[None, :]] = np.inf
    output = []
    for row in distances:
        eligible = np.flatnonzero(np.isfinite(row))
        if len(eligible) > NEIGHBORS:
            cutoff = np.partition(row[eligible], NEIGHBORS - 1)[NEIGHBORS - 1]
            eligible = eligible[row[eligible] <= cutoff]
        order = np.lexsort((candidate_ids[eligible], row[eligible]))[:NEIGHBORS]
        output.append([int(identity) for identity in candidate_ids[eligible[order]]])
    return output


def build_related_tracks(  # noqa: C901, PLR0912 - single frozen input/output boundary.
    pack: Path, features: Path, declaration: Path, output: Path
) -> dict[str, Any]:
    """Produce complete native-query shards without training, labels or evaluation selection."""
    started = time.monotonic()
    if output.exists():
        raise FileExistsError("related-track output must be new")
    protocol_bytes = declaration.read_bytes()
    protocol = json.loads(protocol_bytes)
    if protocol != _protocol(pack):
        raise ValueError("frozen descriptor retrieval protocol differs")
    evaluation, saved, roles = _pack(pack)
    receipt_bytes = _read_pinned(
        features / "projection-receipt.json", FEATURE_RECEIPT_SHA256, MANIFEST_BYTES
    )
    receipt = json.loads(receipt_bytes)
    if (
        sum(receipt["files"][name]["bytes"] for name in ("features.float32", "track_ids.uint32"))
        + sum(map(len, saved.values()))
        > MAX_INPUT_BYTES
    ):
        raise ValueError("pinned retrieval input byte budget exceeded")
    data = {
        name: _read_pinned(
            features / name, receipt["files"][name]["sha256"], receipt["files"][name]["bytes"]
        )
        for name in ("features.float32", "track_ids.uint32")
    }
    identities = np.frombuffer(data["track_ids.uint32"], dtype="<u4")
    values = np.frombuffer(data["features.float32"], dtype="<f4").reshape(
        receipt["rows"], len(receipt["columns"])
    )
    with np.load(io.BytesIO(saved["model.npz"]), allow_pickle=False) as loaded:
        model = {name: loaded[name] for name in ("center", "scale", "active_columns")}
    normalized, supported = normalize(values, model)
    positions = {int(identity): index for index, identity in enumerate(identities)}
    native = {row["track_id"]: row for row in roles}
    candidate_ids = np.array(
        [
            identity
            for identity in protocol["candidate_ids"]
            if identity in positions and supported[positions[identity]]
        ],
        dtype=np.uint32,
    )
    candidate_positions = [positions[int(identity)] for identity in candidate_ids]
    candidate_values = normalized[candidate_positions]
    candidate_components = np.array(
        [native[int(identity)]["component_id"] for identity in candidate_ids], dtype=np.int64
    )
    rows: dict[int, list[Any]] = {}
    eligible = []
    for identity in protocol["query_ids"]:
        role = native[identity]
        reason = (
            "unresolved_artist"
            if not role["artist_known"] or not role["component_id"]
            else "missing_feature_row"
            if identity not in positions
            else "outside_training_support"
            if not supported[positions[identity]]
            else None
        )
        rows[identity] = [identity, [], reason]
        if reason is None:
            eligible.append(identity)
    for offset in range(0, len(eligible), BATCH):
        if time.monotonic() - started > MAX_SECONDS:
            raise TimeoutError("descriptor retrieval wall-time budget exceeded")
        batch = eligible[offset : offset + BATCH]
        neighbors = nearest_batch(
            normalized[[positions[identity] for identity in batch]],
            np.array([native[identity]["component_id"] for identity in batch]),
            candidate_values,
            candidate_ids,
            candidate_components,
        )
        for identity, selected in zip(batch, neighbors, strict=True):
            rows[identity][1] = selected
            if not selected:
                rows[identity][2] = "no_cross_component_candidates"
    shards: dict[int, list[Any]] = {}
    for identity, row in rows.items():
        shards.setdefault(identity // TRACK_SPAN, []).append(row)
    payloads = {
        f"{shard}.json": canonical_json({"rows": records}) + b"\n"
        for shard, records in shards.items()
    }
    manifest = {
        "revision": REVISION,
        "track_id_span": TRACK_SPAN,
        "neighbor_count": NEIGHBORS,
        "counts": {
            "queries": len(rows),
            "supported_queries": sum(row[2] is None for row in rows.values()),
            "declared_candidates": len(protocol["candidate_ids"]),
            "supported_candidates": len(candidate_ids),
            "candidate_components": len(set(candidate_components.tolist())),
            "abstentions": dict(Counter(row[2] for row in rows.values() if row[2])),
        },
        "method": protocol["ranking"],
        "candidate_policy": protocol["candidate_policy"],
        "labels_used": False,
        "musical_relevance_established": False,
        "provenance": {
            "evaluation_sha256": EVALUATION_SHA256,
            "model_sha256": evaluation["artifacts"]["model.npz"]["sha256"],
            "feature_receipt_sha256": FEATURE_RECEIPT_SHA256,
            "declaration_sha256": sha256_hex(protocol_bytes),
            "implementation_sha256": sha256_hex(Path(__file__).read_bytes()),
            "license": receipt["license"],
            "attribution": receipt["attribution"],
        },
        "files": {
            name: {"sha256": sha256_hex(payload), "bytes": len(payload)}
            for name, payload in payloads.items()
        },
    }
    payloads["manifest.json"] = canonical_json(manifest) + b"\n"
    if (
        any(len(payload) > MAX_SHARD_BYTES for payload in payloads.values())
        or sum(map(len, payloads.values())) > MAX_OUTPUT_BYTES
    ):
        raise ValueError("related-track export byte budget exceeded")
    if time.monotonic() - started > MAX_SECONDS:
        raise TimeoutError("descriptor retrieval wall-time budget exceeded")
    output.mkdir(parents=True)
    for name, payload in payloads.items():
        (output / name).write_bytes(payload)
    return manifest
