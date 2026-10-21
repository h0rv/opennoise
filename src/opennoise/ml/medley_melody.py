"""Local research-only native Melody2 contour search; no audio or identity inference."""

from __future__ import annotations

import hashlib
import json
import math
import platform
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import numpy as np

# The public implementation contains no source coordinates, names or results.
# ruff: noqa: PLR2004, TRY004 -- Closed native artifact and numerical schema.
REVISION = "medley-native-melody2-search-v1"
HOP = 256 / 44100
TOLERANCE = 5e-6
TICK = 1e-8
CHUNK = 128
MAX_TRACKS = 24
MAX_FILE = 2_000_000
MAX_RAW = 25_000_000
MAX_PACK = 30_000_000
MAX_METADATA = 1_000_000
MAX_FRAMES = 100_000
MAX_TOTAL_FRAMES = 1_800_000
MIN_QUERY = 173
MAX_QUERY = 1723
PREFIX = "medleydb/data/Annotations/Melody/Melody2/"
CAPS = {
    "cli_cpu_wall_seconds": 120,
    "cli_memory_bytes": 1_000_000_000,
    "nominations": MAX_TRACKS,
    "per_file_bytes": MAX_FILE,
    "query_frames_max": MAX_QUERY,
    "query_frames_min": MIN_QUERY,
    "returned_tracks_max": MAX_TRACKS,
    "source_frames_per_track": MAX_FRAMES,
    "source_total_frames": MAX_TOTAL_FRAMES,
    "total_raw_annotation_bytes": MAX_RAW,
}
CONTRACT = {  # Literal serialization of the externally pinned declaration.
    "distance": (
        "Mean over ALL query frames: squared semitone difference if bothvoiced;144 "
        "if voiced/unvoiced disagree;0 if bothunvoiced. Query>=25%voiced, candidate "
        "jointlyvoiced>=75%ofqueryvoiced. No learnedfit."
    ),
    "f0": (
        "finite float0or0<f0<=20000Hz;0unvoiced; no interpolation/resampling/"
        "octave correction/transposition invariance"
    ),
    "hop_denominator": 44100,
    "hop_numerator": 256,
    "kind": "human_reviewed_medleydb_melody2_f0_hz",
    "pitch": "Voiced MIDI semitones69+12log2(f0/440);unvoicedmasked",
    "ranking": (
        "Distance nearest-integer ticks of1e-8 semitone-squared, ties-to-even; "
        "earliestframewithintrack; onebestalignment pertrack; global distance ticks "
        "then nativeID then frame. No source or label normalization."
    ),
    "timestamp_tolerance_seconds": TOLERANCE,
}


def encoded(value: object) -> bytes:
    """Canonical finite JSON for local artifacts and request hashes."""
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
    ).encode()


def _hex(value: object, size: int = 64) -> bool:
    return isinstance(value, str) and re.fullmatch(rf"[a-f0-9]{{{size}}}", value) is not None


def _safe(path: Path) -> None:
    if any(part.is_symlink() for part in (path, *path.parents)):
        raise ValueError("symlink input or parent is unsupported")


def read_pinned(path: Path, pin: str, cap: int) -> bytes:
    """Check physical bytes before parsing, never following supplied symlinks."""
    _safe(path)
    if not _hex(pin) or not path.is_file() or path.stat().st_size > cap:
        raise ValueError("invalid bounded pinned file")
    data = path.read_bytes()
    if len(data) > cap or hashlib.sha256(data).hexdigest() != pin:
        raise ValueError("physical file hash differs")
    return data


def _json(data: bytes) -> dict[str, Any]:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate JSON field")
            result[key] = value
        return result

    def nonfinite(value: str) -> object:
        raise ValueError("nonfinite JSON literal: " + value)

    value = json.loads(data, object_pairs_hook=pairs, parse_constant=nonfinite)
    if not isinstance(value, dict):
        raise ValueError("expected JSON object")
    return value


