"""Validation-component calibrated overlapping FMA source-recovery suggestions.

Percentiles describe observed positive-component ranks, never genre probabilities.
Source label absences are unknown. The frozen Gaussian is reused without fitting.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
import zstandard

from opennoise.common import sha256_file
from opennoise.ml.fma_acoustic_baseline import (
    MIN_LABEL_SUPPORT,
    RARE_TRAINING_SUPPORT,
    _json_rows,
)
from opennoise.ml.fma_saved_replay import replay_saved_pack

if TYPE_CHECKING:
    from collections.abc import Callable

REVISION = "fma-component-positive-memberships-v1"
MIN_COMPONENTS = 20
COVERAGE = 0.8
MAX_MEMBERSHIPS = 20
STABILITY_RADIUS = 2
DECLARATION_SHA256 = "39017287328e88c26ef23789cb35ed22eb4f250e5a61ae767a2fd84b9f01ccdb"


def calibration_half(component: int) -> bool:
    """Partition whole validation components without observing labels, scores or sizes."""
    return (
        int.from_bytes(hashlib.sha256(f"{REVISION}\0{component}".encode()).digest(), "big") % 2 == 0
    )


def component_threshold(values: list[int], vocabulary_size: int) -> int | None:
    """Finite-sample positive order statistic; insufficient or impossible support abstains."""
    if len(values) < MIN_COMPONENTS:
        return None
    position = math.ceil((len(values) + 1) * COVERAGE)
    threshold = sorted(values)[position - 1] if position <= len(values) else vocabulary_size + 1
    return threshold if threshold <= vocabulary_size else None


def fit_thresholds(
    calibration: list[dict[str, Any]], labels: list[int]
) -> dict[int, dict[str, Any]]:
    """Use only explicitly designated calibration rows and worst positive rank per component."""
    observations: dict[int, dict[int, int]] = {label: {} for label in labels}
    for row in calibration:
        if row["fold"] != 1 or not calibration_half(row["component_id"]):
            raise ValueError("non-calibration component entered threshold fitting")
        ranks = {label: i + 1 for i, label in enumerate(row["ranked_genre_ids"])}
        for label in row["genre_ids"] or []:
            value = ranks.get(label, len(labels) + 1)
            previous = observations[label].get(row["component_id"], 0)
            observations[label][row["component_id"]] = max(value, previous)
    return {
        label: {
            "threshold_rank": component_threshold(list(values.values()), len(labels)),
            "positive_components": len(values),
            "component_worst_positive_ranks": sorted(values.values()),
            "abstention": "insufficient_calibration_components"
            if len(values) < MIN_COMPONENTS
            else "unsupported_positive_rank_tail"
            if component_threshold(list(values.values()), len(labels)) is None
            else None,
        }
        for label, values in observations.items()
    }


def suggest(row: dict[str, Any], thresholds: dict[int, dict[str, Any]]) -> dict[str, Any]:
    """Emit bounded overlapping suggestions in a namespace separate from direct source facts."""
    candidates = []
    for rank, label in enumerate(row["ranked_genre_ids"], 1):
        calibration = thresholds[label]
        threshold = calibration["threshold_rank"]
        if threshold is None or rank > threshold:
            continue
        values = calibration["component_worst_positive_ranks"]
        percentile = sum(value >= rank for value in values) / len(values)
        candidates.append(
            {
                "genre_id": label,
                "source_positive_component_percentile": percentile,
                "raw_acoustic_rank": rank,
                "calibration_threshold_rank": threshold,
                "calibration_components": len(values),
                "threshold_stable_under_plus_minus_2_rank": rank + STABILITY_RADIUS <= threshold,
            }
        )
    candidates.sort(
        key=lambda item: (
            item["raw_acoustic_rank"] / item["calibration_threshold_rank"],
            item["raw_acoustic_rank"],
            item["genre_id"],
        )
    )
    # Threshold robustness differs from stability under bounded-set competition.
    selected = candidates[:MAX_MEMBERSHIPS]
    competitors = candidates[MAX_MEMBERSHIPS:]
    for item in selected:
        worst = (item["raw_acoustic_rank"] + STABILITY_RADIUS) / item["calibration_threshold_rank"]
        best_excluded = min(
            (
                (
                    max(1, other["raw_acoustic_rank"] - STABILITY_RADIUS)
                    / other["calibration_threshold_rank"]
                )
                for other in competitors
            ),
            default=float("inf"),
        )
        item["set_stable_under_plus_minus_2_rank"] = (
            item["threshold_stable_under_plus_minus_2_rank"] and worst < best_excluded
        )
    return {
        "track_id": row["track_id"],
        "namespace": "fma-track-source-model-v1",
        "memberships": selected,
        "uncapped_memberships": len(candidates),
        "abstention": row["reason"] or ("no_calibrated_membership" if not selected else None),
        "musical_probability": False,
        "direct_source_labels_inferred": False,
    }


def _bootstrap(components: dict[int, list[int]]) -> list[float] | None:
    if not components or not sum(value[1] for value in components.values()):
        return None
    values = np.array(list(components.values()), dtype=np.int64)
    rng = np.random.default_rng(72341)
    statistics = []
    for _ in range(200):
        totals = values[rng.integers(0, len(values), len(values))].sum(axis=0)
        statistics.append(float(totals[0] / max(1, totals[1])))
    return [float(value) for value in np.quantile(statistics, [0.025, 0.975])]


def evaluate_rows(
    rows: list[dict[str, Any]],
    thresholds: dict[int, dict[str, Any]],
    training_support: dict[int, int],
    *,
    suggestion_function: Callable[
        [dict[str, Any], dict[int, dict[str, Any]]], dict[str, Any]
    ] = suggest,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Retain every query/positive and cluster uncertainty by exact frozen native components."""
    components: dict[int, list[int]] = defaultdict(lambda: [0, 0])
    strata: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    abstentions: Counter[str] = Counter()
    outputs = []
    per_label: dict[int, list[int]] = defaultdict(lambda: [0, 0])
    label_components: dict[int, dict[int, list[int]]] = defaultdict(
        lambda: defaultdict(lambda: [0, 0])
    )
    raw_hits = raw_positives = uncapped_hits = stable_hits = unlabeled = 0
    for row in rows:
        output = suggestion_function(row, thresholds)
        outputs.append(output)
        targets = set(row["genre_ids"] or [])
        selected = {item["genre_id"] for item in output["memberships"]}
        stable = {
            item["genre_id"]
            for item in output["memberships"]
            if item["set_stable_under_plus_minus_2_rank"]
        }
        uncapped = {
            label
            for rank, label in enumerate(row["ranked_genre_ids"], 1)
            if thresholds[label]["threshold_rank"] is not None
            and rank <= thresholds[label]["threshold_rank"]
        }
        hit = len(targets & selected)
        components[row["component_id"]][0] += hit
        components[row["component_id"]][1] += len(targets)
        raw_hits += len(targets & set(row["ranked_genre_ids"][:20]))
        raw_positives += len(targets)
        uncapped_hits += len(targets & uncapped)
        stable_hits += len(targets & stable)
        unlabeled += not targets
        if output["abstention"]:
            abstentions[output["abstention"]] += 1
        for label in targets:
            support = training_support[label]
            stratum = (
                "unseen"
                if support == 0
                else "below_five"
                if support < MIN_LABEL_SUPPORT
                else "rare"
                if support <= RARE_TRAINING_SUPPORT
                else "supported"
            )
            strata[stratum][0] += label in selected
            strata[stratum][1] += 1
            per_label[label][0] += label in selected
            per_label[label][1] += 1
            label_components[label][row["component_id"]][0] += label in selected
            label_components[label][row["component_id"]][1] += 1
    sizes = [len(output["memberships"]) for output in outputs]
    return {
        "queries": len(rows),
        "components": len(components),
        "unlabeled_queries": unlabeled,
        "source_positives": raw_positives,
        "recovered_source_positives": sum(v[0] for v in components.values()),
        "bounded_positive_recall": sum(v[0] for v in components.values()) / max(1, raw_positives),
        "raw_acoustic_recall_at_20": raw_hits / max(1, raw_positives),
        "uncapped_positive_recall": uncapped_hits / max(1, raw_positives),
        "stable_positive_recall": stable_hits / max(1, raw_positives),
        "component_bootstrap_95_percent_interval": _bootstrap(components),
        "macro_positive_recall": float(np.mean([v[0] / v[1] for v in per_label.values()]))
        if per_label
        else 0,
        "set_size_mean": float(np.mean(sizes)) if sizes else 0,
        "set_size_quantiles": np.quantile(sizes, [0, 0.5, 0.9, 1]).tolist() if sizes else [],
        "uncapped_set_size_mean": float(np.mean([o["uncapped_memberships"] for o in outputs]))
        if outputs
        else 0,
        "abstentions": dict(sorted(abstentions.items())),
        "strata": {
            k: {"hits": v[0], "positives": v[1], "recall": v[0] / max(1, v[1])}
            for k, v in sorted(strata.items())
        },
        "per_label": {
            str(label): {
                "hits": value[0],
                "positives": value[1],
                "positive_recall": value[0] / value[1],
                "positive_components": len(label_components[label]),
                "fully_recovered_positive_components": sum(
                    counts[0] == counts[1] for counts in label_components[label].values()
                ),
                "calibration_components": thresholds[label]["positive_components"],
                "threshold_rank": thresholds[label]["threshold_rank"],
            }
            for label, value in sorted(per_label.items())
        },
        "precision_available": False,
        "musical_calibration_established": False,
    }, outputs


