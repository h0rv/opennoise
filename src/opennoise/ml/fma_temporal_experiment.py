"""Separately frozen mean+standard-deviation experiment on retained native metadata."""

# ruff: noqa: E501 -- immutable protocol descriptions.

from __future__ import annotations

import bz2
import csv
import io
import json
import math
import struct
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

import numpy as np
import zstandard
from scipy import sparse

from opennoise.common import canonical_json, sha256_file
from opennoise.ingest import fma_features
from opennoise.ingest.fma import corpus
from opennoise.ingest.fma.corpus import CheckedCSV
from opennoise.ingest.fma_features import MEMBER_NAME, SELECTED_COLUMNS, verify_feature_source
from opennoise.ml import fma_acoustic_baseline as baseline

REVISION = "fma-native-mean-std-diagnostic-v1"
COLUMNS = (*SELECTED_COLUMNS, *((name, "std", number) for name, _, number in SELECTED_COLUMNS))
LIMITS = {"model_run_seconds": 120, "memory_bytes": 1_000_000_000, "output_bytes": 100_000_000}
MAX_ROWS = 110_000


def _write(path: Path, value: object) -> None:
    with path.open("xb") as stream:
        stream.write(canonical_json(value) + b"\n")


def _binding(path: Path) -> dict[str, Any]:
    if any(item.is_symlink() for item in (path, *path.parents)):
        raise ValueError("symlinked experiment input")
    digest, size = sha256_file(path)
    return {"sha256": digest, "bytes": size}


def _input_paths(root: Path) -> list[Path]:
    paths = [root / "native-declaration.json"]
    for folder in ("metadata-source", "metadata", "feature-source", "baseline44"):
        paths.extend(path for path in (root / folder).rglob("*") if path.is_file())
    paths.extend(
        (
            Path(__file__),
            Path(baseline.__file__),
            Path(corpus.__file__),
            Path(fma_features.__file__),
            Path(__file__).parents[3] / "scripts/run_fma_temporal_experiment.py",
        )
    )
    return sorted(set(paths))


def freeze(root: Path, output: Path) -> dict[str, Any]:
    """Bind actual raw captures, baseline, projection and source before any candidate calculation."""
    paths = _input_paths(root)
    declared = {
        "revision": REVISION,
        "root": str(root.resolve()),
        "inputs": {str(path.resolve()): _binding(path) for path in sorted(set(paths))},
        "columns": COLUMNS,
        "limits": LIMITS,
        "fit": "Original known-artist fold0 only; unchanged components, Gaussian and support gates. One88D candidate versus frozen44D baseline. No tuning or recalibration.",
        "diagnostics": "Previously inspected outer validation/test; full target denominators, primary microRecall@10 then Recall@5/macro/MRR, abstentions zero. No model selection or musical quality claim.",
        "variability_not_temporal_order": True,
    }
    _write(output, declared)
    return declared


def verify(declaration: Path) -> tuple[Path, dict[str, Any]]:
    """Require every frozen input and the explicit experiment contract unchanged."""
    declared = json.loads(declaration.read_bytes())
    if (
        declared["revision"] != REVISION
        or declared["columns"] != [list(c) for c in COLUMNS]
        or declared["limits"] != LIMITS
    ):
        raise ValueError("experiment protocol differs")
    root = Path(declared["root"])
    if set(declared["inputs"]) != {str(p.resolve()) for p in _input_paths(root)}:
        raise ValueError("frozen input inventory differs")
    for name, binding in declared["inputs"].items():
        if _binding(Path(name)) != binding:
            raise ValueError(f"frozen experiment input differs: {name}")
    return Path(declared["root"]), declared


def positions(headers: list[list[str]]) -> list[int]:
    """Require every declared native column once in the exact three-level header."""
    if (
        len(headers) != 3  # noqa: PLR2004 -- native three-level CSV header.
        or [r[0] for r in headers] != ["feature", "statistics", "number"]
        or len({len(r) for r in headers}) != 1
    ):
        raise ValueError("native temporal headers differ")
    available = [
        (headers[0][i], headers[1][i], int(headers[2][i])) for i in range(1, len(headers[0]))
    ]
    if len(set(available)) != len(available) or not set(COLUMNS).issubset(available):
        raise ValueError("missing or duplicate native mean/std columns")
    return [available.index(column) + 1 for column in COLUMNS]


