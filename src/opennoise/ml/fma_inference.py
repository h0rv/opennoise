"""Bounded inference from the reviewed FMA training-only model; no fitting or source labels."""

from __future__ import annotations

import hashlib
import io
import json
import time
from dataclasses import fields
from pathlib import Path
from typing import Any

import numpy as np
import zstandard

from opennoise.ml import fma_acoustic_baseline, fma_memberships, fma_training_memberships
from opennoise.ml.fma_acoustic_baseline import PositiveGaussian, score_positive_gaussian
from opennoise.ml.fma_training_memberships import training_suggest

REVISION = "fma-frozen-track-inference-v1"
EVALUATION_SHA256 = "67228714920a686a2893e778c01406c8f5ee01344d389b1e4a00e414a32b8781"
FEATURE_RECEIPT_SHA256 = "8462edb5aab5642c92b3b5734fc01f09c3bf919fe22d5b5e3b87440bc0720eab"
MAX_QUERIES = 100
MAX_TRACK_ID = 2**32 - 1
MAX_INPUT_BYTES = 25_000_000
MAX_OUTPUT_BYTES = 2_000_000
MAX_SECONDS = 30
MEMORY_BYTES = 1_000_000_000
MANIFEST_BYTES = 1_000_000
PACK_FILES = (
    "model.npz",
    "thresholds.json",
    "native-roles.jsonl.zst",
    "declaration.json",
    "pre-diagnostic-seal.json",
)
FEATURE_FILES = ("features.float32", "track_ids.uint32")


def _read_pinned(path: Path, digest: str, limit: int) -> bytes:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > limit:
        raise ValueError(f"missing, nonregular, symlink or oversized input: {path.name}")
    with path.open("rb") as stream:
        data = stream.read(limit + 1)
    if len(data) > limit or hashlib.sha256(data).hexdigest() != digest:
        raise ValueError(f"frozen input hash/size differs: {path.name}")
    return data


def encode_jsonl(records: list[dict[str, Any]]) -> bytes:
    """Serialize deterministically and reject the entire export before writing if too large."""
    data = b"".join(
        (json.dumps(row, sort_keys=True, allow_nan=False) + "\n").encode() for row in records
    )
    if len(data) > MAX_OUTPUT_BYTES:
        raise ValueError("inference output byte budget exceeded")
    return data