def _load_saved_groups(
    saved_pack: Path,
) -> tuple[dict[str, list[dict[str, Any]]], list[int], dict[int, int]]:
    """Reconstruct query groups from exact native IDs and frozen fold/target ledgers."""
    targets = {
        row["track_id"]: row for row in _json_rows(saved_pack / "held-out-native-targets.jsonl.zst")
    }
    folds = {row["track_id"]: row for row in _json_rows(saved_pack / "native-folds.jsonl.zst")}
    groups: dict[str, list[dict[str, Any]]] = {
        "calibration": [],
        "confirmation": [],
        "test_diagnostic": [],
    }
    for name in ("validation", "test"):
        for ranked in _json_rows(saved_pack / f"{name}-acoustic-ranks.jsonl.zst"):
            target = targets[ranked["track_id"]]
            fold = folds[ranked["track_id"]]
            if (
                target["fold"] != fold["fold"]
                or not fold["artist_known"]
                or not fold["component_id"]
            ):
                raise ValueError("query target/frozen component boundary differs")
            row = {**target, **fold, **ranked}
            group = (
                "test_diagnostic"
                if name == "test"
                else "calibration"
                if calibration_half(fold["component_id"])
                else "confirmation"
            )
            groups[group].append(row)
    baseline = json.loads((saved_pack / "evaluation.json").read_bytes())
    per_label = baseline["evaluation"]["validation"]["acoustic"]["per_label"]
    labels = [row["genre_id"] for row in per_label]
    support = {row["genre_id"]: row["training_positive_count"] for row in per_label}
    return groups, labels, support