def project(declaration: Path, output: Path) -> dict[str, Any]:
    """Stream existing compressed member; preserve native means and require nonnegative std."""
    started = time.monotonic()
    root, _ = verify(declaration)
    source = root / "feature-source"
    member = verify_feature_source(source)["member"]
    output.mkdir(exist_ok=False)
    mean_path = source / "projection" / "features.float32"
    ids_path = source / "projection" / "track_ids.uint32"
    count = missing = 0
    row_struct = struct.Struct("<" + "f" * len(COLUMNS))
    with (
        (source / member["payload_path"]).open("rb") as raw,
        mean_path.open("rb") as means,
        ids_path.open("rb") as identities,
        (output / "features.float32").open("xb") as writer,
    ):
        if raw.read(len(MEMBER_NAME)) != MEMBER_NAME.encode():
            raise ValueError("native member filename differs")
        raw.seek(member["payload_prefix_bytes"])
        checked = CheckedCSV(bz2.BZ2File(raw), member)
        with io.TextIOWrapper(io.BufferedReader(checked), encoding="utf-8", newline="") as text:
            reader = csv.reader(text)
            headers = [next(reader) for _ in range(3)]
            selected = positions(headers)
            index = next(reader)
            if index[0] != "track_id" or any(index[1:]):
                raise ValueError("native ID header differs")
            for row in reader:
                if len(row) != len(headers[0]) or not row[0].isascii() or not row[0].isdecimal():
                    raise ValueError("native feature row malformed")
                identity = int(row[0])
                if identities.read(4) != struct.pack("<I", identity):
                    raise ValueError("native projection ID order differs")
                values = [float(row[i]) if row[i] else math.nan for i in selected]
                values = [value if math.isfinite(value) else math.nan for value in values]
                if any(value < 0 for value in values[len(SELECTED_COLUMNS) :]):
                    raise ValueError("negative native standard deviation")
                encoded = row_struct.pack(*values)
                if means.read(4 * len(SELECTED_COLUMNS)) != encoded[: 4 * len(SELECTED_COLUMNS)]:
                    raise ValueError("native mean columns differ from verified baseline")
                count += 1
                missing += not all(math.isfinite(v) for v in values)
                if count > MAX_ROWS or count * row_struct.size > LIMITS["output_bytes"]:
                    raise ValueError("temporal projection output bound exceeded")
                writer.write(encoded)
            if not checked.complete or means.read(1) or identities.read(1):
                raise ValueError("native feature stream or baseline projection incomplete")
    receipt = {
        "rows": count,
        "columns": COLUMNS,
        "nonfinite_rows": missing,
        "native_sha256": checked.sha256.hexdigest(),
        "declaration_sha256": _binding(declaration)["sha256"],
        "features": _binding(output / "features.float32"),
        "elapsed_seconds": time.monotonic() - started,
    }
    _write(output / "receipt.json", receipt)
    return receipt


