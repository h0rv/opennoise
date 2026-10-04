"""Fit and calibrate one frozen FMA arm entirely within original training components."""

from __future__ import annotations

import argparse
import json
import resource
import time
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from typing import Any

import numpy as np
import zstandard
from scipy import sparse

from opennoise.common import sha256_file
from opennoise.ml import fma_acoustic_baseline, fma_memberships, fma_training_memberships
from opennoise.ml.fma_acoustic_baseline import (
    PositiveGaussian,
    PositiveMetrics,
    artist_group_fold,
    fit_positive_gaussian,
    load_features,
    load_metadata,
    native_components,
    score_positive_gaussian,
)
from opennoise.ml.fma_training_memberships import (
    DECLARATION_SHA256,
    fit_thresholds,
    role,
    training_suggest,
)
from scripts.compare_fma_cosine_baseline import LIMITS, read_rows


def write_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    """Write losslessly replayable, compressed query evidence."""
    with path.open("xb") as raw, zstandard.ZstdCompressor(level=6).stream_writer(raw) as writer:
        for row in rows:
            writer.write((json.dumps(row, sort_keys=True) + "\n").encode())


def calibrate(args: argparse.Namespace) -> dict[str, Any]:  # noqa: C901, PLR0912, PLR0915 - single sealed artifact boundary.
    """Verify native inputs and unchanged folds, freeze fit/calibration, then score diagnostics."""
    started = time.monotonic()
    if sha256_file(args.declaration)[0] != DECLARATION_SHA256:
        raise ValueError("predeclared training-only protocol bytes differ")
    declared = json.loads(args.declaration.read_bytes())
    if (
        declared["limits"] != LIMITS
        or declared["native_declaration_sha256"] != sha256_file(args.native_declaration)[0]
        or declared["baseline_evaluation_sha256"]
        != sha256_file(args.baseline / "evaluation.json")[0]
    ):
        raise ValueError("native input binding or resource guards differ")
    baseline = json.loads((args.baseline / "evaluation.json").read_bytes())
    for name, binding in baseline["artifacts"].items():
        if sha256_file(args.baseline / name) != (binding["sha256"], binding["bytes"]):
            raise ValueError("baseline artifact differs")
    native_declaration = json.loads(args.native_declaration.read_bytes())
    tracks, labels, _ = load_metadata(args.metadata, native_declaration)
    ids, values, duplicates, _ = load_features(args.features, args.native_declaration)
    for path, key in (
        (args.metadata / "corpus-receipt.json", "metadata_receipt_sha256"),
        (args.features / "projection-receipt.json", "feature_receipt_sha256"),
    ):
        if sha256_file(path)[0] != baseline[key]:
            raise ValueError("inputs differ from original baseline")
    components = native_components(tracks, duplicates)
    ledger = []
    for row, saved in zip(tracks, read_rows(args.baseline / "native-folds.jsonl.zst"), strict=True):
        component = components.get(row.artist_id)
        fold = artist_group_fold(component) if component is not None else -1
        expected = {
            "track_id": row.track_id,
            "artist_id": row.artist_id,
            "artist_known": row.artist_known,
            "album_id": row.album_id,
            "component_id": component,
            "fold": fold,
        }
        if saved != expected:
            raise ValueError("original native fold ledger differs")
        ledger.append({**expected, "role": role(fold, component, artist_known=row.artist_known)})
    roles = np.array([row["role"] for row in ledger])
    training = roles == "inner_fit"
    positions = {row.track_id: i for i, row in enumerate(tracks)}
    features = np.full((len(tracks), values.shape[1]), np.nan, dtype=np.float32)
    present = np.zeros(len(tracks), dtype=bool)
    for i, identity in enumerate(ids):
        index = positions.get(int(identity))
        if index is None or present[index]:
            raise ValueError("feature IDs require distinct native metadata tracks")
        features[index] = values[i]
        present[index] = True
    label_positions = {label: i for i, label in enumerate(labels)}
    target_rows, target_columns = [], []
    for i, row in enumerate(tracks):
        for label in row.genre_ids:
            target_rows.append(i)
            target_columns.append(label_positions[label])
    targets = sparse.csr_matrix(
        (np.ones(len(target_rows), dtype=np.float64), (target_rows, target_columns)),
        shape=(len(tracks), len(labels)),
    )
    support = np.asarray(targets[training].sum(axis=0)).ravel()
    model = fit_positive_gaussian(features, targets, training)
    args.output.mkdir(parents=True, exist_ok=False)
    np.savez_compressed(args.output / "model.npz", **asdict(model), labels=np.array(labels))
    with np.load(args.output / "model.npz", allow_pickle=False) as loaded:
        restored = PositiveGaussian(**{k: loaded[k] for k in asdict(model)})
    for name, value in asdict(model).items():
        np.testing.assert_array_equal(value, getattr(restored, name))
    write_rows(args.output / "native-roles.jsonl.zst", ledger)
    for path in (
        args.declaration,
        Path(__file__),
        Path(fma_training_memberships.__file__),
        Path(fma_memberships.__file__),
        Path(fma_acoustic_baseline.__file__),
    ):
        (args.output / path.name).write_bytes(path.read_bytes())

    def ranked_rows(group: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        rows = []
        metric = PositiveMetrics(labels, support)
        selected = np.flatnonzero(roles == group)
        for start in range(0, len(selected), 512):
            batch = selected[start : start + 512]
            scores, reasons = score_positive_gaussian(restored, features[batch])
            ordered = np.argsort(-scores, axis=1, kind="stable")
            for i, index in enumerate(batch):
                track = tracks[index]
                reason = reasons[i] if present[index] else "missing_feature_row"
                ranking = (
                    [int(v) for v in ordered[i] if restored.active_labels[v]]
                    if reason is None
                    else []
                )
                metric.add([label_positions[v] for v in track.genre_ids], ranking, reason)
                rows.append(
                    {
                        **ledger[index],
                        "genre_ids": list(track.genre_ids),
                        "targets_missing": track.targets_missing,
                        "reason": reason,
                        "ranked_genre_ids": [labels[v] for v in ranking],
                    }
                )
        return rows, metric.report()

    calibration, calibration_metric = ranked_rows("inner_calibration")
    thresholds = fit_thresholds(calibration, list(labels))
    (args.output / "thresholds.json").write_text(
        json.dumps(thresholds, indent=2, sort_keys=True) + "\n"
    )
    frozen = {name: sha256_file(args.output / name)[0] for name in ("model.npz", "thresholds.json")}
    seal = {
        "artifacts": frozen,
        "stage": "fit_and_thresholds_frozen_before_any_external_scoring",
        "original_validation_and_test_previously_inspected": True,
        "refit_after_calibration": False,
    }
    (args.output / "pre-diagnostic-seal.json").write_text(
        json.dumps(seal, indent=2, sort_keys=True) + "\n"
    )
    evaluation = {}
    support_dict = dict(zip(labels, map(int, support), strict=True))
    for group in ("inner_calibration", "validation_diagnostic", "test_diagnostic"):
        rows, metric = (
            (calibration, calibration_metric)
            if group == "inner_calibration"
            else ranked_rows(group)
        )
        report, suggestions = fma_memberships.evaluate_rows(
            rows,
            thresholds,
            support_dict,
            suggestion_function=training_suggest,
        )
        if group != "inner_calibration":
            previous = baseline["evaluation"][group.removesuffix("_diagnostic")]["acoustic"]
            for key in ("queries", "labeled_queries", "source_positive_count"):
                if metric[key] != previous[key]:
                    raise ValueError("external diagnostic denominator changed")
        evaluation[group] = {
            "acoustic": metric,
            "memberships": report,
            "held_out_threshold_evaluation": group != "inner_calibration",
        }
        write_rows(args.output / f"{group}-ranks.jsonl.zst", rows)
        write_rows(args.output / f"{group}-memberships.jsonl.zst", suggestions)
    if any(sha256_file(args.output / name)[0] != digest for name, digest in frozen.items()):
        raise ValueError("sealed model or thresholds changed during diagnostics")
    coverage = {}
    for group in sorted(set(roles)):
        mask = roles == group
        sizes = Counter(ledger[i]["component_id"] for i in np.flatnonzero(mask))
        coverage[group] = {
            "queries": int(mask.sum()),
            "source_positives": int(targets[mask].sum()),
            "components": len(sizes),
            "largest_component_queries": max(sizes.values(), default=0),
            "missing_features": int((mask & ~present).sum()),
            "unlabeled_queries": sum(not tracks[i].genre_ids for i in np.flatnonzero(mask)),
            "missing_targets": sum(tracks[i].targets_missing for i in np.flatnonzero(mask)),
        }
    artifacts: dict[str, dict[str, Any]] = {
        p.name: {"sha256": sha256_file(p)[0], "bytes": p.stat().st_size}
        for p in sorted(args.output.iterdir())
    }
    result = {
        "revision": declared["revision"],
        "declaration_sha256": DECLARATION_SHA256,
        "coverage": coverage,
        "raw_coverage": baseline["coverage"],
        "original_partition": baseline["partition"],
        "inner_fit_source_positive_support": support_dict,
        "inner_fit_finite_positive_support": dict(
            zip(labels, map(int, model.label_feature_support), strict=True)
        ),
        "finite_fit_rows": model.training_rows,
        "active_labels": int(model.active_labels.sum()),
        "calibrated_labels": sum(v["threshold_rank"] is not None for v in thresholds.values()),
        "threshold_abstentions": dict(
            Counter(v["abstention"] for v in thresholds.values() if v["abstention"])
        ),
        "seal": seal,
        "seal_rechecked_after_diagnostics": True,
        "evaluation": evaluation,
        "selection_performed": False,
        "musical_calibration_established": False,
        "limitations": baseline["limitations"]
        + [
            "Previously inspected outer folds provide diagnostics, not fresh confirmation.",
            "Inner calibration metrics reuse threshold-fitting labels, not held-out evaluation.",
            "Fixed component allocation preserves giant-component imbalance; no rebalancing.",
        ],
        "resource": {
            "elapsed_seconds": time.monotonic() - started,
            "peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
            "limits": LIMITS,
        },
        "artifacts": artifacts,
    }
    encoded = (json.dumps(result, indent=2, sort_keys=True) + "\n").encode()
    if len(encoded) + sum(v["bytes"] for v in artifacts.values()) > LIMITS["new_outputs_bytes"]:
        raise ValueError("complete output budget exceeded")
    if time.monotonic() - started > LIMITS["model_run_seconds"]:
        raise ValueError("model run time budget exceeded")
    (args.output / "evaluation.json").write_bytes(encoded)
    return result


def main() -> None:
    """Apply unchanged memory/CPU guards and require explicit retained native inputs."""
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("metadata", "features", "native-declaration", "baseline", "declaration", "output"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    args = parser.parse_args()
    resource.setrlimit(resource.RLIMIT_AS, (LIMITS["memory_bytes"], LIMITS["memory_bytes"]))
    resource.setrlimit(
        resource.RLIMIT_CPU, (LIMITS["model_run_seconds"], LIMITS["model_run_seconds"])
    )
    result = calibrate(args)
    print(  # noqa: T201 - execution receipt.
        json.dumps(
            {k: result[k] for k in ("resource", "coverage", "active_labels", "calibrated_labels")}
        )
    )


if __name__ == "__main__":
    main()