def _inventory(root: Path) -> dict[str, dict[str, object]]:
    _safe(root)
    if not root.is_dir():
        raise ValueError("source pack must be a directory")
    paths = []
    for item in root.rglob("*"):
        paths.append(item)
        if len(paths) > MAX_TRACKS + 6:
            raise ValueError("source inventory count exceeds bound")
    if (
        len(paths) > MAX_TRACKS + 6
        or any(p.is_symlink() or not (p.is_file() or p.is_dir()) for p in paths)
        or any(p.is_dir() and p != root / "raw" for p in paths)
    ):
        raise ValueError("source inventory bound or symlink differs")
    files = [p for p in paths if p.is_file() and p != root / "manifest.json"]
    if sum(p.stat().st_size for p in files) > MAX_PACK:
        raise ValueError("source inventory exceeds byte bound")
    return {
        p.relative_to(root).as_posix(): {
            "bytes": p.stat().st_size,
            "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
        }
        for p in sorted(files)
    }


def _runtime() -> dict[str, object]:
    root = Path(__file__).resolve().parents[3]
    files = ("src/opennoise/ml/medley_melody.py", "scripts/query_melody_contour.py")
    return {
        "python": platform.python_version(),
        "numpy": np.__version__,
        "code_sha256": {f: hashlib.sha256((root / f).read_bytes()).hexdigest() for f in files},
    }


def _pilot(pilot: dict[str, Any]) -> list[str]:
    ids = pilot.get("nominated_native_track_ids")
    if (
        pilot.get("revision") != "medley-melody2-native-contour-pilot-v1"
        or pilot.get("source_repository") != "https://github.com/marl/medleydb"
        or not _hex(pilot.get("source_commit"), 40)
        or encoded(pilot.get("caps")) != encoded(CAPS)
        or encoded(pilot.get("contract")) != encoded(CONTRACT)
        or not isinstance(ids, list)
        or not 1 <= len(ids) <= MAX_TRACKS
        or any(
            not isinstance(x, str) or re.fullmatch(r"[A-Za-z0-9]+(?:_[A-Za-z0-9]+)+", x) is None
            for x in ids
        )
        or len(set(ids)) != len(ids)
    ):
        raise ValueError("native pilot schema or fixed metric contract differs")
    rights = pilot.get("rights")
    if (
        not isinstance(rights, dict)
        or rights.get("license") != "CC BY-NC-SA4.0"
        or rights.get("license_url") != "https://creativecommons.org/licenses/by-nc-sa/4.0/"
        or rights.get("local_research_only") is not True
        or rights.get("public_code_and_synthetic_fixtures_only") is not True
        or rights.get("publish_raw_derived_annotations_or_real_results") is not False
        or not isinstance(rights.get("attribution"), str)
        or not rights["attribution"].strip()
        or rights.get("source_notice") != "https://medleydb.weebly.com/downloads.html"
    ):
        raise ValueError("source research rights or attribution differs")
    return cast("list[str]", ids)


@dataclass(frozen=True)
class Contour:
    """Exact native timestamps and masked pitch values, without metadata joins."""

    times: np.ndarray
    f0: np.ndarray
    voiced: np.ndarray
    midi: np.ndarray