def build_membership_pack(saved_pack: Path, declaration: Path, output: Path) -> dict[str, Any]:
    """Verify the baseline, calibrate one frozen arm and export exact re-playable evidence."""
    if sha256_file(declaration)[0] != DECLARATION_SHA256:
        raise ValueError("frozen membership declaration bytes differ")
    config = json.loads(declaration.read_bytes())
    if (
        config["revision"] != REVISION
        or config["coverage_target"] != COVERAGE
        or config["minimum_calibration_positive_components"] != MIN_COMPONENTS
        or config["maximum_memberships"] != MAX_MEMBERSHIPS
        or config["rank_stability_radius"] != STABILITY_RADIUS
    ):
        raise ValueError("frozen membership declaration differs")
    replay_saved_pack(saved_pack)
    output.mkdir(parents=True, exist_ok=False)
    groups, labels, support = _load_saved_groups(saved_pack)
    thresholds = fit_thresholds(groups["calibration"], labels)
    (output / "thresholds.json").write_text(json.dumps(thresholds, sort_keys=True, indent=2) + "\n")
    (output / "declaration.json").write_bytes(declaration.read_bytes())
    (output / "fma_memberships.py").write_bytes(Path(__file__).read_bytes())
    evaluation = {}
    for name, rows in groups.items():
        report, suggestions = evaluate_rows(rows, thresholds, support)
        evaluation[name] = report
        with (
            (output / f"{name}-memberships.jsonl.zst").open("xb") as raw,
            zstandard.ZstdCompressor(level=6).stream_writer(raw) as writer,
        ):
            for row, suggestion in zip(rows, suggestions, strict=True):
                writer.write(
                    (
                        json.dumps(
                            {
                                **suggestion,
                                "component_id": row["component_id"],
                                "observed_genre_ids": row["genre_ids"],
                            },
                            sort_keys=True,
                        )
                        + "\n"
                    ).encode()
                )
    results = {
        "revision": REVISION,
        "role": "native_fma_track_source_recovery_only",
        "baseline_pack_receipt_sha256": sha256_file(saved_pack / "pack-receipt.json")[0],
        "frozen_declaration_sha256": sha256_file(declaration)[0],
        "calibrated_labels": sum(row["threshold_rank"] is not None for row in thresholds.values()),
        "label_abstentions": dict(
            Counter(row["abstention"] for row in thresholds.values() if row["abstention"])
        ),
        "evaluation": evaluation,
        "model_refit": False,
        "model_selection": False,
        "musical_probability": False,
        "formal_coverage_guarantee_claimed": False,
        "native_source_replay_from_saved_pack_alone": False,
        "test_previously_observed": True,
        "artist_genre_assertions": False,
        "limitations": [
            "Native FMA track annotations are incomplete source observations, not musical truth.",
            (
                "Component-positive percentiles and coverage thresholds "
                "are not posterior probabilities."
            ),
            (
                "No exchangeable-component or stable-domain assumption is established; "
                "no formal coverage guarantee."
            ),
            "Bounding the output at twenty can reduce source-positive coverage below the target.",
            (
                "Confirmation partition is new for this arm; "
                "old aggregate validation baseline was previously reported."
            ),
            "Test is a previously observed diagnostic, not fresh evidence for selecting a model.",
            (
                "Rank-radius sensitivity is algebraic robustness, "
                "not audio perturbation or musical stability."
            ),
            "No native FMA to MusicBrainz artist or recording bridge is inferred.",
        ],
    }
    (output / "evaluation.json").write_text(json.dumps(results, sort_keys=True, indent=2) + "\n")
    bindings = {}
    for path in sorted(output.iterdir()):
        digest, size = sha256_file(path)
        bindings[path.name] = {"sha256": digest, "bytes": size}
    (output / "pack-receipt.json").write_text(
        json.dumps(
            {
                "revision": REVISION,
                "files": bindings,
                "baseline_pack_receipt_sha256": results["baseline_pack_receipt_sha256"],
                "license": "CC-BY-4.0",
                "audio_included": False,
            },
            sort_keys=True,
            indent=2,
        )
        + "\n"
    )
    return results


