"""Exploratory nested temperature scaling of pinned historical human-genre NB."""

from __future__ import annotations

import hashlib
from collections import Counter
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path
from typing import Any

import numpy as np
from scipy.special import logsumexp

from opennoise.ml import jamendo_human_genre as base
from opennoise.ml import jamendo_human_mood as native

PROTOCOL_SHA256 = "012af3ed3453c5157d3a5bce79323bdb086da2d8b18a594bca8c76e981b74eff"
SALT = "opennoise-jamendo-human-genre-temperature-inner-v1"
TEMPERATURES = (1, 2, 4, 8)
METHODS = (*base.METHODS, "temperature_nb")
BINS = (0, 0.2, 0.4, 0.6, 0.8, 1)
PAYLOAD_HASHES = {
    "predictions.json": "2bb3de821e30d87eff0672d31cbc2bde2d57212e87a982b89c5c5d5b4824c585",
    "models.json": "d13b4e8e807e703e9fdb71634ff00bfa6de78993dbeeb378153eb26f2c1a4208",
    "evaluation.json": "178f321e67cfe95b6b7830dd034690469f17316cff848b1ca39de07c5355fcb4",
}
DATA_FILES = {"models.json", "predictions.json", "evaluation.json"}


@dataclass(frozen=True)
class Inputs:
    """Explicit source stages and external pins; no implicit discovery or acquisition."""

    protocol: Path
    protocol_sha256: str
    prepared: Path
    identity_sha256: str
    census: Path
    census_sha256: str
    baseline: Path
    baseline_sha256: str

    @property
    def paths(self) -> tuple[Path, ...]:
        """Protect every input from output overlap."""
        return self.protocol, self.prepared, self.census, self.baseline

    def pins(self) -> dict[str, str]:
        """Bind the original immutable stages and new protocol."""
        return {
            "protocol": self.protocol_sha256,
            "identity_seal": self.identity_sha256,
            "census_seal": self.census_sha256,
            "result_receipt": self.baseline_sha256,
        }


def runtime() -> dict[str, Any]:
    """Keep the original runtime immutable and add this research implementation."""
    script = Path(__file__).resolve().parents[3] / "scripts/run_jamendo_genre_temperature.py"
    return {
        "original": base.runtime(),
        "code": {p.name: base.digest(p) for p in (Path(__file__), script)},
    }


def inner_fold(component: int, outer: int) -> int:
    """Use the one inspected, frozen hash, without reseeding."""
    return (
        int.from_bytes(hashlib.sha256(f"{SALT}|{outer}|{component}".encode()).digest(), "big") % 3
    )


def logits(model: dict[str, Any], row: native.Observation) -> np.ndarray:
    """Recover raw class scores directly; never log clipped stored probabilities."""
    tags = native.feature_tags(row)
    x = np.array([t in tags for t in model["vocabulary"]], dtype=float)
    theta = np.array(model["theta"])
    return np.log(model["prior"]) + (np.log(theta) * x + np.log1p(-theta) * (1 - x)).sum(axis=1)


def soften(scores: np.ndarray, temperature: int) -> np.ndarray:
    """Normalize raw logits at the fixed scalar temperature."""
    if temperature not in TEMPERATURES or not np.isfinite(scores).all():
        raise ValueError("Finite raw logits and frozen temperature required")
    scaled = scores / temperature
    return np.exp(scaled - logsumexp(scaled, axis=-1, keepdims=True))


def inner_census(
    rows: list[native.Observation], identities: list[dict[str, Any]]
) -> dict[str, Any]:
    """Count all fifteen training-only gates before any new fit or candidate score."""
    groups = {r["track_id"]: r["component_id"] for r in identities}
    eligible = [r for r in rows if base.vote_reason(r) is None]
    cells = []
    roles = []
    for outer in range(base.FOLDS):
        train = [r for r in eligible if base.fold(groups[r.track_id]) != outer]
        roles.extend(
            {
                "outer": outer,
                "track_id": r.track_id,
                "component_id": groups[r.track_id],
                "inner": inner_fold(groups[r.track_id], outer),
            }
            for r in train
        )
        for inner in range(3):
            fit = [r for r in train if inner_fold(groups[r.track_id], outer) != inner]
            valid = [r for r in train if inner_fold(groups[r.track_id], outer) == inner]
            counts = base.class_components(fit, groups)
            cells.append(
                {
                    "outer": outer,
                    "inner": inner,
                    "training_track_ids": [r.track_id for r in fit],
                    "validation_track_ids": [r.track_id for r in valid],
                    "training_components": sorted({groups[r.track_id] for r in fit}),
                    "validation_components": sorted({groups[r.track_id] for r in valid}),
                    "training_class_components": counts,
                    "fit_gate": all(n >= base.MIN_CLASS_COMPONENTS for n in counts),
                }
            )
    return {"cells": cells, "roles": roles, "fits": 0, "candidate_scores": 0}