def contour(times: object, f0: object, *, query: bool) -> Contour:
    """Require native timing and explicit zero/unvoiced; never interpolate."""
    if not isinstance(times, (list, np.ndarray)) or not isinstance(f0, (list, np.ndarray)):
        raise ValueError("times and f0 must be numeric arrays")
    for values in (times, f0):
        if isinstance(values, list) and any(type(x) not in (int, float) for x in values):
            raise ValueError("boolean/string/non-numeric contour sample")
        if isinstance(values, np.ndarray) and values.dtype.kind not in "fiu":
            raise ValueError("contour array dtype is not real numeric")
    t, hz = np.array(times, dtype=np.float64, copy=True), np.array(f0, dtype=np.float64, copy=True)
    low, high = (MIN_QUERY, MAX_QUERY) if query else (1, MAX_FRAMES)
    if (
        t.ndim != 1
        or hz.shape != t.shape
        or not low <= len(t) <= high
        or not np.isfinite(t).all()
        or not np.isfinite(hz).all()
        or (t < 0).any()
        or (hz < 0).any()
        or (hz > 20000).any()
    ):
        raise ValueError("contour shape, finite values or native bounds differ")
    origin = t[0] if query else 0.0
    if (np.diff(t) <= 0).any() or np.abs((t - origin) - np.arange(len(t)) * HOP).max() > TOLERANCE:
        raise ValueError("native timestamp grid differs")
    voiced = hz > 0
    midi = np.zeros(len(t), dtype=np.float64)
    midi[voiced] = 69 + 12 * (np.log2(hz[voiced]) - math.log2(440))
    if not np.isfinite(midi).all():
        raise ValueError("MIDI conversion is nonfinite")
    for array in (t, hz, voiced, midi):
        array.flags.writeable = False
    return Contour(t, hz, voiced, midi)


def _csv(data: bytes) -> Contour:
    try:
        lines = data.decode("utf-8").splitlines()
        if not 1 <= len(lines) <= MAX_FRAMES:
            raise ValueError("native frame bound differs")  # noqa: TRY301 -- Native CSV error context.
        values = []
        number = r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?"
        for line in lines:
            pair = line.split(",")
            if len(pair) != 2 or any(re.fullmatch(number, value.strip()) is None for value in pair):
                raise ValueError("native CSV requires exactly two numeric columns")  # noqa: TRY301
            values.append([float(value) for value in pair])
        array = np.asarray(values, dtype=np.float64)
    except (ValueError, UnicodeError) as error:
        raise ValueError("invalid native two-column CSV") from error
    return contour(array[:, 0], array[:, 1], query=False)


@dataclass(frozen=True)
class Source:
    """Validated complete nomination ledger and locally retained native contours."""

    pin: str
    pilot: dict[str, Any]
    nominations: tuple[dict[str, Any], ...]
    contours: dict[str, Contour]
    inputs: dict[str, str]


