"""Prespecified local research: inner-component calibration of human-vote NB."""

from __future__ import annotations

import hashlib
import json
import resource
import time
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
from scipy.optimize import minimize
from scipy.special import expit, logit

from opennoise.ml import jamendo_human_mood as base

PROTOCOL_SHA256 = "a4dfc1148e339cfb8980f50cddccb6b2e020645694bde42ec174af65e724f0d4"
PREPARED_SHA256 = "9417ff2fe7b10325497386c784d7c7f53276e02114df7140686386c5620b91b8"
METHODS = ("inner_fit_nb", "calibrated_nb", "inner_fit_human_prior")
EPS = 1e-12
RIDGE = 0.01
MAX_OUTPUT = 20_000_000
MIN_CALIBRATION_COMPONENTS = 2
ATTRIBUTION = "MTG-Jamendo Dataset; human music-classification annotations"


def role(component: int, outer: int) -> str:
    """Assign entire components independently of feature and target values."""
    if outer not in range(5):
        raise ValueError("Invalid outer fold")
    if base.fold(component) == outer:
        return "query"
    key = f"jamendo-calibration-inner-v1\0{outer}\0{component}".encode()
    return "calibration" if int.from_bytes(hashlib.sha256(key).digest(), "big") % 5 == 0 else "fit"


def weights(groups: list[int]) -> np.ndarray:
    """Normalize equal-component mass to one across eligible rows."""
    counts = Counter(groups)
    return np.array([1 / (len(counts) * counts[g]) for g in groups])


@dataclass(frozen=True)
class Calibrator:
    """Identity fallback is distinguished from a fitted slope and intercept."""

    slope: float
    intercept: float
    reason: str | None
    iterations: int
    objective: float | None
    components: int
    happy_mass: float
    not_happy_mass: float
    constant_input: bool


def objective(
    parameters: np.ndarray, x: np.ndarray, y: np.ndarray, w: np.ndarray
) -> tuple[float, np.ndarray]:
    """Convex fractional log loss, regularized toward identity calibration."""
    eta = parameters[0] * x + parameters[1]
    offset = parameters - np.array([1.0, 0.0])
    error = w * (expit(eta) - y)
    value = w @ (np.logaddexp(0, eta) - y * eta) + RIDGE / 2 * (offset @ offset)
    return float(value), np.array([error @ x, error.sum()]) + RIDGE * offset


def fit_calibrator(p: np.ndarray, y: np.ndarray, groups: list[int]) -> Calibrator:
    """Fit only supplied calibration components, never outer-query labels."""
    p, y = np.asarray(p, dtype=float), np.asarray(y, dtype=float)
    if p.ndim != 1 or p.shape != y.shape or len(p) != len(groups):
        raise ValueError("Calibration shapes differ")
    if (
        not np.isfinite(p).all()
        or not np.isfinite(y).all()
        or np.any((p < 0) | (p > 1) | (y < 0) | (y > 1))
    ):
        raise ValueError("Invalid calibration probabilities/targets")
    w = weights(groups)
    happy = float(w @ y)
    negative = float(w @ (1 - y))
    components = len(set(groups))
    constant = bool(len(p) and np.all(p == p[0]))
    reason = (
        "insufficient_calibration_components"
        if components < MIN_CALIBRATION_COMPONENTS
        else "one_class_calibration"
        if happy == 0 or negative == 0
        else None
    )
    if reason:
        return Calibrator(1, 0, reason, 0, None, components, happy, negative, constant)
    x = logit(np.clip(p, EPS, 1 - EPS))
    result = minimize(
        objective,
        np.array([1.0, 0.0]),
        args=(x, y, w),
        jac=True,
        method="L-BFGS-B",
        bounds=[(0, None), (None, None)],
        options={"ftol": 1e-12, "gtol": 1e-8, "maxiter": 500, "maxls": 50},
    )
    if (
        not result.success
        or not np.isfinite(result.x).all()
        or not np.isfinite(result.fun)
        or result.x[0] < 0
    ):
        raise ValueError(f"Calibration optimizer failed: {result.message}")
    return Calibrator(
        float(result.x[0]),
        float(result.x[1]),
        None,
        int(result.nit),
        float(result.fun),
        components,
        happy,
        negative,
        constant,
    )


def apply(calibrator: Calibrator, p: float) -> float:
    """Preserve original probability exactly when calibration falls back."""
    if not np.isfinite(p) or not 0 <= p <= 1:
        raise ValueError("Invalid prediction")
    return (
        p
        if calibrator.reason
        else float(expit(calibrator.slope * logit(np.clip(p, EPS, 1 - EPS)) + calibrator.intercept))
    )


