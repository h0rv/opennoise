"""Offline saved-rank replay; this does not establish absent native source custody."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import numpy as np

from opennoise.common import sha256_file
from opennoise.ml.fma_acoustic_baseline import (
    MIN_LABEL_SUPPORT,
    PositiveMetrics,
    _json_rows,
    training_baseline_rankings,
)

if TYPE_CHECKING:
    from pathlib import Path


def replay_saved_pack(directory: Path) -> dict[str, Any]:  # noqa: C901, PLR0912 - validate every independent saved-query contract before counting it.
    """Verify byte bindings and replay all positive-only metrics without source download or fit."""
    receipt = json.loads((directory / "pack-receipt.json").read_bytes())
    if (
        receipt["license"] != "CC-BY-4.0"
        or receipt["raw_source_replay_from_pack_alone"] is not False
        or receipt["artist_facts"] is not False
        or receipt["scores_calibrated"] is not False
        or receipt["audio_included"] is not False
        or receipt["public_product_promotion_authorized"] is not False
    ):
        raise ValueError("saved FMA source-recovery pack boundary differs")
    for filename, binding in receipt["files"].items():
        path = directory / filename
        if path.name != filename or path.is_symlink():
            raise ValueError("saved replay artifact must be a plain local filename")
        if sha256_file(path) != (binding["sha256"], binding["bytes"]):
            raise ValueError("saved replay artifact byte binding differs")
    report = json.loads((directory / "evaluation.json").read_bytes())
    target_rows = {1: {}, 2: {}}
    for row in _json_rows(directory / "held-out-native-targets.jsonl.zst"):
        fold = row["fold"]
        if fold not in target_rows or row["track_id"] in target_rows[fold]:
            raise ValueError("saved target fold or distinct track ID differs")
        target_rows[fold][row["track_id"]] = row["genre_ids"] or []
    results = {}
    for fold, name in ((1, "validation"), (2, "test")):
        expected = report["evaluation"][name]
        label_rows = expected["acoustic"]["per_label"]
        labels = [row["genre_id"] for row in label_rows]
        positions = {label: i for i, label in enumerate(labels)}
        support = np.array([row["training_positive_count"] for row in label_rows])
        popularity, constant = training_baseline_rankings(support)
        metrics = {
            arm: PositiveMetrics(labels, support) for arm in ("acoustic", "popularity", "constant")
        }
        seen = set()
        for row in _json_rows(directory / f"{name}-acoustic-ranks.jsonl.zst"):
            identity, ranked = row["track_id"], row["ranked_genre_ids"]
            if identity not in target_rows[fold] or identity in seen:
                raise ValueError("saved acoustic query differs from native target ledger")
            seen.add(identity)
            reason = row["reason"]
            if reason not in {
                None,
                "missing_feature_row",
                "missing_descriptors",
                "outside_training_support",
            }:
                raise ValueError("unexpected saved acoustic abstention reason")
            if (reason is not None and ranked) or len(set(ranked)) != len(ranked):
                raise ValueError("saved acoustic ranking duplicates or nonempty abstention")
            if any(
                report["model"]["feature_positive_support"].get(str(label), 0) < MIN_LABEL_SUPPORT
                for label in ranked
            ):
                raise ValueError("unsupported source label entered acoustic ranking")
            positive = [positions[label] for label in target_rows[fold][identity]]
            metrics["acoustic"].add(positive, [positions[label] for label in ranked], reason)
            metrics["popularity"].add(positive, popularity)
            metrics["constant"].add(positive, constant)
        if seen != set(target_rows[fold]):
            raise ValueError("saved rank ledger omits held-out raw metadata queries")
        actual = {arm: metric.report() for arm, metric in metrics.items()}
        if actual != expected:
            raise ValueError("saved positive-only metrics differ from complete query replay")
        results[name] = {"queries": len(seen), "all_saved_metrics_match": True}
    return {"native_source_replay": False, "model_refit": False, "folds": results}