def _source(root: Path, manifest: dict[str, Any], pin: str) -> Source:  # noqa: C901, PLR0912, PLR0915
    bindings = manifest["inputs"]
    pilot = _json(read_pinned(root / "pilot.json", bindings["pilot"], MAX_METADATA))
    ids = _pilot(pilot)
    preflight = _json(read_pinned(root / "preflight.json", bindings["preflight"], MAX_METADATA))
    census = _json(read_pinned(root / "census.json", bindings["census"], MAX_METADATA))
    if (
        preflight.get("pilot_sha256") != bindings["pilot"]
        or census.get("pilot_sha256") != bindings["pilot"]
        or census.get("preflight_sha256") != bindings["preflight"]
        or census.get("source_commit") != pilot["source_commit"]
    ):
        raise ValueError("source declaration/census association differs")
    rows, before = census.get("nominations"), preflight.get("nomination_outcomes")
    if (
        not isinstance(rows, list)
        or not isinstance(before, list)
        or any(not isinstance(r, dict) for r in rows + before)
        or [r.get("native_track_id") for r in rows] != ids
        or [r.get("native_track_id") for r in before] != ids
    ):
        raise ValueError("source nomination order differs")
    captures, raw_bytes, frames = {}, 0, 0
    allocated, exhausted = 0, False
    expected = {"pilot.json", "preflight.json", "census.json"}
    for row, prior in zip(rows, before, strict=True):
        native = row["native_track_id"]
        status = row.get("status")
        if status not in ("usable", "missing", "over_file_cap", "not_attempted_total_cap"):
            raise ValueError("unsupported source nomination status")
        if status == "missing":
            if (
                set(row) != {"native_track_id", "status"}
                or set(prior) != set(row)
                or prior.get("status") != "missing"
            ):
                raise ValueError("missing nomination contains invented source coordinates")
            continue
        path = PREFIX + native + "_MELODY2.csv"
        if (
            row.get("path") != path
            or prior.get("path") != path
            or not _hex(row.get("sha"), 40)
            or row.get("sha") != prior.get("sha")
            or type(row.get("size")) is not int
            or row["size"] <= 0
            or row["size"] != prior.get("size")
        ):
            raise ValueError("native source observation identity differs")
        if row["size"] > MAX_FILE:
            expected_status = "over_file_cap"
        elif exhausted or allocated + row["size"] > MAX_RAW:
            expected_status = "not_attempted_total_cap"
            exhausted = True
        else:
            expected_status = "nominated_for_capture"
            allocated += row["size"]
        if prior.get("status") != expected_status or status != (
            "usable" if expected_status == "nominated_for_capture" else expected_status
        ):
            raise ValueError("preflight source allocation rule differs")
        if status != "usable":
            continue
        name = "raw/" + native + "_MELODY2.csv"
        data = read_pinned(root / name, row.get("sha256"), MAX_FILE)
        if (
            type(row.get("bytes")) is not int
            or len(data) != row["bytes"]
            or len(data) != row["size"]
            or hashlib.sha1(
                b"blob " + str(len(data)).encode() + b"\0" + data, usedforsecurity=False
            ).hexdigest()
            != row["sha"]
        ):
            raise ValueError("native Git blob/byte identity differs")
        item = _csv(data)
        if (
            type(row.get("frames")) is not int
            or len(item.times) != row["frames"]
            or type(row.get("voiced_frames")) is not int
            or int(item.voiced.sum()) != row["voiced_frames"]
        ):
            raise ValueError("native frame census differs")
        if "git_blob_sha1" in row and row["git_blob_sha1"] != row["sha"]:
            raise ValueError("duplicate native Git blob binding differs")
        if "max_grid_error_seconds" in row:
            error = float(
                np.abs(
                    item.times - np.arange(len(item.times), dtype=np.float64) * 256 / 44100
                ).max()
            )
            if (
                type(row["max_grid_error_seconds"]) not in (int, float)
                or row["max_grid_error_seconds"] != error
            ):
                raise ValueError("native timestamp census differs")
        center_fields = {
            "center_query_frames",
            "center_query_start_frame",
            "center_query_voiced_frames",
            "query_status",
        }
        if center_fields & set(row):
            if len(item.times) < 862:
                if (
                    center_fields & set(row) != {"query_status"}
                    or row["query_status"] != "insufficient_length"
                ):
                    raise ValueError("fixed short-query census differs")
            else:
                if not center_fields <= set(row):
                    raise ValueError("incomplete fixed center-query census")
                start = (len(item.times) - 862) // 2
                voiced = int(item.voiced[start : start + 862].sum())
                if (
                    any(type(row[k]) is not int for k in center_fields - {"query_status"})
                    or row["center_query_frames"] != 862
                    or row["center_query_start_frame"] != start
                    or row["center_query_voiced_frames"] != voiced
                    or row["query_status"]
                    != ("eligible" if voiced * 4 >= 862 else "insufficient_voicing")
                ):
                    raise ValueError("fixed center-query census differs")
        captures[native] = item
        raw_bytes += len(data)
        frames += len(item.times)
        expected.add(name)
    if (
        type(preflight.get("allocated_annotation_bytes")) is not int
        or preflight["allocated_annotation_bytes"] != allocated
        or raw_bytes > MAX_RAW
        or frames > MAX_TOTAL_FRAMES
        or type(census.get("total_raw_bytes")) is not int
        or type(census.get("total_usable_frames")) is not int
        or type(census.get("captures")) is not int
        or raw_bytes != census.get("total_raw_bytes")
        or frames != census.get("total_usable_frames")
        or len(captures) != census.get("captures")
        or set(_inventory(root)) != expected
    ):
        raise ValueError("source closed inventory/census total differs")
    return Source(pin, pilot, tuple(rows), captures, bindings)