def infer_tracks(pack: Path, features: Path, track_ids: list[int]) -> list[dict[str, Any]]:  # noqa: C901, PLR0915 - one pinned inference boundary.
    """Load a portable frozen pack; preserve explicit query order/duplicates and abstentions.

    No target labels, rank exports or native source archives are needed. The API
    checks a cooperative wall deadline; the CLI additionally enforces OS limits.
    """
    started = time.monotonic()
    if not 1 <= len(track_ids) <= MAX_QUERIES or any(
        type(i) is not int or not 1 <= i <= MAX_TRACK_ID for i in track_ids
    ):
        raise ValueError(f"request requires 1..{MAX_QUERIES} positive uint32 native track IDs")
    evaluation_bytes = _read_pinned(pack / "evaluation.json", EVALUATION_SHA256, MANIFEST_BYTES)
    receipt_bytes = _read_pinned(
        features / "projection-receipt.json", FEATURE_RECEIPT_SHA256, MANIFEST_BYTES
    )
    evaluation = json.loads(evaluation_bytes)
    receipt = json.loads(receipt_bytes)
    bindings = evaluation["artifacts"]
    total = len(evaluation_bytes) + len(receipt_bytes)
    total += sum(bindings[name]["bytes"] for name in PACK_FILES)
    total += sum(receipt["files"][name]["bytes"] for name in FEATURE_FILES)
    total += sum(
        bindings[Path(module.__file__).name]["bytes"]
        for module in (fma_acoustic_baseline, fma_memberships, fma_training_memberships)
    )
    if total > MAX_INPUT_BYTES:
        raise ValueError("inference input byte budget exceeded")
    # Preserve frozen scoring semantics; snapshots are checked, never executed.
    for module in (fma_acoustic_baseline, fma_memberships, fma_training_memberships):
        path = Path(module.__file__)
        _read_pinned(path, bindings[path.name]["sha256"], bindings[path.name]["bytes"])
    saved = {
        name: _read_pinned(pack / name, bindings[name]["sha256"], bindings[name]["bytes"])
        for name in PACK_FILES
    }
    projection = {
        name: _read_pinned(
            features / name, receipt["files"][name]["sha256"], receipt["files"][name]["bytes"]
        )
        for name in FEATURE_FILES
    }
    seal = json.loads(saved["pre-diagnostic-seal.json"])
    for name in ("model.npz", "thresholds.json"):
        if seal["artifacts"][name] != bindings[name]["sha256"]:
            raise ValueError("saved model/threshold seal differs")
    with np.load(io.BytesIO(saved["model.npz"]), allow_pickle=False) as loaded:
        model = PositiveGaussian(
            **{field.name: loaded[field.name] for field in fields(PositiveGaussian)}
        )
        labels = loaded["labels"].tolist()
    thresholds = {
        int(label): value for label, value in json.loads(saved["thresholds.json"]).items()
    }
    ids = np.frombuffer(projection["track_ids.uint32"], dtype="<u4")
    values = np.frombuffer(projection["features.float32"], dtype="<f4").reshape(
        receipt["rows"], len(receipt["columns"])
    )
    requested = set(track_ids)
    native = {}
    with (
        zstandard.ZstdDecompressor().stream_reader(
            io.BytesIO(saved["native-roles.jsonl.zst"])
        ) as raw,
        io.TextIOWrapper(raw, encoding="utf-8") as text,
    ):
        for line in text:
            row = json.loads(line)
            if row["track_id"] in requested:
                native[row["track_id"]] = row
    positions = {int(value): i for i, value in enumerate(ids) if int(value) in requested}
    query_features = np.full((len(track_ids), values.shape[1]), np.nan, dtype=np.float32)
    for i, identity in enumerate(track_ids):
        if identity in positions and identity in native and native[identity]["artist_known"]:
            query_features[i] = values[positions[identity]]
    if time.monotonic() - started > MAX_SECONDS:
        raise TimeoutError("inference wall-time budget exceeded")
    scores, reasons = score_positive_gaussian(model, query_features)
    ordered = np.argsort(-scores, axis=1, kind="stable")
    provenance = {
        "inference_revision": REVISION,
        "evaluation_sha256": EVALUATION_SHA256,
        "model_sha256": bindings["model.npz"]["sha256"],
        "thresholds_sha256": bindings["thresholds.json"]["sha256"],
        "native_roles_sha256": bindings["native-roles.jsonl.zst"]["sha256"],
        "feature_receipt_sha256": FEATURE_RECEIPT_SHA256,
        "license": receipt["license"],
        "attribution": receipt["attribution"],
        "target": "native_track_source_recovery",
        "query_source_labels_consumed": False,
        "musical_calibration_established": False,
        "fitted_or_recalibrated": False,
    }
    outputs = []
    for i, identity in enumerate(track_ids):
        row = native.get(identity)
        reason = (
            "unknown_native_track_id"
            if row is None
            else "unresolved_artist"
            if not row["artist_known"]
            else "missing_feature_row"
            if identity not in positions
            else reasons[i]
        )
        ranking = (
            [labels[int(index)] for index in ordered[i] if model.active_labels[index]]
            if reason is None
            else []
        )
        output = training_suggest(
            {"track_id": identity, "ranked_genre_ids": ranking, "reason": reason}, thresholds
        )
        outputs.append(
            {**output, "provenance": {**provenance, "original_role": row["role"] if row else None}}
        )
    encode_jsonl(outputs)
    if time.monotonic() - started > MAX_SECONDS:
        raise TimeoutError("inference wall-time budget exceeded")
    return outputs