def run(declaration: Path, projection: Path, output: Path) -> dict[str, Any]:  # noqa: C901, PLR0912, PLR0915 -- single fit/seal/diagnostic boundary.
    """Fit once, independently check training moments, seal, then score all outer queries."""
    started = time.monotonic()
    root, _ = verify(declaration)
    receipt = json.loads((projection / "receipt.json").read_bytes())
    original_projection = json.loads(
        (root / "feature-source/projection/projection-receipt.json").read_bytes()
    )
    if (
        receipt["columns"] != [list(c) for c in COLUMNS]
        or receipt["rows"] != original_projection["rows"]
        or receipt["native_sha256"] != original_projection["native_observed_sha256"]
    ):
        raise ValueError("temporal projection native shape or source hash differs")
    if receipt["declaration_sha256"] != _binding(declaration)["sha256"] or receipt[
        "features"
    ] != _binding(projection / "features.float32"):
        raise ValueError("temporal projection binding differs")
    native = root / "native-declaration.json"
    tracks, labels, _ = baseline.load_metadata(root / "metadata", json.loads(native.read_bytes()))
    identities, _, duplicates, _ = baseline.load_features(
        root / "feature-source" / "projection", native
    )
    values = np.fromfile(projection / "features.float32", dtype="<f4").reshape(
        len(identities), len(COLUMNS)
    )
    components = baseline.native_components(tracks, duplicates)
    positions_by_id = {row.track_id: i for i, row in enumerate(tracks)}
    features = np.full((len(tracks), len(COLUMNS)), np.nan, dtype=np.float32)
    present = np.zeros(len(tracks), dtype=bool)
    for i, identity in enumerate(identities):
        target = positions_by_id[int(identity)]
        features[target] = values[i]
        present[target] = True
    del values
    folds = np.array(
        [
            baseline.artist_group_fold(components[r.artist_id]) if r.artist_id else -1
            for r in tracks
        ],
        dtype=np.int8,
    )
    known = np.array([r.artist_known for r in tracks], dtype=bool)
    with (
        (root / "baseline44" / "native-folds.jsonl.zst").open("rb") as raw,
        zstandard.ZstdDecompressor().stream_reader(raw) as stream,
    ):
        ledger = [json.loads(line) for line in io.TextIOWrapper(stream)]
    for row, fold, saved in zip(tracks, folds, ledger, strict=True):
        if saved != {
            "track_id": row.track_id,
            "artist_id": row.artist_id,
            "artist_known": row.artist_known,
            "album_id": row.album_id,
            "component_id": components.get(row.artist_id),
            "fold": int(fold),
        }:
            raise ValueError("baseline component ledger differs")
    label_positions = {label: i for i, label in enumerate(labels)}
    cells = [(i, label_positions[label]) for i, row in enumerate(tracks) for label in row.genre_ids]
    targets = sparse.csr_matrix(
        (np.ones(len(cells)), tuple(zip(*cells, strict=True))), shape=(len(tracks), len(labels))
    )
    training = known & (folds == 0)
    support = np.asarray(targets[training].sum(axis=0)).ravel()
    model = baseline.fit_positive_gaussian(features, targets, training)
    finite_training = training & np.isfinite(features).all(axis=1)
    # Independent columnwise normalization check avoids using producer fit code.
    for column in range(len(COLUMNS)):
        vector = features[finite_training, column].astype(np.float64)
        np.testing.assert_allclose(model.center[column], np.mean(vector), rtol=1e-12, atol=1e-12)
        np.testing.assert_allclose(
            model.scale[column],
            np.sqrt(np.mean((vector - np.mean(vector)) ** 2)),
            rtol=1e-12,
            atol=1e-12,
        )
    normalized = (
        features[finite_training][:, model.active_columns].astype(np.float64)
        - model.center[model.active_columns]
    ) / model.scale[model.active_columns]
    positive_targets = targets[finite_training].tocsc()
    for label in range(len(labels)):
        selected_rows = positive_targets.indices[
            positive_targets.indptr[label] : positive_targets.indptr[label + 1]
        ]
        positive = normalized[selected_rows]
        mean = positive.mean(axis=0) if len(positive) else np.zeros(normalized.shape[1])
        variance = positive.var(axis=0) if len(positive) else np.zeros(normalized.shape[1])
        variance = np.maximum(0.5 * variance + 0.5, 0.1)
        np.testing.assert_allclose(model.quadratic[label], -0.5 / variance, rtol=1e-10, atol=1e-10)
        np.testing.assert_allclose(model.linear[label], mean / variance, rtol=1e-10, atol=1e-10)
        expected = -0.5 * np.sum(mean * mean / variance + np.log(variance)) + np.log(
            (support[label] + 0.5) / (int(training.sum()) + 1)
        )
        if len(positive) >= baseline.MIN_LABEL_SUPPORT:
            np.testing.assert_allclose(model.intercept[label], expected, rtol=1e-10, atol=1e-10)
        elif model.intercept[label] != -np.inf:
            raise ValueError("unsupported positive label received finite score")
    del normalized
    output.mkdir(exist_ok=False)
    np.savez(output / "model.npz", **asdict(model), labels=np.asarray(labels))
    seal = {
        "model": _binding(output / "model.npz"),
        "declaration_sha256": _binding(declaration)["sha256"],
        "projection": _binding(projection / "receipt.json"),
        "training_rows": int(training.sum()),
        "finite_training_rows": int(finite_training.sum()),
        "phase": "before outer diagnostic scoring",
    }
    _write(output / "pre-diagnostic-seal.json", seal)
    results = baseline._evaluate_folds(  # noqa: SLF001 -- unchanged full-denominator evaluation.
        features,
        targets=targets,
        folds=np.where(known, folds, -1),
        present=present,
        labels=labels,
        support=support,
        model=model,
        output=output,
        tracks=tracks,
    )
    if _binding(output / "model.npz") != seal["model"]:
        raise ValueError("model changed after seal")
    previous = json.loads((root / "baseline44" / "evaluation.json").read_bytes())["evaluation"]
    comparison = {}
    for fold in ("validation", "test"):
        old, new = previous[fold]["acoustic"], results[fold]["acoustic"]
        for field in (
            "queries",
            "source_positive_count",
            "unlabeled_queries",
            "training_unseen_positive_count",
        ):
            if old[field] != new[field]:
                raise ValueError("diagnostic denominator changed")
        comparison[fold] = {
            field: {"mean44": old[field], "mean_std88": new[field]}
            for field in (
                "queries",
                "source_positive_count",
                "abstentions",
                "recall_at_5",
                "recall_at_10",
                "macro_recall_at_5",
                "macro_recall_at_10",
                "mean_reciprocal_rank",
            )
        }
    report = {
        "revision": REVISION,
        "declaration_sha256": seal["declaration_sha256"],
        "training_rows": int(training.sum()),
        "finite_training_rows": int(finite_training.sum()),
        "active_columns": int(model.active_columns.sum()),
        "active_labels": int(model.active_labels.sum()),
        "evaluation": results,
        "comparison": comparison,
        "elapsed_seconds": time.monotonic() - started,
        "musical_quality_validated": False,
        "outer_results": "previously inspected diagnostic only; no selection",
        "independent_moment_checks": "all88 normalization columns and all164 Gaussian coefficient rows checked by direct positive-row mean/variance",
    }
    _write(output / "evaluation.json", report)
    size = sum(
        p.stat().st_size
        for directory in (projection, output)
        for p in directory.rglob("*")
        if p.is_file()
    )
    if size > LIMITS["output_bytes"] or report["elapsed_seconds"] > LIMITS["model_run_seconds"]:
        raise ValueError("temporal model resource bound exceeded")
    return report