def load(
    inputs: Inputs,
) -> tuple[
    list[native.Observation], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]
]:
    """Verify physical source artifacts and original code pins before accepting old outcomes."""
    if inputs.protocol_sha256 != PROTOCOL_SHA256 or base.digest(inputs.protocol) != PROTOCOL_SHA256:
        raise ValueError("Frozen temperature protocol pin differs")
    protocol = base.read(inputs.protocol)
    if base.runtime()["code"] != protocol["original_code"]:
        raise ValueError("Original source or implementation pins differ")
    rows, identities, _, _ = base.load_census(
        inputs.prepared, inputs.identity_sha256, inputs.census, inputs.census_sha256
    )
    base.check_inventory(inputs.baseline, DATA_FILES | {"receipt.json"})
    receipt = base.read(inputs.baseline / "receipt.json")
    if (
        base.digest(inputs.baseline / "receipt.json") != inputs.baseline_sha256
        or receipt["runtime"] != base.runtime()
        or receipt["identity_seal_sha256"] != inputs.identity_sha256
        or receipt["census_seal_sha256"] != inputs.census_sha256
        or receipt["protocol_sha256"] != base.PROTOCOL_SHA256
        or receipt["amendment_sha256"] != base.AMENDMENT_SHA256
        or any(receipt[k] != v for k, v in base.RIGHTS.items())
    ):
        raise ValueError("Pinned baseline receipt differs")
    base.check_file_bindings(inputs.baseline, DATA_FILES, receipt["files"])
    if any(base.digest(inputs.baseline / name) != pin for name, pin in PAYLOAD_HASHES.items()):
        raise ValueError("Historical baseline payload bytes differ")
    records = base.read(inputs.baseline / "predictions.json")
    models = base.read(inputs.baseline / "models.json")
    if [
        {k: r[k] for k in identity} for r, identity in zip(records, identities, strict=True)
    ] != identities:
        raise ValueError("Baseline complete identity cohort differs")
    return rows, identities, records, models


def seal(inputs: Inputs, files: dict[str, Any], revision: str) -> dict[str, Any]:
    """Describe deterministic bytes, source stages, implementation and rights."""
    return {
        "revision": revision,
        "inputs": inputs.pins(),
        "runtime": runtime(),
        "files": base.bindings(files),
        **base.RIGHTS,
    }


def census(inputs: Inputs, output: Path) -> str:
    """Publish roles/gates without any model fitting or temperature scoring."""
    base.destination(output, inputs.paths)
    rows, identities, _, _ = load(inputs)
    files = {"census.json": inner_census(rows, identities)}
    return base.publish(
        output,
        {**files, "seal.json": seal(inputs, files, "jamendo-temperature-census-v1")},
        inputs.paths,
    )


def load_sealed(
    inputs: Inputs, directory: Path, pin: str, names: set[str], revision: str
) -> dict[str, Any]:
    """Verify external pin, closed inventory and physical bytes before semantic replay."""
    receipt_name = "seal.json" if "census.json" in names else "receipt.json"
    base.check_inventory(directory, names | {receipt_name})
    receipt = base.read(directory / receipt_name)
    if base.digest(directory / receipt_name) != pin:
        raise ValueError("Research stage external pin differs")
    base.check_file_bindings(directory, names, receipt["files"])
    files = {name: base.read(directory / name) for name in names}
    if receipt != seal(inputs, files, revision):
        raise ValueError("Research stage pins, runtime, rights or content binding differs")
    return files


