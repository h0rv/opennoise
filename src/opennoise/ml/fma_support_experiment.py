"""One component-disjoint proper-fit/calibration experiment, with frozen stages."""

import hashlib
import json
import resource
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

import numpy as np
import zstandard

from opennoise.ml import fma_component_balanced as balanced
from opennoise.ml import fma_component_balanced_metrics as metrics
from opennoise.ml import fma_component_embedding as prior
from opennoise.ml import fma_nonlinear_experiment as factorial
from opennoise.ml.fma_fixed_nonlinear import FixedEncoder, fit_encoder
from opennoise.ml.fma_support_calibration import (
    LEVELS,
    calibration_mask,
    component_quantiles,
    descriptor_state,
)

ORIGINAL_LIMIT = 12.0
ARMS = ("linear44", "linear518")
AVAILABILITY = (
    "descriptor_accepted",
    "embedding_accepted",
    "neighbor_queries",
    "ranking_queries",
    "missing_descriptors",
    "outside_threshold",
    "norm_failure",
)
POINTS = ("original12", "q90", "q95", "q99")
PROTOCOL_SHA256 = "8e68db4d9b066af7e47a727d923ffd08603da80aee176c44642ffadf6d69a5d3"
FILES = {
    "fit-linear44": {"model.npz", "fit-ids.json"},
    "fit-linear518": {"model.npz", "fit-ids.json"},
    "calibrate": {"thresholds.json", "calibration.npz", "candidates.json"},
    "score": {"ranks.jsonl.zst", "statistics.npz", "results.json"},
}


