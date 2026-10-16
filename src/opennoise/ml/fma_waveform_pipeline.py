"""Permitted local audio to explicit descriptors, train-only layout and honest diagnostics."""

from __future__ import annotations

# ruff: noqa: PLR2004, TRY301 -- literal frozen protocol bounds and fail-closed stages.
import hashlib
import io
import json
import os
import selectors
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import numpy as np
import zstandard

from opennoise.common import canonical_json

PROTOCOL_SHA = "3a61f37a8bc0f0f9db6935bd5cb195e0d24eaf6ef56d86656d63efec8110b949"
MANIFEST_SHA = "242505b6c393185bdca4925b3ee97eb579fac93746091e8b0675809c8c0286cf"
FOLDS_SHA = "a43584aeb88c874576b2e7a84a25a2ebd1908385935f1c2a20b84e1273642ea7"
ROSTER_SHA = "1d9b1cbc4f6a6fb474cb319100d17e516b0bb49277a385b03203319750c8dfae"
REVISION = "fma-permitted55-waveform-layout-v1"
MAX_BYTES = 100_000_000
PCM_BYTES = 2_734_200
COLUMNS = [f"mel_{i:02d}_{stat}" for stat in ("mean", "std") for i in range(24)] + [
    "rms_mean",
    "rms_std",
    "zcr_mean",
    "zcr_std",
]
FILES = {
    "protocol.json",
    "declaration.json",
    "receipt.json",
    "features.npz",
    "model.npz",
    "evaluation.json",
    "layout.json",
}


def read(path: Path, cap: int = MAX_BYTES) -> bytes:
    """Never follow symlinked input/output paths or allocate beyond a declared bound."""
    if any(p.is_symlink() for p in (path, *path.parents)) or not path.is_file():
        raise ValueError("unsafe or absent file")
    if path.stat().st_size > cap:
        raise ValueError("file exceeds bound")
    return path.read_bytes()


def digest(body: bytes) -> str:
    """Hash exact artifact bytes."""
    return hashlib.sha256(body).hexdigest()


def binding(path: Path) -> dict[str, Any]:
    """Bind a bounded local file."""
    body = read(path)
    return {"sha256": digest(body), "bytes": len(body)}


def write(path: Path, value: Any) -> None:  # noqa: ANN401 -- explicit JSON artifact boundary.
    """Write fresh deterministic JSON."""
    body = canonical_json(value) + b"\n"
    with path.open("xb") as stream:
        stream.write(body)


def candidate(path: Path) -> dict[str, Any]:
    """Require the independently reviewed exact metadata authorization pin."""
    body = read(path, 200_000)
    if digest(body) != MANIFEST_SHA:
        raise ValueError("unreviewed candidate manifest")
    return json.loads(body)


def folds(path: Path, identities: list[int]) -> list[dict[str, Any]]:
    """Select the candidate roster from the exact retained component split."""
    body = read(path)
    if digest(body) != FOLDS_SHA:
        raise ValueError("component roster differs")
    found = {}
    with zstandard.ZstdDecompressor().stream_reader(io.BytesIO(body)) as stream:
        for line in io.TextIOWrapper(stream):
            row = json.loads(line)
            if row["track_id"] in identities:
                found[row["track_id"]] = row
    if set(found) != set(identities):
        raise ValueError("component roster incomplete")
    return [found[identity] for identity in identities]