def temperature_selection(
    train: list[native.Observation], groups: dict[int, int], outer: int
) -> dict[str, Any]:
    """Choose on complete inner OOF training labels only, with explicit identity fallback."""
    splits = []
    for inner in range(3):
        fit = [r for r in train if inner_fold(groups[r.track_id], outer) != inner]
        valid = [r for r in train if inner_fold(groups[r.track_id], outer) == inner]
        if any(n < base.MIN_CLASS_COMPONENTS for n in base.class_components(fit, groups)):
            return {
                "temperature": 1,
                "reason": "inner_training_class_support_failed",
                "fits": [],
                "losses": None,
            }
        splits.append((fit, valid))
    expected = [r.track_id for r in train]
    observed = [r.track_id for _, valid in splits for r in valid]
    if (
        not expected
        or len(expected) != len(set(expected))
        or Counter(expected) != Counter(observed)
    ):
        return {
            "temperature": 1,
            "reason": "incomplete_inner_oof_coverage",
            "fits": [],
            "losses": None,
        }
    by_id = {}
    models = []
    for inner, (fit, valid) in enumerate(splits):
        model = base.fit(fit, groups)
        models.append(
            {
                "inner": inner,
                "model": model,
                "training_track_ids": [r.track_id for r in fit],
                "validation_track_ids": [r.track_id for r in valid],
            }
        )
        by_id.update({r.track_id: logits(model, r).tolist() for r in valid})
    if set(by_id) != set(expected):
        return {
            "temperature": 1,
            "reason": "incomplete_inner_oof_coverage",
            "fits": models,
            "losses": None,
        }
    scores = np.array([by_id[r.track_id] for r in train])
    y = np.array([base.target(r) for r in train])
    counts = Counter(groups[r.track_id] for r in train)
    weights = np.array([1 / counts[groups[r.track_id]] for r in train])
    losses = [
        float(np.average(base.losses(soften(scores, t), y)[:, 1], weights=weights))
        for t in TEMPERATURES
    ]
    chosen = min(zip(losses, TEMPERATURES, strict=True))[1]
    return {
        "temperature": chosen,
        "reason": None,
        "fits": models,
        "losses": losses,
        "clipping": {
            str(t): {
                "positive_target_class_cells": int(
                    ((soften(scores, t) < base.CLIP) & (y > 0)).sum()
                ),
                "tracks": int((((soften(scores, t) < base.CLIP) & (y > 0)).any(axis=1)).sum()),
            }
            for t in TEMPERATURES
        },
        "oof_logits": [{"track_id": r.track_id, "scores": by_id[r.track_id]} for r in train],
    }


