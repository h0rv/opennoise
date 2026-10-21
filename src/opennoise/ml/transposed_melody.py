"""Opt-in bounded pitch-offset alignment; preserve the absolute-pitch source loader."""

from __future__ import annotations

import hashlib
import platform
from pathlib import Path
from typing import Any

import numpy as np

from opennoise.ml import medley_melody as native

REVISION = "medley-bounded-transposition-search-v1"
DECLARATION_SHA256 = "f3c652f69c03f05f88b178eb08daccce345536c05089929ec08e21edbc7da367"
MIN_OFFSET = -12.0
MAX_OFFSET = 12.0
BASELINE_FILES = {
    "src/opennoise/ml/medley_melody.py": (
        "22b5fb0e53bbe07744450c8ecd9aebc6a3d0c85b8b2978e863e50b9bb040e98a"
    ),
    "scripts/query_melody_contour.py": (
        "5ddd93d8a3a20a2da169763d72a08fc13a7b42708e2fee1007db7cd7bb803405"
    ),
}


def runtime() -> dict[str, object]:
    """Bind the separate scorer and require the unchanged source-loading implementation."""
    root = Path(__file__).resolve().parents[3]
    files = (
        *BASELINE_FILES,
        "src/opennoise/ml/transposed_melody.py",
        "scripts/query_transposed_melody_contour.py",
    )
    pins = {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in files}
    if any(pins[name] != pin for name, pin in BASELINE_FILES.items()):
        raise ValueError("absolute-pitch loader/CLI differs from the frozen implementation")
    return {"python": platform.python_version(), "numpy": np.__version__, "code_sha256": pins}


def _best(source: native.Contour, query: native.Contour) -> dict[str, Any] | None:
    n, m = len(source.times), len(query.times)
    if n < m:
        return None
    pitch = np.lib.stride_tricks.sliding_window_view(source.midi, m)
    voiced = np.lib.stride_tricks.sliding_window_view(source.voiced, m)
    best: dict[str, Any] | None = None
    count = int(query.voiced.sum())
    for start in range(0, len(pitch), native.CHUNK):
        candidate = voiced[start : start + native.CHUNK]
        joint = candidate & query.voiced
        overlap = joint.sum(axis=1)
        eligible = overlap * 4 >= count * 3
        if not eligible.any():
            continue
        differences = pitch[start : start + native.CHUNK] - query.midi
        totals = np.sum(np.where(joint, differences, 0.0), axis=1, dtype=np.float64)
        offsets = np.divide(totals, overlap, out=np.zeros_like(totals), where=overlap > 0)
        offsets = np.clip(offsets, MIN_OFFSET, MAX_OFFSET)
        mismatch = candidate != query.voiced
        costs = np.where(
            joint, np.square(differences - offsets[:, None]), np.where(mismatch, 144.0, 0.0)
        )
        scores = np.asarray(np.sum(costs, axis=1, dtype=np.float64) / m, dtype=np.float64)
        if not np.isfinite(offsets).all() or not np.isfinite(scores).all():
            raise ValueError("nonfinite bounded pitch-offset distance")
        scaled = np.rint(scores / native.TICK)
        if not np.isfinite(scaled).all() or (scaled < 0).any() or (scaled >= 2**63).any():
            raise ValueError("bounded pitch-offset quantization is out of range")
        ticks = scaled.astype(np.int64)
        positions = np.flatnonzero(eligible)
        local = int(positions[np.argmin(ticks[positions])])
        tick = int(ticks[local])
        if best is None or tick < best["distance_ticks"]:
            frame = start + local
            best = {
                "start_frame": frame,
                "end_frame_exclusive": frame + m,
                "first_sample_time_seconds": float(source.times[frame]),
                "last_sample_time_seconds": float(source.times[frame + m - 1]),
                "distance_ticks": tick,
                "mean_squared_midi_distance": float(scores[local]),
                "source_minus_query_semitones": float(offsets[local]),
                "joint_voiced_frames": int(overlap[local]),
                "voicing_mismatch_frames": int(mismatch[local].sum()),
            }
    return best


def search_contour(
    source: native.Source, request: dict[str, Any], *, limit: int = native.MAX_TRACKS
) -> dict[str, Any]:
    """Align new caller contours with a joint-voiced mean offset bounded to one octave."""
    code = runtime()
    if type(limit) is not int or not 1 <= limit <= native.MAX_TRACKS:
        raise ValueError("result limit must be an integer in 1..24")
    if not isinstance(request, dict) or set(request) != {"times_seconds", "f0_hz"}:
        raise ValueError("query schema requires only times_seconds and f0_hz")
    query = native.contour(request["times_seconds"], request["f0_hz"], query=True)
    count = int(query.voiced.sum())
    supported = count * 4 >= len(query.times)
    results, outcomes = [], []
    for row in source.nominations:
        identity, status = row["native_track_id"], row["status"]
        reason = "source_unavailable"
        if status == "usable":
            item = source.contours[identity]
            reason = "query_insufficient_voicing" if not supported else "shorter_than_query"
            if supported and len(item.times) >= len(query.times):
                match = _best(item, query)
                reason = "insufficient_joint_voicing" if match is None else "matched"
                if match is not None:
                    results.append(
                        {
                            "native_track_id": identity,
                            **match,
                            "source_annotation_sha256": row["sha256"],
                        }
                    )
        outcomes.append({"native_track_id": identity, "source_status": status, "status": reason})
    results.sort(
        key=lambda row: (row["distance_ticks"], row["native_track_id"], row["start_frame"])
    )
    semantic = {"times_seconds": query.times.tolist(), "f0_hz": query.f0.tolist()}
    return {
        "revision": REVISION,
        "metric_declaration_sha256": DECLARATION_SHA256,
        "runtime": code,
        "source_manifest_sha256": source.pin,
        "source_inputs": source.inputs,
        "rights": source.pilot["rights"],
        "source_repository": source.pilot["source_repository"],
        "source_commit": source.pilot["source_commit"],
        "scope": "local_native_annotation_bounded_pitch_offset_alignment_only",
        "metric": {
            "offset_sign": "source_minus_query_semitones",
            "offset_min_semitones": MIN_OFFSET,
            "offset_max_semitones": MAX_OFFSET,
            "offset_rule": "joint_voiced_float64_mean_then_clip",
            "tick_semitone_squared": native.TICK,
        },
        "status": "completed" if supported else "query_insufficient_voicing",
        "query": {
            "frames": len(query.times),
            "voiced_frames": count,
            "origin_seconds": float(query.times[0]),
            "sha256": hashlib.sha256(native.encoded(semantic)).hexdigest(),
        },
        "limit": limit,
        "results": results[:limit],
        "nominations": outcomes,
    }