def fit_outer(
    rows: list[base.Observation], groups: dict[int, int], outer: int
) -> tuple[base.BernoulliModel | None, Calibrator | None, dict[str, Any]]:
    """Distinct inner-fit and calibration partitions; no refit after calibration."""
    partitions = {
        name: [r for r in rows if role(groups[r.track_id], outer) == name]
        for name in ("fit", "calibration", "query")
    }
    eligible = {
        name: [r for r in selected if base.vote_reason(r.votes) is None]
        for name, selected in partitions.items()
    }
    counts = {
        name: {
            "nominated_rows": len(partitions[name]),
            "eligible_rows": len(selected),
            "nominated_components": len({groups[r.track_id] for r in partitions[name]}),
            "eligible_components": len({groups[r.track_id] for r in selected}),
        }
        for name, selected in eligible.items()
    }
    model = base.fit(eligible["fit"], groups)
    calibration = None
    if model:
        selected = eligible["calibration"]
        calibration = fit_calibrator(
            np.array([base.predict(model, r)[1] for r in selected]),
            np.array([sum(v == "happy" for v in r.votes or ()) / 3 for r in selected]),
            [groups[r.track_id] for r in selected],
        )
    return model, calibration, counts


def predictions(rows: list[base.Observation]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Retain all nominated rows and explicitly identify missing proper scores."""
    groups = base.components(rows)
    records, models = [], []
    for outer in range(5):
        model, calibrator, counts = fit_outer(rows, groups, outer)
        models.append(
            {
                "fold": outer,
                "roles": counts,
                "vocabulary": list(model.vocabulary) if model else [],
                "prior": model.prior if model else None,
                "theta_happy": model.happy.tolist() if model else None,
                "theta_not_happy": model.not_happy.tolist() if model else None,
                "calibrator": asdict(calibrator) if calibrator else None,
            }
        )
        for row in rows:
            component = groups[row.track_id]
            if base.fold(component) != outer:
                continue
            eligibility = base.vote_reason(row.votes)
            reason = eligibility or ("no_inner_fit" if model is None else None)
            probs = None
            if reason is None and model and calibrator:
                prior, p, _ = base.predict(model, row)
                probs = [p, apply(calibrator, p), prior]
            records.append(
                {
                    "track_id": row.track_id,
                    "component_id": component,
                    "fold": outer,
                    "votes": row.votes,
                    "happy_fraction": sum(v == "happy" for v in row.votes or ()) / 3
                    if eligibility is None
                    else None,
                    "eligibility_reason": eligibility,
                    "prediction_reason": reason,
                    "calibration_reason": calibrator.reason if calibrator else "no_inner_fit",
                    "probabilities": probs,
                }
            )
    return sorted(records, key=lambda r: r["track_id"]), models


def scores(p: np.ndarray, y: float) -> np.ndarray:
    """Columns: individual-vote Brier, fractional log loss, mean-target error."""
    clipped = np.clip(p, EPS, 1 - EPS)
    return np.column_stack(
        (p * p - 2 * p * y + y, -y * np.log(clipped) - (1 - y) * np.log1p(-clipped), (p - y) ** 2)
    )


def summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Proper-score comparisons retain missingness and fixed-bin reliability."""
    eligible = [r for r in records if r["eligibility_reason"] is None]
    covered = [r for r in eligible if r["probabilities"] is not None]
    groups = sorted({r["component_id"] for r in covered})
    sizes = Counter(r["component_id"] for r in covered)
    totals = {g: np.zeros((3, 3)) for g in groups}
    for r in covered:
        p = np.array(r["probabilities"])
        if p.shape != (3,) or not np.isfinite(p).all() or np.any((p < 0) | (p > 1)):
            raise ValueError("Invalid probabilities")
        totals[r["component_id"]] += scores(p, r["happy_fraction"])
    means = np.array([totals[g] / sizes[g] for g in groups])
    methods: dict[str, Any] = {}
    for a, name in enumerate(METHODS):
        metrics = {}
        for j, metric in enumerate(
            ("individual_vote_brier", "fractional_log_loss", "mean_target_squared_error")
        ):
            metrics["component_equal_" + metric] = float(means[:, a, j].mean()) if covered else None
            metrics["track_" + metric] = (
                float(sum(t[a, j] for t in totals.values()) / len(covered)) if covered else None
            )
        bins = []
        for b in range(10):
            selected = [r for r in covered if min(int(r["probabilities"][a] * 10), 9) == b]
            w = np.array([1 / sizes[r["component_id"]] for r in selected])
            bins.append(
                {
                    "bin": b,
                    "rows": len(selected),
                    "components": len({r["component_id"] for r in selected}),
                    "weight": float(w.sum()),
                    "mean_probability": float(
                        w @ [r["probabilities"][a] for r in selected] / w.sum()
                    )
                    if selected
                    else None,
                    "mean_happy_fraction": float(
                        w @ [r["happy_fraction"] for r in selected] / w.sum()
                    )
                    if selected
                    else None,
                }
            )
        methods[name] = {"metrics": metrics, "reliability": bins}
    return {
        "nominated": len(records),
        "eligible": len(eligible),
        "predicted": len(covered),
        "missing_eligible_predictions": len(eligible) - len(covered),
        "eligible_components": len({r["component_id"] for r in eligible}),
        "predicted_components": len(groups),
        "coverage_all_nominated": len(covered) / len(records) if records else None,
        "coverage_eligible": len(covered) / len(eligible) if eligible else None,
        "eligibility_reasons": dict(
            Counter(r["eligibility_reason"] or "eligible" for r in records)
        ),
        "calibration_reasons": dict(Counter(r["calibration_reason"] or "fitted" for r in covered)),
        "methods": methods,
        "calibrated_minus_nb": {
            k: methods[METHODS[1]]["metrics"][k] - v if v is not None else None
            for k, v in methods[METHODS[0]]["metrics"].items()
        },
        "per_component": [
            {
                "component_id": g,
                "rows": sizes[g],
                "vote_brier_delta": float(means[i, 1, 0] - means[i, 0, 0]),
                "log_loss_delta": float(means[i, 1, 1] - means[i, 0, 1]),
            }
            for i, g in enumerate(groups)
        ],
        "vote_noise_track": float(
            np.mean([r["happy_fraction"] * (1 - r["happy_fraction"]) for r in covered])
        )
        if covered
        else None,
        "vote_noise_component": float(
            np.mean(
                [
                    np.mean(
                        [
                            r["happy_fraction"] * (1 - r["happy_fraction"])
                            for r in covered
                            if r["component_id"] == g
                        ]
                    )
                    for g in groups
                ]
            )
        )
        if covered
        else None,
        "conditional_on_prediction_availability": len(covered) != len(eligible),
    }


def code() -> dict[str, str]:
    """Bind new implementation and unchanged imported base implementation."""
    root = Path(__file__).resolve().parents[3]
    return {
        n: base.digest(root / n)
        for n in (
            "src/opennoise/ml/jamendo_calibration.py",
            "scripts/run_jamendo_calibration.py",
            "src/opennoise/ml/jamendo_human_mood.py",
            "scripts/run_jamendo_human_mood.py",
        )
    }


def fresh(path: Path) -> None:
    """Never mutate previous research artifacts or follow output symlinks."""
    if path.exists() or any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError("Fresh nonsymlink output required")
    path.mkdir(parents=True)


def write(path: Path, value: object) -> None:
    """Keep closed research-stage output below20MB."""
    body = (json.dumps(value, indent=2, allow_nan=False) + "\n").encode()
    if (
        any(p.is_symlink() for p in path.parent.iterdir())
        or sum(p.stat().st_size for p in path.parent.iterdir() if p.is_file() and p != path)
        + len(body)
        > MAX_OUTPUT
    ):
        raise ValueError("Output size or symlink guard")
    path.write_bytes(body)


def role_ledger(rows: list[base.Observation]) -> list[dict[str, Any]]:
    """Freeze identity-only per-fold roles without recording votes."""
    groups = base.components(rows)
    return [
        {
            "track_id": r.track_id,
            "component_id": groups[r.track_id],
            "outer_fold": base.fold(groups[r.track_id]),
            "roles": [role(groups[r.track_id], f) for f in range(5)],
        }
        for r in rows
    ]


def freeze(prepared: Path, protocol: Path, output: Path) -> dict[str, Any]:
    """Freeze exact pre-existing custody and label-independent roles before fitting."""
    if base.digest(protocol) != PROTOCOL_SHA256:
        raise ValueError("Protocol differs")
    rows = base._load(prepared, PREPARED_SHA256)  # noqa: SLF001 -- reuse exact original custody guard.
    fresh(output)
    write(output / "roles.json", role_ledger(rows))
    seal = {
        "revision": "jamendo-calibration-seal-v1",
        "prepared": str(prepared.resolve()),
        "prepared_seal_sha256": PREPARED_SHA256,
        "protocol_sha256": PROTOCOL_SHA256,
        "protocol": json.loads(protocol.read_text()),
        "roles_sha256": base.digest(output / "roles.json"),
        "code": code(),
        "versions": base._versions(),  # noqa: SLF001 -- same pinned runtime contract.
        "research_only": True,
        "source_license": "CC-BY-NC-SA-4.0",
    }
    write(output / "seal.json", seal)
    return seal


def frozen_protocol() -> dict[str, Any]:
    """Resolve exact reviewed protocol bytes independently of embedded seal claims."""
    path = (
        Path(__file__).resolve().parents[3]
        / "data/recipes/jamendo-calibration-20261017/protocol.json"
    )
    if base.digest(path) != PROTOCOL_SHA256:
        raise ValueError("Reviewed protocol bytes differ")
    return json.loads(path.read_text())


def load(sealed: Path, pin: str) -> list[base.Observation]:
    """Validate new seal and unchanged original source custody."""
    if (
        base.digest(sealed / "seal.json") != pin
        or {p.name for p in sealed.iterdir()} != {"seal.json", "roles.json"}
        or any(p.is_symlink() for p in (sealed, *sealed.parents, *sealed.iterdir()))
    ):
        raise ValueError("Seal or closed inventory differs")
    seal = json.loads((sealed / "seal.json").read_text())
    if (
        seal["revision"] != "jamendo-calibration-seal-v1"
        or seal["protocol"] != frozen_protocol()
        or seal["code"] != code()
        or seal["versions"] != base._versions()  # noqa: SLF001 -- same pinned runtime contract.
        or seal["protocol_sha256"] != PROTOCOL_SHA256
        or seal["prepared_seal_sha256"] != PREPARED_SHA256
        or seal["research_only"] is not True
        or seal["source_license"] != "CC-BY-NC-SA-4.0"
        or base.digest(sealed / "roles.json") != seal["roles_sha256"]
    ):
        raise ValueError("Source, versions, roles or research scope differs")
    rows = base._load(Path(seal["prepared"]), PREPARED_SHA256)  # noqa: SLF001 -- original custody.
    if role_ledger(rows) != json.loads((sealed / "roles.json").read_text()):
        raise ValueError("Role ledger differs")
    return rows


def compute(rows: list[base.Observation]) -> dict[str, Any]:
    """Compute fixed predictions and descriptive evaluation."""
    records, models = predictions(rows)
    return {
        "predictions.json": records,
        "models.json": models,
        "evaluation.json": {
            "pooled": summary(records),
            "folds": {str(f): summary([r for r in records if r["fold"] == f]) for f in range(5)},
            "research_only": True,
            "musical_quality_validated": False,
            "outer_folds_previously_inspected": True,
        },
    }


def evaluate(sealed: Path, pin: str, output: Path) -> dict[str, Any]:
    """Write fresh sealed local research results."""
    started = time.monotonic()
    rows = load(sealed, pin)
    artifacts = compute(rows)
    fresh(output)
    for name, value in artifacts.items():
        write(output / name, value)
    receipt = {
        "seal_sha256": pin,
        "research_only": True,
        "source_license": "CC-BY-NC-SA-4.0",
        "attribution": ATTRIBUTION,
        "elapsed_seconds": time.monotonic() - started,
        "peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
        "files": {
            n: {"sha256": base.digest(output / n), "bytes": (output / n).stat().st_size}
            for n in artifacts
        },
    }
    write(output / "receipt.json", receipt)
    return receipt


def replay(sealed: Path, pin: str, output: Path) -> None:
    """Recompute every numeric artifact and reject custody drift."""
    if any(p.is_symlink() for p in (output, *output.parents, *output.iterdir())):
        raise ValueError("Symlink result path")
    if sum(p.stat().st_size for p in output.iterdir() if p.is_file()) > MAX_OUTPUT:
        raise ValueError("Combined result byte budget exceeded")
    receipt = json.loads((output / "receipt.json").read_text())
    expected = {"predictions.json", "models.json", "evaluation.json"}
    if (
        set(receipt)
        != {
            "seal_sha256",
            "research_only",
            "source_license",
            "attribution",
            "elapsed_seconds",
            "peak_rss_bytes",
            "files",
        }
        or receipt["attribution"] != ATTRIBUTION
        or receipt["seal_sha256"] != pin
        or receipt["research_only"] is not True
        or receipt["source_license"] != "CC-BY-NC-SA-4.0"
        or set(receipt["files"]) != expected
        or {p.name for p in output.iterdir()} != expected | {"receipt.json"}
        or any(p.is_symlink() for p in (output, *output.iterdir()))
    ):
        raise ValueError("Result custody differs")
    for name, binding in receipt["files"].items():
        if (
            base.digest(output / name) != binding["sha256"]
            or (output / name).stat().st_size != binding["bytes"]
        ):
            raise ValueError("Result bytes differ")
    for name, value in compute(load(sealed, pin)).items():
        if json.loads((output / name).read_text()) != json.loads(json.dumps(value)):
            raise ValueError(f"Numerical replay differs: {name}")