def load_source(root: Path, pin: str) -> Source:
    """Replay a closed externally pinned local source pack before querying."""
    _inventory(root)
    manifest = _json(read_pinned(root / "manifest.json", pin, MAX_METADATA))
    if (
        set(manifest) != {"revision", "inputs", "runtime", "files"}
        or manifest["revision"] != REVISION
        or manifest["runtime"] != _runtime()
        or not isinstance(manifest["inputs"], dict)
        or set(manifest["inputs"]) != {"pilot", "preflight", "census"}
        or not all(_hex(v) for v in manifest["inputs"].values())
        or not isinstance(manifest["files"], dict)
    ):
        raise ValueError("source manifest schema/runtime differs")
    for value in manifest["files"].values():
        if (
            not isinstance(value, dict)
            or set(value) != {"sha256", "bytes"}
            or not _hex(value["sha256"])
            or type(value["bytes"]) is not int
            or value["bytes"] < 0
        ):
            raise ValueError("source physical binding schema differs")
    if manifest["files"] != _inventory(root):
        raise ValueError("source physical inventory differs")
    return _source(root, manifest, pin)


def build_source(  # noqa: C901, PLR0913, PLR0917 -- Explicit external custody pins.
    raw: Path,
    pilot: Path,
    pilot_sha256: str,
    preflight: Path,
    preflight_sha256: str,
    census: Path,
    census_sha256: str,
    output: Path,
) -> str:
    """Validate and atomically stage a fresh local-only source pack without fetching."""
    _safe(raw)
    _safe(output)
    if (
        output.exists()
        or output.resolve().is_relative_to(raw.resolve())
        or any(output.resolve() == p.resolve() for p in (pilot, preflight, census))
    ):
        raise ValueError("source output must be fresh and separate from inputs")
    records = {
        "pilot": (pilot, pilot_sha256),
        "preflight": (preflight, preflight_sha256),
        "census": (census, census_sha256),
    }
    data = {name: read_pinned(path, sha, MAX_METADATA) for name, (path, sha) in records.items()}
    ids = _pilot(_json(data["pilot"]))
    roster = _json(data["census"])["nominations"]
    if (
        not isinstance(roster, list)
        or any(not isinstance(row, dict) for row in roster)
        or [row.get("native_track_id") for row in roster] != ids
    ):
        raise ValueError("source nomination order differs")
    files = {
        row["native_track_id"] + "_MELODY2.csv" for row in roster if row.get("status") == "usable"
    }
    _safe(raw)
    actual = []
    for item in raw.iterdir():
        actual.append(item)
        if len(actual) > MAX_TRACKS:
            raise ValueError("raw capture count exceeds bound")
    if (
        any(p.is_symlink() or not p.is_file() or p.stat().st_size > MAX_FILE for p in actual)
        or sum(p.stat().st_size for p in actual) > MAX_RAW
        or {p.name for p in actual} != files
    ):
        raise ValueError("raw capture inventory differs")
    output.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".melody-", dir=output.parent))
    try:
        (stage / "raw").mkdir()
        for name, value in data.items():
            (stage / (name + ".json")).write_bytes(value)
        for row in roster:
            if row.get("status") == "usable":
                name = row["native_track_id"] + "_MELODY2.csv"
                (stage / "raw" / name).write_bytes(read_pinned(raw / name, row["sha256"], MAX_FILE))
        manifest = {
            "revision": REVISION,
            "inputs": {name: sha for name, (_, sha) in records.items()},
            "runtime": _runtime(),
            "files": _inventory(stage),
        }
        body = encoded(manifest)
        (stage / "manifest.json").write_bytes(body)
        pin = hashlib.sha256(body).hexdigest()
        load_source(stage, pin)
        if output.exists() or output.is_symlink():
            raise ValueError("source destination appeared during build")
        stage.rename(output)
        return pin
    finally:
        if stage.exists():
            shutil.rmtree(stage)