def decode(path: Path) -> np.ndarray:  # noqa: C901 -- bounded multiplexed decoder completion.
    """Stream bounded PCM and stderr; require full completion without truncation."""
    command = [
        shutil.which("ffmpeg") or "ffmpeg",
        "-nostdin",
        "-v",
        "error",
        "-xerror",
        "-protocol_whitelist",
        "file,pipe",
        "-i",
        str(path.resolve()),
        "-vn",
        "-ac",
        "1",
        "-ar",
        "22050",
        "-f",
        "f32le",
        "pipe:1",
    ]
    process = subprocess.Popen(  # noqa: S603 -- fixed offline decoder, no shell.
        command, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    output, errors = bytearray(), bytearray()
    started = time.monotonic()
    if process.stdout is None or process.stderr is None:
        process.kill()
        raise ValueError("decoder pipes unavailable")
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ, (output, PCM_BYTES))
            selector.register(process.stderr, selectors.EVENT_READ, (errors, 200_000))
            while selector.get_map():
                remaining = 20 - (time.monotonic() - started)
                if remaining <= 0:
                    raise ValueError("decoder timeout")
                for key, _ in selector.select(min(remaining, 0.1)):
                    buffer, cap = key.data
                    chunk = os.read(key.fd, min(65536, cap + 1 - len(buffer)))
                    if not chunk:
                        selector.unregister(key.fileobj)
                    else:
                        buffer.extend(chunk)
                        if len(buffer) > cap:
                            raise ValueError("decoder output exceeds bound")
        if process.wait(timeout=max(0.001, 20 - (time.monotonic() - started))) != 0:
            raise ValueError("incomplete or failed full audio decode")
    finally:
        if process.poll() is None:
            process.kill()
        process.wait()
        process.stdout.close()
        process.stderr.close()
    if len(output) % 4 or len(output) < 2048 * 4:
        raise ValueError("incomplete decoded samples")
    values = np.frombuffer(output, dtype="<f4").astype(np.float64)
    if not np.isfinite(values).all():
        raise ValueError("nonfinite waveform")
    return values


def features(samples: np.ndarray) -> np.ndarray:
    """Fixed52 waveform descriptors; no metadata or labels enter this computation."""
    if samples.ndim != 1 or len(samples) < 2048 or not np.isfinite(samples).all():
        raise ValueError("invalid waveform")
    frames = np.lib.stride_tricks.sliding_window_view(samples, 2048)[::1024]
    window = np.hanning(2048)
    power = np.abs(np.fft.rfft(frames * window, axis=1)) ** 2 / np.sum(window**2)
    frequencies = np.fft.rfftfreq(2048, 1 / 22050)
    mel_edges = np.linspace(0, 2595 * np.log10(1 + 11025 / 700), 26)
    edges = 700 * (10 ** (mel_edges / 2595) - 1)
    filters = np.array(
        [
            np.maximum(0, np.minimum((frequencies - a) / (b - a), (c - frequencies) / (c - b)))
            for a, b, c in zip(edges[:-2], edges[1:-1], edges[2:], strict=True)
        ]
    )
    bands = np.log10(np.maximum(power @ filters.T, 1e-12))
    rms = np.sqrt(np.mean(frames**2, axis=1))
    zcr = np.mean((frames[:, :-1] < 0) != (frames[:, 1:] < 0), axis=1)
    return np.concatenate(
        (bands.mean(axis=0), bands.std(axis=0), [rms.mean(), rms.std(), zcr.mean(), zcr.std()])
    )


def fit(values: np.ndarray, training: np.ndarray) -> dict[str, np.ndarray]:
    """Fit population normalization and covariance only on original-training rows."""
    train = values[training]
    center, scale = train.mean(axis=0), train.std(axis=0)
    active = scale > 1e-12
    scale = np.where(active, scale, 1)
    standardized = (train - center) / scale
    standardized[:, ~active] = 0
    covariance = standardized.T @ standardized / len(train)
    eigenvalues, vectors = np.linalg.eigh(covariance)
    eigenvalues, vectors = eigenvalues[::-1], vectors[:, ::-1]
    tolerance = 1e-10 * max(1, eigenvalues[0])
    usable = bool(
        eigenvalues[1] > tolerance
        and eigenvalues[0] - eigenvalues[1] > tolerance
        and eigenvalues[1] - eigenvalues[2] > tolerance
    )
    axes = vectors[:, :2].copy()
    for column in range(2):
        if axes[np.argmax(np.abs(axes[:, column])), column] < 0:
            axes[:, column] *= -1
    return {
        "center": center,
        "scale": scale,
        "active": active,
        "eigenvalues": eigenvalues,
        "axes": axes,
        "projection_usable": np.array(usable),
    }


def transform(
    values: np.ndarray, model: dict[str, np.ndarray]
) -> tuple[np.ndarray, np.ndarray, list[str | None]]:
    """Apply saved normalization and PCA without updating fitted parameters."""
    standardized = (values - model["center"]) / model["scale"]
    standardized[:, ~model["active"]] = 0
    norms = np.linalg.norm(standardized, axis=1)
    reasons = [
        "out_of_support" if np.max(np.abs(row)) > 12 else "zero_norm" if norm <= 1e-12 else None
        for row, norm in zip(standardized, norms, strict=True)
    ]
    return standardized, standardized @ model["axes"], reasons