def _write(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def _code() -> dict[str, str]:
    root = Path(__file__).resolve().parents[3]
    names = (
        "src/opennoise/ml/fma_support_calibration.py",
        "src/opennoise/ml/fma_support_experiment.py",
        "scripts/run_fma_support_calibration.py",
    )
    return factorial._code() | {n: balanced.digest(root / n) for n in names}  # noqa: SLF001


def freeze(protocol: Path, input_seal: Path, output: Path) -> None:
    """Freeze new protocol and source bindings without reading previous fitted models/outcomes."""
    if output.exists() or balanced.digest(protocol) != PROTOCOL_SHA256:
        raise ValueError("Fresh output and reviewed protocol required")
    factorial.load_inputs(input_seal)
    _write(
        output,
        {
            "revision": "fma-support-calibration-v1",
            "protocol": json.loads(protocol.read_text()),
            "input_seal": str(input_seal.resolve()),
            "input_seal_sha256": balanced.digest(input_seal),
            "code": _code(),
            "versions": factorial._versions(),  # noqa: SLF001
        },
    )


def verify_seal(seal: Path) -> dict[str, Any]:
    """Reject changed source, protocol, code or numerical environment."""
    spec = json.loads(seal.read_text())
    if (
        spec["revision"] != "fma-support-calibration-v1"
        or spec["code"] != _code()
        or spec["versions"] != factorial._versions()  # noqa: SLF001
        or hashlib.sha256((json.dumps(spec["protocol"], indent=2) + "\n").encode()).hexdigest()
        != PROTOCOL_SHA256
        or balanced.digest(Path(spec["input_seal"])) != spec["input_seal_sha256"]
    ):
        raise ValueError("Calibration execution seal differs")
    return spec


def load_inputs(seal: Path) -> tuple[balanced.Corpus, np.ndarray]:
    """Use the unchanged verified original-training corpus and exact native-bank parity."""
    return factorial.load_inputs(Path(verify_seal(seal)["input_seal"]))


def _tree(output: Path) -> None:
    allowed = set(FILES)
    allowed.update(
        f"{stage}/{name}" for stage, files in FILES.items() for name in files | {"receipt.json"}
    )
    if any(p.is_symlink() for p in (output, *output.parents)) or any(
        p.is_symlink() or p.relative_to(output).as_posix() not in allowed for p in output.rglob("*")
    ):
        raise ValueError("Unexpected or symlink experiment output")
    balanced._budget(output)  # noqa: SLF001 - unchanged100MB guard.


def _new(output: Path, stage: str) -> Path:
    _tree(output)
    folder = output / stage
    if folder.exists():
        raise ValueError("Fresh stage required; preserve partial stages")
    folder.mkdir(parents=True)
    return folder


def _complete(folder: Path, seal: Path, started: float) -> None:
    _write(
        folder / "receipt.pending",
        {
            "stage": folder.name,
            "seal_sha256": balanced.digest(seal),
            "elapsed_seconds": time.monotonic() - started,
            "peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
            "files": {
                p.name: {"bytes": p.stat().st_size, "sha256": balanced.digest(p)}
                for p in folder.iterdir()
            },
        },
    )
    balanced._budget(folder.parent)  # noqa: SLF001
    (folder / "receipt.pending").replace(folder / "receipt.json")


def verify_stage(output: Path, seal: Path, stage: str) -> dict[str, Any]:
    """Validate closed output and exact stage bindings; this is custody, not numerical replay."""
    verify_seal(seal)
    _tree(output)
    folder = output / stage
    receipt = json.loads((folder / "receipt.json").read_text())
    if (
        receipt["stage"] != stage
        or receipt["seal_sha256"] != balanced.digest(seal)
        or set(receipt["files"]) != FILES[stage]
        or {p.name for p in folder.iterdir()} != FILES[stage] | {"receipt.json"}
    ):
        raise ValueError("Stage identity or inventory differs")
    for name, pin in receipt["files"].items():
        p = folder / name
        if p.stat().st_size != pin["bytes"] or balanced.digest(p) != pin["sha256"]:
            raise ValueError("Stage file changed")
    return receipt


def fit(seal: Path, output: Path, arm: str) -> None:
    """Fit one matched linear control on proper-fit components only."""
    started = time.monotonic()
    if arm not in ARMS:
        raise ValueError("Unknown arm")
    folder = _new(output, "fit-" + arm)
    data, full = load_inputs(seal)
    training = ~calibration_mask(data.groups)
    for start in range(0, len(training), 512):
        sl = slice(start, start + 512)
        training[sl] &= np.isfinite(full[sl]).all(axis=1) & np.isfinite(data.features[sl]).all(
            axis=1
        )
    model = fit_encoder(
        full if arm == "linear518" else data.features,
        data.targets,
        training,
        data.groups,
        nonlinear=False,
    )
    np.savez(folder / "model.npz", **asdict(model))
    _write(folder / "fit-ids.json", data.ids[training].tolist())
    _complete(folder, seal, started)


def _models(output: Path, seal: Path) -> dict[str, FixedEncoder]:
    models: dict[str, FixedEncoder] = {}
    pins = []
    for arm in ARMS:
        receipt = verify_stage(output, seal, "fit-" + arm)
        pins.append(receipt["files"]["fit-ids.json"]["sha256"])
        with np.load(output / ("fit-" + arm) / "model.npz", allow_pickle=False) as saved:
            models[arm] = FixedEncoder(**{key: saved[key] for key in saved.files})
    if len(set(pins)) != 1:
        raise ValueError("Matched proper-fit cohorts differ")
    return models


def calibrate(seal: Path, output: Path) -> None:
    """Freeze component-weighted descriptor quantiles without consulting calibration labels."""
    started = time.monotonic()
    models = _models(output, seal)
    data, full = load_inputs(seal)
    mask = calibration_mask(data.groups)
    if not mask.any() or mask.all():
        raise ValueError("Empty proper-fit or calibration partition")
    rows = np.flatnonzero(mask)
    scores = np.empty((len(rows), len(ARMS)))
    for start in range(0, len(rows), 256):
        ix = rows[start : start + 256]
        for a, arm in enumerate(ARMS):
            scores[start : start + len(ix), a] = descriptor_state(
                models[arm], (full if a else data.features)[ix]
            )[0]
    common = np.isfinite(scores).all(axis=1)
    thresholds, weights, report = [], np.zeros(0), {}
    for a, arm in enumerate(ARMS):
        quantiles, weights = component_quantiles(scores[common, a], data.groups[rows[common]])
        thresholds.append([ORIGINAL_LIMIT, *quantiles.tolist()])
        report[arm] = {
            "thresholds": dict(zip(POINTS, thresholds[-1], strict=True)),
            "empirical_weighted_acceptance": {
                p: float(weights @ (scores[common, a] <= t))
                for p, t in zip(POINTS, thresholds[-1], strict=True)
            },
        }
    nominated = prior.nominate(data, ~mask)
    joint = np.ones(len(nominated), dtype=bool)
    for a, arm in enumerate(ARMS):
        ss, _, ok = descriptor_state(models[arm], (full if a else data.features)[nominated])
        joint &= ok & (ss <= ORIGINAL_LIMIT)
    folder = _new(output, "calibrate")
    np.savez(
        folder / "calibration.npz",
        ids=data.ids[rows],
        groups=data.groups[rows],
        scores=scores,
        common_finite=common,
        weights=weights,
        thresholds=np.array(thresholds),
    )
    _write(
        folder / "thresholds.json",
        {
            "arms": report,
            "calibration_rows": len(rows),
            "calibration_components": len(np.unique(data.groups[rows])),
            "properfit_components": len(np.unique(data.groups[~mask])),
            "properfit_roster_rows": int((~mask).sum()),
            "properfit_finite_rows": len(
                json.loads((output / "fit-linear44/fit-ids.json").read_text())
            ),
            "calibration_components_without_common_finite_rows": sorted(
                set(data.groups[rows].tolist()) - set(data.groups[rows[common]].tolist())
            ),
            "giant_component_role": "calibration"
            if calibration_mask(np.array([prior.GIANT_COMPONENT]))[0]
            else "proper_fit",
            "common_finite_rows": int(common.sum()),
            "common_finite_components": len(np.unique(data.groups[rows[common]])),
            "nominal_levels": LEVELS,
            "interpretation": (
                "Empirical descriptor acceptance on common-finite calibration rows; "
                "not future or ranking coverage guarantee."
            ),
        },
    )
    _write(
        folder / "candidates.json",
        {
            "nominated_ids": data.ids[nominated].tolist(),
            "common_ids": data.ids[nominated[joint]].tolist(),
        },
    )
    _complete(folder, seal, started)


def score(seal: Path, output: Path) -> None:  # noqa: C901, PLR0915 - fixed two-arm/four-mask stream.
    """Rank calibration rows once per arm, then apply frozen gates without point selection."""
    started = time.monotonic()
    models = _models(output, seal)
    verify_stage(output, seal, "calibrate")
    data, full = load_inputs(seal)
    rows = np.flatnonzero(calibration_mask(data.groups))
    with np.load(output / "calibrate/calibration.npz", allow_pickle=False) as saved:
        thresholds = saved["thresholds"]
        if not np.array_equal(saved["ids"], data.ids[rows]):
            raise ValueError("Calibration roster changed")
    ids = json.loads((output / "calibrate/candidates.json").read_text())["common_ids"]
    lookup = {int(t): i for i, t in enumerate(data.ids)}
    candidates = np.array([lookup[t] for t in ids], dtype=int)
    vectors = {
        arm: descriptor_state(models[arm], (full if a else data.features)[candidates])[1]
        for a, arm in enumerate(ARMS)
    }
    union = np.asarray(data.targets[candidates].sum(axis=0)).ravel() > 0
    groups, inverse = np.unique(data.groups[rows], return_inverse=True)
    values = np.zeros((len(groups), 2, 4, 11))
    accepted = np.zeros_like(values)
    common_values = np.zeros_like(values)
    availability = np.zeros((*values.shape[:3], len(AVAILABILITY)))
    folder = _new(output, "score")
    with zstandard.open(folder / "ranks.jsonl.zst", "wt") as stream:
        for start in range(0, len(rows), 256):
            batch = rows[start : start + 256]
            states = {
                arm: descriptor_state(models[arm], (full if a else data.features)[batch])
                for a, arm in enumerate(ARMS)
            }
            nearest = {
                arm: np.argsort(-(states[arm][1] @ vectors[arm].T), axis=1, kind="stable")[:, :10]
                for arm in ARMS
            }
            for j, row in enumerate(batch):
                positives = data.targets.indices[
                    data.targets.indptr[row] : data.targets.indptr[row + 1]
                ].tolist()
                record = {
                    "track_id": int(data.ids[row]),
                    "component_id": int(data.groups[row]),
                    "targets": positives,
                    "arms": {},
                }
                common_masks = np.ones(len(POINTS), dtype=bool)
                for a, arm in enumerate(ARMS):
                    common_masks &= states[arm][2][j] & (states[arm][0][j] <= thresholds[a])
                for a, arm in enumerate(ARMS):
                    scores, _, valid = states[arm]
                    neighbors = candidates[nearest[arm][j]].tolist() if valid[j] else []
                    ranking = prior.transfer(neighbors, data.targets)
                    masks = valid[j] & (scores[j] <= thresholds[a])
                    for point, okay in enumerate(masks):
                        stats = balanced.query_stats(positives, ranking if okay else [], union)
                        availability[inverse[start + j], a, point] += [
                            np.isfinite(scores[j]) and scores[j] <= thresholds[a, point],
                            okay,
                            okay and bool(neighbors),
                            okay and bool(ranking),
                            not np.isfinite(scores[j]),
                            np.isfinite(scores[j]) and scores[j] > thresholds[a, point],
                            np.isfinite(scores[j])
                            and scores[j] <= thresholds[a, point]
                            and not valid[j],
                        ]
                        values[inverse[start + j], a, point] += stats
                        if okay:
                            accepted[inverse[start + j], a, point] += stats
                        if common_masks[point]:
                            common_values[inverse[start + j], a, point] += stats
                    record["arms"][arm] = {
                        "ranking": ranking,
                        "neighbor_ids": data.ids[neighbors].tolist(),
                        "score": float(scores[j]) if np.isfinite(scores[j]) else None,
                        "embedding_valid": bool(valid[j]),
                        "accepted": masks.tolist(),
                    }
                stream.write(json.dumps(record, separators=(",", ":")) + "\n")
    np.savez(
        folder / "statistics.npz",
        components=groups,
        values=values,
        accepted_values=accepted,
        common_values=common_values,
        availability=availability,
    )
    result: dict[str, Any] = {
        "interpretation": (
            "Calibration-label metrics are descriptive on already examined training data; "
            "no independent evaluation or point selection."
        ),
        "arms": {},
    }
    for a, arm in enumerate(ARMS):
        result["arms"][arm] = {}
        for p, point in enumerate(POINTS):
            counts = availability[:, a, p]
            denominators = values[:, a, p, 0]
            result["arms"][arm][point] = {
                "availability": {
                    "queries": int(denominators.sum()),
                    "counts": dict(zip(AVAILABILITY, counts.sum(axis=0).tolist(), strict=True)),
                    "component_mean_rates": dict(
                        zip(
                            AVAILABILITY,
                            np.mean(counts / denominators[:, None], axis=0).tolist(),
                            strict=True,
                        )
                    ),
                }
            }
            for name, stats in (
                ("all_calibration", values[:, a, p]),
                ("accepted_only", accepted[:, a, p]),
                ("common_accepted", common_values[:, a, p]),
            ):
                measured = metrics.metrics(stats[:, None, :])[0]
                result["arms"][arm][point][name] = {
                    "metrics": {
                        k: metrics.nullable(v)
                        for k, v in zip(metrics.METRICS, measured, strict=True)
                    },
                    "totals": dict(
                        zip(balanced.STAT_NAMES, stats.sum(axis=0).tolist(), strict=True)
                    ),
                }
    _write(folder / "results.json", result)
    _complete(folder, seal, started)