def replay_membership_pack(saved_pack: Path, output: Path) -> dict[str, Any]:
    """Reconstruct every threshold, membership and metric independently of saved result claims."""
    receipt = json.loads((output / "pack-receipt.json").read_bytes())
    expected_files = {
        "thresholds.json",
        "declaration.json",
        "fma_memberships.py",
        "evaluation.json",
        "calibration-memberships.jsonl.zst",
        "confirmation-memberships.jsonl.zst",
        "test_diagnostic-memberships.jsonl.zst",
    }
    if (
        set(receipt["files"]) != expected_files
        or receipt["license"] != "CC-BY-4.0"
        or receipt["audio_included"] is not False
    ):
        raise ValueError("membership pack boundary differs")
    for filename, binding in receipt["files"].items():
        path = output / filename
        if path.is_symlink() or sha256_file(path) != (binding["sha256"], binding["bytes"]):
            raise ValueError("membership pack byte binding differs")
    if receipt["baseline_pack_receipt_sha256"] != sha256_file(saved_pack / "pack-receipt.json")[0]:
        raise ValueError("membership baseline pack differs")
    if sha256_file(output / "declaration.json")[0] != DECLARATION_SHA256:
        raise ValueError("frozen membership declaration bytes differ")
    replay_saved_pack(saved_pack)
    groups, labels, support = _load_saved_groups(saved_pack)
    thresholds = fit_thresholds(groups["calibration"], labels)
    saved_thresholds = {
        int(key): value
        for key, value in json.loads((output / "thresholds.json").read_bytes()).items()
    }
    if thresholds != saved_thresholds:
        raise ValueError("membership threshold replay differs")
    report = json.loads((output / "evaluation.json").read_bytes())
    for name, rows in groups.items():
        metrics, suggestions = evaluate_rows(rows, thresholds, support)
        if metrics != report["evaluation"][name]:
            raise ValueError("membership metrics replay differs")
        actual = list(_json_rows(output / f"{name}-memberships.jsonl.zst"))
        expected = [
            {
                **suggestion,
                "component_id": row["component_id"],
                "observed_genre_ids": row["genre_ids"],
            }
            for row, suggestion in zip(rows, suggestions, strict=True)
        ]
        if actual != expected:
            raise ValueError("membership suggestion replay differs")
    return {
        "all_thresholds_metrics_memberships_match": True,
        "native_source_replay": False,
        "calibration_queries": len(groups["calibration"]),
        "confirmation_queries": len(groups["confirmation"]),
        "test_diagnostic_queries": len(groups["test_diagnostic"]),
        "model_refit": False,
    }