def rank(  # noqa: PLR0913, PLR0917 -- explicit frozen ranking inputs.
    query: int,
    values: np.ndarray,
    positions: np.ndarray,
    identities: np.ndarray,
    components: np.ndarray,
    pool: np.ndarray,
    method: str,
) -> list[int]:
    """Rank exact native candidates with one representative per component."""
    eligible = [int(i) for i in pool if components[i] != components[query]]
    if method == "raw":
        distances = {
            i: float(
                1
                - np.dot(values[query], values[i])
                / (np.linalg.norm(values[query]) * np.linalg.norm(values[i]))
            )
            for i in eligible
        }
    elif method == "pca":
        distances = {i: float(np.sum((positions[query] - positions[i]) ** 2)) for i in eligible}
    else:
        distances = {i: float(identities[i]) for i in eligible}
    ordered = sorted(eligible, key=lambda i: (distances[i], identities[i]))
    seen: set[int] = set()
    selected: list[int] = []
    for index in ordered:
        if int(components[index]) not in seen:
            selected.append(index)
            seen.add(int(components[index]))
    return selected


def metrics(
    tags: set[int], known: set[int], ordered: list[int], labels: list[set[int]]
) -> dict[str, Any]:
    """Retain observed-positive tag denominators, including unsupported outcomes."""
    result = {}
    for k in (1, 3):
        neighbors = ordered[:k]
        recovered = set().union(*(labels[i] for i in neighbors)) & tags
        result[str(k)] = {
            "hit": bool(recovered),
            "matching_neighbors": sum(bool(tags & labels[i]) for i in neighbors),
            "recall_all": len(recovered) / len(tags) if tags else None,
            "recall_known": len(recovered & known) / len(tags & known) if tags & known else None,
        }
    return result