def _best(source: Contour, query: Contour) -> dict[str, Any] | None:
    n, m = len(source.times), len(query.times)
    if n < m:
        return None
    pitch = np.lib.stride_tricks.sliding_window_view(source.midi, m)
    voiced = np.lib.stride_tricks.sliding_window_view(source.voiced, m)
    best: dict[str, Any] | None = None
    count = int(query.voiced.sum())
    for offset in range(0, len(pitch), CHUNK):
        v = voiced[offset : offset + CHUNK]
        joint = v & query.voiced
        overlap = joint.sum(axis=1)
        eligible = overlap * 4 >= count * 3
        if not eligible.any():
            continue
        mismatch = v != query.voiced
        costs = np.where(
            joint,
            np.square(pitch[offset : offset + CHUNK] - query.midi),
            np.where(mismatch, 144.0, 0.0),
        )
        scores = np.asarray(np.sum(costs, axis=1, dtype=np.float64) / m, dtype=np.float64)
        if not np.isfinite(scores).all():
            raise ValueError("nonfinite contour distance")
        scaled = np.rint(scores / TICK)
        if not np.isfinite(scaled).all() or (scaled < 0).any() or (scaled >= 2**63).any():
            raise ValueError("contour distance quantization is out of range")
        ticks = scaled.astype(np.int64)
        positions = np.flatnonzero(eligible)
        local = int(positions[np.argmin(ticks[positions])])
        tick = int(ticks[local])
        if best is None or tick < best["distance_ticks"]:
            start = offset + local
            best = {
                "start_frame": start,
                "end_frame_exclusive": start + m,
                "first_sample_time_seconds": float(source.times[start]),
                "last_sample_time_seconds": float(source.times[start + m - 1]),
                "distance_ticks": tick,
                "mean_squared_midi_distance": float(scores[local]),
                "joint_voiced_frames": int(overlap[local]),
                "voicing_mismatch_frames": int(mismatch[local].sum()),
            }
    return best


def search_contour(
    source: Source, request: dict[str, Any], *, limit: int = MAX_TRACKS
) -> dict[str, Any]:
    """Search new caller coordinates at fixed absolute pitch and tempo; no fit or audio."""
    if type(limit) is not int or not 1 <= limit <= MAX_TRACKS:
        raise ValueError("result limit must be an integer in 1..24")
    if not isinstance(request, dict) or set(request) != {"times_seconds", "f0_hz"}:
        raise ValueError("query schema requires only times_seconds and f0_hz")
    query = contour(request["times_seconds"], request["f0_hz"], query=True)
    count = int(query.voiced.sum())
    supported = count * 4 >= len(query.times)
    results, outcomes = [], []
    for row in source.nominations:
        native = row["native_track_id"]
        status = row["status"]
        reason = "source_unavailable"
        if status == "usable":
            item = source.contours[native]
            reason = "query_insufficient_voicing" if not supported else "shorter_than_query"
            if supported and len(item.times) >= len(query.times):
                match = _best(item, query)
                reason = "insufficient_joint_voicing" if match is None else "matched"
                if match is not None:
                    results.append(
                        {
                            "native_track_id": native,
                            **match,
                            "source_annotation_sha256": row["sha256"],
                        }
                    )
        outcomes.append({"native_track_id": native, "source_status": status, "status": reason})
    results.sort(
        key=lambda row: (row["distance_ticks"], row["native_track_id"], row["start_frame"])
    )
    return {
        "revision": REVISION,
        "source_manifest_sha256": source.pin,
        "source_inputs": source.inputs,
        "rights": source.pilot["rights"],
        "source_repository": source.pilot["source_repository"],
        "source_commit": source.pilot["source_commit"],
        "scope": "local_native_annotation_contour_alignment_only",
        "status": "completed" if supported else "query_insufficient_voicing",
        "query": {
            "frames": len(query.times),
            "voiced_frames": count,
            "origin_seconds": float(query.times[0]),
            "sha256": hashlib.sha256(
                encoded({"times_seconds": query.times.tolist(), "f0_hz": query.f0.tolist()})
            ).hexdigest(),
        },
        "limit": limit,
        "results": results[:limit],
        "nominations": outcomes,
    }