def predictions(
    rows: list[native.Observation],
    identities: list[dict[str, Any]],
    baseline: list[dict[str, Any]],
    old_models: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Verify all original outer models/results, then change only the optional fourth method."""
    groups = {r["track_id"]: r["component_id"] for r in identities}
    by_id = {r.track_id: r for r in rows}
    selections = []
    for outer, old in enumerate(old_models):
        train = [
            r
            for r in rows
            if base.fold(groups[r.track_id]) != outer and base.vote_reason(r) is None
        ]
        if old["fold"] != outer or old["training_track_ids"] != [r.track_id for r in train]:
            raise ValueError("Original outer training membership differs")
        model = base.fit(train, groups) if old["model"] is not None else None
        if model != old["model"]:
            raise ValueError("Original outer model reproduction differs")
        selection = (
            temperature_selection(train, groups, outer)
            if model is not None
            else {
                "temperature": 1,
                "reason": "original_outer_abstention",
                "fits": [],
                "losses": None,
            }
        )
        selections.append({"outer": outer, **selection})
    records = []
    for old in baseline:
        row = by_id[old["track_id"]]
        outer = old["fold"]
        model = old_models[outer]["model"]
        original = base.predict(model, row) if model is not None else None
        if original != old["methods"]:
            raise ValueError("Original baseline probabilities differ")
        selection = selections[outer]
        methods = None
        if original is not None:
            calibrated = (
                original["genre_instrument_nb"]
                if selection["temperature"] == 1
                else soften(logits(model, row), selection["temperature"]).tolist()
            )
            methods = {**original, "temperature_nb": calibrated}
        records.append(
            {
                **old,
                "methods": methods,
                "temperature": selection["temperature"],
                "temperature_reason": selection["reason"],
            }
        )
    return records, selections


def aggregate(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Score matched methods and fixed paired component resamples, with no selection feedback."""
    rows = [r for r in records if r["scored"]]
    components = sorted({r["component_id"] for r in rows})
    index = {c: i for i, c in enumerate(components)}
    counts = np.array([sum(r["component_id"] == c for r in rows) for c in components], dtype=float)
    sums = np.zeros((len(components), len(METHODS), 2))
    clipping = {m: {"positive_target_class_cells": 0, "tracks": 0} for m in METHODS}
    for r in rows:
        p = np.array([r["methods"][m] for m in METHODS])
        y = np.array(r["target"])
        sums[index[r["component_id"]]] += base.losses(p, y)
        for j, m in enumerate(METHODS):
            clipped = (p[j] < base.CLIP) & (y > 0)
            clipping[m]["positive_target_class_cells"] += int(clipped.sum())
            clipping[m]["tracks"] += int(clipped.any())
    means = sums / counts[:, None, None]
    point = (
        np.stack((means.mean(axis=0), sums.sum(axis=0) / counts.sum()))
        if rows
        else np.full((2, len(METHODS), 2), np.nan)
    )
    rng = np.random.default_rng(20261019)
    samples = np.empty((2000, 2, len(METHODS), 2))
    if rows:
        for draw in range(2000):
            chosen = rng.integers(0, len(counts), size=len(counts))
            samples[draw] = np.stack(
                (means[chosen].mean(axis=0), sums[chosen].sum(axis=0) / counts[chosen].sum())
            )
    scopes = ("component_equal", "track_weighted")
    metrics = ("vote_brier", "fractional_log_loss")
    return {
        "counts": {
            "metadata_tracks": len(records),
            "metadata_components": len({r["component_id"] for r in records}),
            "taxonomy_nominations": sum(r.get("taxonomy_nominated", False) for r in records),
            "eligible_tracks": sum(r["target_reason"] is None for r in records),
            "predicted_components": len(
                {r["component_id"] for r in records if r["methods"] is not None}
            ),
            "predicted_tracks": sum(r["methods"] is not None for r in records),
            "scored_tracks": len(rows),
            "scored_components": len(components),
            "target_outcomes": dict(Counter(r["target_reason"] or "eligible" for r in records)),
        },
        "scores": {
            m: {
                f"{scope}_{metric}": float(point[s, j, k]) if rows else None
                for s, scope in enumerate(scopes)
                for k, metric in enumerate(metrics)
            }
            for j, m in enumerate(METHODS)
        },
        "clipping": clipping,
        "bootstrap": {
            "draws": 2000,
            "valid_draws": 2000 if rows else 0,
            "comparisons": {
                f"{METHODS[a]}-minus-{METHODS[b]}": {
                    scope: {
                        metric: {
                            "difference": float(point[s, a, k] - point[s, b, k]) if rows else None,
                            "interval": np.quantile(
                                samples[:, s, a, k] - samples[:, s, b, k], [0.025, 0.975]
                            ).tolist()
                            if rows
                            else None,
                        }
                        for k, metric in enumerate(metrics)
                    }
                    for s, scope in enumerate(scopes)
                }
                for a in range(len(METHODS))
                for b in range(a)
            },
        },
        **base.RIGHTS,
    }


def diagnostics(records: list[dict[str, Any]], rows: list[native.Observation]) -> dict[str, Any]:
    """Report fixed confidence bins, class masses and sampling without selection feedback."""
    scored = [r for r in records if r["scored"]]
    by_id = {r.track_id: r for r in rows}
    counts = Counter(r["component_id"] for r in scored)
    weights = np.array([1 / counts[r["component_id"]] for r in scored])
    weights /= weights.sum() if len(weights) else 1
    y = np.array([r["target"] for r in scored]).reshape(-1, len(base.CLASSES))
    methods = {}
    for m in METHODS:
        p = np.array([r["methods"][m] for r in scored]).reshape(-1, len(base.CLASSES))
        confidence = p.max(axis=1)
        agreement = y[np.arange(len(y)), p.argmax(axis=1)]
        bins = []
        for i, (a, b) in enumerate(pairwise(BINS)):
            mask = (confidence >= a) & (
                (confidence <= b) if i == len(BINS) - 2 else (confidence < b)
            )
            bins.append(
                {
                    "bounds": [a, b],
                    "tracks": int(mask.sum()),
                    "component_mass": float(weights[mask].sum()),
                    "confidence": float(np.average(confidence[mask], weights=weights[mask]))
                    if mask.any()
                    else None,
                    "agreement": float(np.average(agreement[mask], weights=weights[mask]))
                    if mask.any()
                    else None,
                }
            )
        methods[m] = {
            "bins": bins,
            "mean_confidence": float(weights @ confidence),
            "top_label_vote_agreement": float(weights @ agreement),
            "component_predicted_class_mass": (weights @ p).tolist(),
            "row_predicted_class_mass": p.mean(axis=0).tolist() if scored else None,
            "row_class_logloss_contribution": (-y * np.log(np.maximum(p, base.CLIP)))
            .mean(axis=0)
            .tolist()
            if scored
            else None,
            "component_class_logloss_contribution": (
                weights @ (-y * np.log(np.maximum(p, base.CLIP)))
            ).tolist(),
        }
    sampling = {}
    for reason in sorted({r["target_reason"] or "eligible" for r in records}):
        subset = [r for r in records if (r["target_reason"] or "eligible") == reason]
        tags = [native.feature_tags(by_id[r["track_id"]]) for r in subset]
        sampling[reason] = {
            "tracks": len(subset),
            "components": len({r["component_id"] for r in subset}),
            "genre_present": sum(any(t.startswith("genre---") for t in ts) for ts in tags),
            "instrument_present": sum(
                any(t.startswith("instrument---") for t in ts) for ts in tags
            ),
            "empty_feature_tracks": sum(not ts for ts in tags),
            "mean_tag_count": float(np.mean([len(ts) for ts in tags])),
        }
    return {
        "classes": list(base.CLASSES),
        "component_vote_mass": (weights @ y).tolist(),
        "row_vote_mass": y.mean(axis=0).tolist() if scored else None,
        "class_positive_tracks": (y > 0).sum(axis=0).tolist(),
        "class_votes": (y.sum(axis=0) * base.VOTES).round().astype(int).tolist(),
        "class_positive_components": [
            len({r["component_id"] for r in scored if r["target"][c] > 0})
            for c in range(len(base.CLASSES))
        ],
        "methods": methods,
        "sampling": sampling,
    }


def compute(inputs: Inputs, census_directory: Path, census_pin: str) -> dict[str, Any]:
    """Require sealed roles/gates before any new numeric model computation."""
    rows, identities, old, models = load(inputs)
    sealed = load_sealed(
        inputs, census_directory, census_pin, {"census.json"}, "jamendo-temperature-census-v1"
    )
    if sealed["census.json"] != inner_census(rows, identities):
        raise ValueError("Inner roles or support census differs")
    records, fitted = predictions(rows, identities, old, models)
    return {
        "predictions.json": records,
        "models.json": fitted,
        "evaluation.json": {**aggregate(records), "diagnostics": diagnostics(records, rows)},
    }


def evaluate(inputs: Inputs, census_directory: Path, census_pin: str, output: Path) -> str:
    """Publish bounded local predictions/models and restrained aggregate research results."""
    sources = (*inputs.paths, census_directory)
    base.destination(output, sources)
    files = compute(inputs, census_directory, census_pin)
    receipt = {
        **seal(inputs, files, "jamendo-temperature-result-v1"),
        "inner_census_sha256": census_pin,
    }
    return base.publish(output, {**files, "receipt.json": receipt}, sources)


def replay(
    inputs: Inputs, census_directory: Path, census_pin: str, output: Path, result_pin: str
) -> dict[str, Any]:
    """Verify exact physical bytes and deterministically reproduce all twenty fits and results."""
    # Result seal additionally binds the independently pinned inner census.
    base.check_inventory(output, DATA_FILES | {"receipt.json"})
    receipt = base.read(output / "receipt.json")
    if (
        base.digest(output / "receipt.json") != result_pin
        or receipt.get("inner_census_sha256") != census_pin
    ):
        raise ValueError("Result or inner census external pin differs")
    base.check_file_bindings(output, DATA_FILES, receipt["files"])
    files = {name: base.read(output / name) for name in DATA_FILES}
    if receipt != {
        **seal(inputs, files, "jamendo-temperature-result-v1"),
        "inner_census_sha256": census_pin,
    } or files != compute(inputs, census_directory, census_pin):
        raise ValueError("Result runtime, source, model, prediction or score replay differs")
    return files["evaluation.json"]