def derive(
    values: np.ndarray,
    tracks: list[dict[str, Any]],
    roster: list[dict[str, Any]],
    model: dict[str, np.ndarray],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """One deterministic serving pool and explicit per-query heldout diagnostics."""
    ids = np.array([row["track_id"] for row in tracks])
    components = np.array([row["component_id"] for row in roster])
    training = np.array([row["fold"] == 0 for row in roster])
    labels = [set(row["genre_ids"]) for row in tracks]
    standardized, positions, reasons = transform(values, model)
    pool = np.array([i for i in range(len(ids)) if training[i] and reasons[i] is None], dtype=int)
    known = set().union(*(labels[i] for i in np.flatnonzero(training)))
    eligible_known = set().union(*(labels[i] for i in pool))
    projection = bool(model["projection_usable"])
    rows, diagnostics = [], []
    for i, identity in enumerate(ids):
        orders = {
            method: rank(i, standardized, positions, ids, components, pool, method)
            if reasons[i] is None and (method != "pca" or projection)
            else []
            for method in ("raw", "pca", "id")
        }
        projection_reason = (
            "projection_degenerate"
            if not projection
            else "out_of_support"
            if reasons[i] == "out_of_support"
            else None
        )
        rows.append(
            {
                "track_id": int(identity),
                "component_id": int(components[i]),
                "fold": roster[i]["fold"],
                "position": positions[i].tolist() if projection_reason is None else None,
                "projection_reason": projection_reason,
                "neighbors": [int(ids[j]) for j in orders["raw"][:6]],
                "neighbor_reason": reasons[i]
                or (None if orders["raw"] else "no_eligible_components"),
            }
        )
        raw, projected = orders["raw"][:3], orders["pca"][:3]
        rank_sum = sum(
            abs(
                (raw.index(j) + 1 if j in raw else 4)
                - (projected.index(j) + 1 if j in projected else 4)
            )
            for j in set(raw) | set(projected)
        )
        query_pool = [j for j in pool if components[j] != components[i]]
        query_known = set().union(*(labels[j] for j in query_pool))
        diagnostics.append(
            {
                "track_id": int(identity),
                "fold": roster[i]["fold"],
                "reason": reasons[i],
                "observed_tags": sorted(labels[i]),
                "training_known_tags": sorted(labels[i] & known),
                "eligible_pool_known_tags": sorted(labels[i] & eligible_known),
                "query_pool_known_tags": sorted(labels[i] & query_known),
                "eligible_components": len({int(components[j]) for j in query_pool}),
                "rankings": {
                    method: [int(ids[j]) for j in order] for method, order in orders.items()
                },
                "metrics": {
                    method: metrics(labels[i], known, order, labels)
                    if method != "pca" or projection
                    else None
                    for method, order in orders.items()
                },
                "overlap_at_3": len(set(raw) & set(projected)) / len(raw)
                if raw and projection
                else None,
                "rank_footrule_sum": rank_sum if raw and projection else None,
                "rank_footrule": rank_sum / 12 if raw and projection else None,
            }
        )
    genre_rows = []
    for genre in sorted(set().union(*labels)):
        all_indices = [i for i in range(len(ids)) if training[i] and genre in labels[i]]
        eligible = [i for i in pool if genre in labels[i]]
        count = len({int(components[i]) for i in eligible})
        reason = (
            "projection_degenerate"
            if not projection
            else "insufficient_training_components"
            if count < 3
            else None
        )
        genre_rows.append(
            {
                "genre_id": genre,
                "training_track_count": len(all_indices),
                "training_component_count": len({int(components[i]) for i in all_indices}),
                "eligible_training_track_count": len(eligible),
                "eligible_training_component_count": count,
                "position": positions[eligible].mean(axis=0).tolist() if reason is None else None,
                "reason": reason,
            }
        )
    evaluation = {
        "queries": diagnostics,
        "global_training_labels": sorted(known),
        "eligible_training_labels": sorted(eligible_known),
        "training_ids": ids[training].tolist(),
        "eligible_training_ids": ids[pool].tolist(),
        "musical_quality_validated": False,
        "limits": (
            "Selected license-reviewed sample; previously inspected folds "
            "are not fresh confirmation. "
            "Source tags are incomplete, not musical relevance judgments."
        ),
    }
    evaluation["aggregates"] = aggregate(diagnostics)
    return {"tracks": rows, "genres": genre_rows}, evaluation


def tool_versions() -> dict[str, str]:
    """Record the exact numerical library and decoder executable."""
    result = subprocess.run(  # noqa: S603 -- fixed decoder version query.
        [shutil.which("ffmpeg") or "ffmpeg", "-version"],
        capture_output=True,
        timeout=10,
        check=True,
    )
    return {
        "python": sys.version,
        "numpy": np.__version__,
        "ffmpeg": result.stdout.decode().splitlines()[0],
        "ffmpeg_sha256": digest(read(Path(shutil.which("ffmpeg") or "ffmpeg"))),
    }


def freeze(site: Path, roster_path: Path, protocol: Path, output: Path) -> dict[str, Any]:
    """Seal input identities, implementation and tool versions before reading waveforms."""
    manifest = candidate(site / "manifest.json")
    if digest(read(protocol)) != PROTOCOL_SHA or output.exists():
        raise ValueError("protocol or fresh declaration path differs")
    tracks = sorted(manifest["tracks"], key=lambda row: row["track_id"])
    roster = folds(roster_path, [row["track_id"] for row in tracks])
    inputs = {
        str(path.resolve()): binding(path)
        for path in [site / "manifest.json", roster_path, protocol]
    }
    for row in tracks:
        path = site / row["audio_path"]
        actual = binding(path)
        if actual != {"sha256": row["audio_sha256"], "bytes": row["audio_bytes"]}:
            raise ValueError("audio custody differs")
        inputs[str(path.resolve())] = actual
    implementation = [
        Path(__file__),
        Path(__file__).parents[3] / "scripts/run_fma_waveform_pipeline.py",
    ]
    value = {
        "revision": "fma-waveform-declaration-v1",
        "protocol_sha256": PROTOCOL_SHA,
        "candidate_manifest_sha256": MANIFEST_SHA,
        "site": str(site.resolve()),
        "protocol": str(protocol.resolve()),
        "inputs": inputs,
        "implementation": {str(path.resolve()): binding(path) for path in implementation},
        "tools": tool_versions(),
        "roster": roster,
        "limits": {"wall_seconds": 120, "memory_bytes": 1_000_000_000, "output_bytes": MAX_BYTES},
    }
    write(output, value)
    return value


def _fresh_directory(output: Path) -> None:
    if output.exists() or any(p.is_symlink() for p in (output, *output.parents)):
        raise ValueError("output must be fresh and nonsymlinked")
    output.mkdir(parents=True)


def run(declaration_path: Path, output: Path) -> dict[str, Any]:  # noqa: C901 -- staged custody and promotion.
    """Extract, fit and evaluate once under the caller's frozen process envelope."""
    declaration = json.loads(read(declaration_path))
    if declaration["protocol_sha256"] != PROTOCOL_SHA or declaration["tools"] != tool_versions():
        raise ValueError("declaration tools or protocol differ")
    for group in ("inputs", "implementation"):
        for name, expected in declaration[group].items():
            if binding(Path(name)) != expected:
                raise ValueError("frozen input or implementation changed")
    site = Path(declaration["site"])
    manifest = candidate(site / "manifest.json")
    tracks = sorted(manifest["tracks"], key=lambda row: row["track_id"])
    roster = declaration["roster"]
    if digest(canonical_json(roster)) != ROSTER_SHA:
        raise ValueError("frozen native roster differs")
    _fresh_directory(output)
    try:
        matrix = []
        for row in tracks:
            body = read(site / row["audio_path"], 2_000_000)
            if digest(body) != row["audio_sha256"]:
                raise ValueError("audio changed during extraction")
            with tempfile.TemporaryDirectory(prefix="waveform-snapshot-") as name:
                snapshot = Path(name) / "input.mp3"
                snapshot.write_bytes(body)
                matrix.append(features(decode(snapshot)))
        values = np.array(matrix)
        training = np.array([row["fold"] == 0 for row in roster])
        if values.shape != (55, 52) or int(training.sum()) != 47:
            raise ValueError("frozen sample scope differs")
        model = fit(values, training)
        layout, evaluation = derive(values, tracks, roster, model)
        np.savez(
            output / "features.npz",
            values=values,
            track_ids=np.array([r["track_id"] for r in tracks]),
        )
        np.savez(output / "model.npz", allow_pickle=False, **model)
        write(output / "evaluation.json", evaluation)
        (output / "protocol.json").write_bytes(read(Path(declaration["protocol"])))
        (output / "declaration.json").write_bytes(read(declaration_path))
        receipt = {
            "revision": "fma-waveform-receipt-v1",
            "protocol_sha256": PROTOCOL_SHA,
            "candidate_manifest_sha256": MANIFEST_SHA,
            "columns": COLUMNS,
            "fit_ids": [row["track_id"] for row in roster if row["fold"] == 0],
            "files": {
                name: binding(output / name)
                for name in (
                    "features.npz",
                    "model.npz",
                    "evaluation.json",
                    "declaration.json",
                    "protocol.json",
                )
            },
        }
        write(output / "receipt.json", receipt)
        layout.update(
            revision=REVISION,
            candidate_manifest_sha256=MANIFEST_SHA,
            protocol_sha256=PROTOCOL_SHA,
            receipt_sha256=digest(read(output / "receipt.json")),
            axes=["PC1", "PC2"],
            musical_quality_validated=False,
        )
        write(output / "layout.json", layout)
        if (output / "layout.json").stat().st_size > 200_000:
            raise ValueError("layout exceeds view bound")
        write(output / "inventory.json", {name: binding(output / name) for name in sorted(FILES)})
        if sum(p.stat().st_size for p in output.iterdir()) > MAX_BYTES:
            raise ValueError("output exceeds frozen bound")
        return validate_waveform_pack(output, site / "manifest.json")
    except BaseException:
        # A failed partial stage is evidence, never a valid pack or promoted result.
        (output / "inventory.json").unlink(missing_ok=True)
        raise


def validate_waveform_pack(pack: Path, candidate_manifest: Path) -> dict[str, Any]:  # noqa: C901, PLR0912 -- separate closed artifact gates.
    """Validate closed bytes, saved-state replay and exact source scope."""
    manifest = candidate(candidate_manifest)
    expected = FILES | {"inventory.json"}
    if {p.name for p in pack.iterdir()} != expected:
        raise ValueError("waveform pack inventory differs")
    inventory = json.loads(read(pack / "inventory.json", 200_000))
    if set(inventory) != FILES or sum(p.stat().st_size for p in pack.iterdir()) > MAX_BYTES:
        raise ValueError("waveform inventory size differs")
    for name in FILES:
        if binding(pack / name) != inventory[name]:
            raise ValueError("waveform artifact hash differs")
    if digest(read(pack / "protocol.json")) != PROTOCOL_SHA:
        raise ValueError("unreviewed waveform protocol")
    declaration = json.loads(read(pack / "declaration.json"))
    receipt = json.loads(read(pack / "receipt.json"))
    layout = json.loads(read(pack / "layout.json", 200_000))
    if (
        layout["revision"] != REVISION
        or layout["candidate_manifest_sha256"] != MANIFEST_SHA
        or layout["protocol_sha256"] != PROTOCOL_SHA
        or layout["receipt_sha256"] != digest(read(pack / "receipt.json"))
        or layout["musical_quality_validated"] is not False
        or receipt["columns"] != COLUMNS
    ):
        raise ValueError("layout custody differs")
    if (
        set(receipt["files"])
        != {"features.npz", "model.npz", "evaluation.json", "declaration.json", "protocol.json"}
        or declaration["protocol_sha256"] != PROTOCOL_SHA
        or declaration["candidate_manifest_sha256"] != MANIFEST_SHA
        or receipt["protocol_sha256"] != PROTOCOL_SHA
        or receipt["candidate_manifest_sha256"] != MANIFEST_SHA
        or set(layout)
        != {
            "revision",
            "candidate_manifest_sha256",
            "protocol_sha256",
            "receipt_sha256",
            "axes",
            "musical_quality_validated",
            "tracks",
            "genres",
        }
        or layout["axes"] != ["PC1", "PC2"]
    ):
        raise ValueError("unexpected declaration, receipt or layout scope")
    for name, entry in receipt["files"].items():
        if name not in FILES or binding(pack / name) != entry:
            raise ValueError("receipt custody differs")
    tracks = sorted(manifest["tracks"], key=lambda row: row["track_id"])
    roster = declaration["roster"]
    if digest(canonical_json(roster)) != ROSTER_SHA:
        raise ValueError("frozen native roster differs")
    if [r["track_id"] for r in roster] != [r["track_id"] for r in tracks]:
        raise ValueError("roster identity differs")
    with np.load(pack / "features.npz", allow_pickle=False) as saved:
        if set(saved.files) != {"values", "track_ids"}:
            raise ValueError("unexpected feature array keys")
        values = saved["values"]
        if (
            values.shape != (55, 52)
            or values.dtype != np.dtype("float64")
            or saved["track_ids"].shape != (55,)
            or saved["track_ids"].dtype.kind not in "iu"
            or not np.isfinite(values).all()
            or saved["track_ids"].tolist() != [r["track_id"] for r in tracks]
        ):
            raise ValueError("feature identity or scope differs")
    training = np.array([row["fold"] == 0 for row in roster])
    if receipt["fit_ids"] != [row["track_id"] for row in roster if row["fold"] == 0]:
        raise ValueError("receipt training IDs differ")
    if int(training.sum()) != 47:
        raise ValueError("training count differs")
    derived_model = fit(values, training)
    with np.load(pack / "model.npz", allow_pickle=False) as saved:
        if set(saved.files) != set(derived_model) or any(
            not np.array_equal(saved[key], value) for key, value in derived_model.items()
        ):
            raise ValueError("saved model differs from training-only fit")
    view, evaluation = derive(values, tracks, roster, derived_model)
    if (
        view["tracks"] != layout["tracks"]
        or view["genres"] != layout["genres"]
        or evaluation != json.loads(read(pack / "evaluation.json"))
    ):
        raise ValueError("saved layout or evaluation differs from replay")
    return layout


def aggregate(queries: list[dict[str, Any]]) -> dict[str, Any]:
    """Keep validation/test totals and explicit denominators alongside all query rows."""
    result = {}
    for fold, name in ((1, "validation"), (2, "test")):
        selected = [row for row in queries if row["fold"] == fold]
        methods = {}
        for method in ("raw", "pca", "id"):
            available = [row for row in selected if row["metrics"][method] is not None]
            methods[method] = {}
            for k in ("1", "3"):
                outcomes = [row["metrics"][method][k] for row in available]
                summary = {
                    "query_count": len(selected),
                    "defined_arm_count": len(available),
                    "hits": sum(row["hit"] for row in outcomes),
                }
                for metric in ("recall_all", "recall_known"):
                    scores = [row[metric] for row in outcomes if row[metric] is not None]
                    summary[metric] = {
                        "mean": sum(scores) / len(scores) if scores else None,
                        "denominator_queries": len(scores),
                    }
                methods[method][k] = summary
        result[name] = {
            "total_queries": len(selected),
            "supported_queries": sum(row["reason"] is None for row in selected),
            "known_label_queries": sum(bool(row["training_known_tags"]) for row in selected),
            "methods": methods,
        }
    return result
