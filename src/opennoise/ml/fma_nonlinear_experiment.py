"""Sealed factorial feature-bank experiment on already examined development data."""

import hashlib
import json
import platform
import resource
import time
from dataclasses import asdict
from importlib.metadata import version
from pathlib import Path
from typing import Any

import numpy as np
import zstandard

from opennoise.ingest.fma_features import SELECTED_COLUMNS
from opennoise.ml import fma_component_balanced as balanced
from opennoise.ml import fma_component_balanced_metrics as metrics
from opennoise.ml import fma_component_embedding as prior
from opennoise.ml.fma_fixed_nonlinear import FixedEncoder, fit_encoder, transform

RARE_SUPPORT = 100
ARMS = ("linear44", "rff44", "linear518", "rff518")
PROTOCOL_SHA256 = "35afae57b9aab5eda475bb80c369fdb0de8ec3df0598d10be3dbd7e5a4977a5a"


def _write(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def _code() -> dict[str, str]:
    root = Path(__file__).resolve().parents[3]
    names = (
        "src/opennoise/ml/fma_fixed_nonlinear.py",
        "src/opennoise/ml/fma_nonlinear_experiment.py",
        "src/opennoise/ml/fma_component_embedding.py",
        "src/opennoise/ml/fma_component_balanced.py",
        "src/opennoise/ml/fma_component_balanced_metrics.py",
        "src/opennoise/ml/fma_acoustic_baseline.py",
        "src/opennoise/ml/fma_split_audit.py",
        "src/opennoise/ingest/fma_native_bank.py",
        "scripts/run_fma_fixed_nonlinear.py",
    )
    return {name: balanced.digest(root / name) for name in names}


def _versions() -> dict[str, str]:
    return {
        "python": platform.python_version(),
        **{n: version(n) for n in ("numpy", "scipy", "zstandard")},
    }


def freeze(protocol: Path, source: Path, bank: Path, output: Path) -> None:
    """Bind approved design, numeric source identities, code and environment before fits."""
    from opennoise.ingest.fma_native_bank import verify_native_bank  # noqa: PLC0415

    if output.exists() or balanced.digest(protocol) != PROTOCOL_SHA256:
        raise ValueError("Fresh seal and exact reviewed protocol required")
    balanced.load_corpus({"source": str(source)})
    verify_native_bank(bank)
    _write(
        output,
        {
            "revision": "fma-fixed-factorial-v1",
            "protocol": json.loads(protocol.read_text()),
            "protocol_sha256": PROTOCOL_SHA256,
            "source": str(source.resolve()),
            "bank": str(bank.resolve()),
            "bank_receipt_sha256": balanced.digest(bank / "projection-receipt.json"),
            "code": _code(),
            "versions": _versions(),
        },
    )


def verify_seal(path: Path) -> dict[str, Any]:
    """Reject changed protocol, implementation, or numerical environment."""
    seal = json.loads(path.read_text())
    if (
        seal.get("revision") != "fma-fixed-factorial-v1"
        or seal["code"] != _code()
        or seal["versions"] != _versions()
        or seal["protocol_sha256"] != PROTOCOL_SHA256
        or hashlib.sha256((json.dumps(seal["protocol"], indent=2) + "\n").encode()).hexdigest()
        != PROTOCOL_SHA256
    ):
        raise ValueError("Execution seal differs")
    return seal


def load_inputs(seal: Path) -> tuple[balanced.Corpus, np.ndarray]:
    """Verify both banks, preserve original component/row/label identities, align by ID."""
    from opennoise.ingest.fma_native_bank import verify_native_bank  # noqa: PLC0415

    bound = verify_seal(seal)
    data = balanced.load_corpus(bound)
    bank = Path(bound["bank"])
    if balanced.digest(bank / "projection-receipt.json") != bound["bank_receipt_sha256"]:
        raise ValueError("Feature bank receipt changed")
    bank_receipt = verify_native_bank(bank)
    ids = np.fromfile(bank / "track_ids.uint32", dtype="<u4")
    original_ids = np.fromfile(Path(bound["source"]) / "track_ids.uint32", dtype="<u4")
    if not np.array_equal(ids, original_ids) or len(np.unique(ids)) != len(ids) or (ids == 0).any():
        raise ValueError("Native bank identity roster differs")
    positions = [bank_receipt["columns"].index(list(column)) for column in SELECTED_COLUMNS]
    original = np.memmap(
        Path(bound["source"]) / "features.float32", dtype="<f4", mode="r", shape=(len(ids), 44)
    )
    raw = np.memmap(bank / "features.float32", dtype="<f4", mode="r", shape=(len(ids), 518))
    for start in range(0, len(ids), 512):
        if not np.array_equal(
            raw[start : start + 512, positions], original[start : start + 512], equal_nan=True
        ):
            raise ValueError("Native bank44-column parity differs")
    lookup = {int(identity): i for i, identity in enumerate(ids)}
    full = np.full((len(data.ids), 518), np.nan, dtype=np.float32)
    for start in range(0, len(full), 512):
        rows = np.arange(start, min(start + 512, len(full)))
        present = np.array([int(data.ids[i]) in lookup for i in rows])
        target = rows[present]
        full[target] = raw[[lookup[int(data.ids[i])] for i in target]]
    return data, full


def _folder(output: Path, fold: int, arm: str, stage: str) -> Path:
    if fold not in range(5) or arm not in ARMS:
        raise ValueError("Unknown arm or fold")
    path = output / f"fold-{fold}" / arm / stage
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError("Symlink output")
    return path


def _receipt(folder: Path, seal: Path, started: float, extra: dict[str, Any]) -> None:
    extra.update(
        seal_sha256=balanced.digest(seal),
        elapsed_seconds=time.monotonic() - started,
        peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
        files={
            p.name: {"bytes": p.stat().st_size, "sha256": balanced.digest(p)}
            for p in folder.iterdir()
            if p.is_file()
        },
    )
    pending = folder / "receipt.pending"
    _write(pending, extra)
    balanced._budget(folder.parents[2])  # noqa: SLF001 - unchanged inherited100MBguard.
    pending.replace(folder / "receipt.json")


def _verify_stage(folder: Path, seal: Path, expected: set[str]) -> dict[str, Any]:
    _verify_tree(folder.parents[2])
    receipt = json.loads((folder / "receipt.json").read_text())
    if (
        receipt["seal_sha256"] != balanced.digest(seal)
        or set(receipt["files"]) != expected
        or {p.name for p in folder.iterdir()} != expected | {"receipt.json"}
    ):
        raise ValueError("Stage inventory or seal differs")
    for name, pin in receipt["files"].items():
        p = folder / name
        if (
            p.is_symlink()
            or p.stat().st_size != pin["bytes"]
            or balanced.digest(p) != pin["sha256"]
        ):
            raise ValueError("Stage file changed")
    return receipt


def fit_stage(seal: Path, output: Path, fold: int, arm: str) -> None:
    """Fit one arm on matched complete44+518 training rows with fixed resource guards."""
    started = time.monotonic()
    folder = _folder(output, fold, arm, "fit")
    if folder.exists():
        raise ValueError("Fresh fit stage required")
    _verify_tree(output)
    data, full = load_inputs(seal)
    training = data.inner_folds != fold
    for start in range(0, len(training), 512):
        sl = slice(start, start + 512)
        training[sl] &= np.isfinite(full[sl]).all(axis=1) & np.isfinite(data.features[sl]).all(
            axis=1
        )
    features = full if arm.endswith("518") else data.features
    model = fit_encoder(
        features, data.targets, training, data.groups, nonlinear=arm.startswith("rff")
    )
    folder.mkdir(parents=True, exist_ok=False)
    np.savez(folder / "model.npz", **asdict(model))
    _write(
        folder / "training.json",
        {"ids": data.ids[training].tolist(), "components": len(np.unique(data.groups[training]))},
    )
    _receipt(
        folder,
        seal,
        started,
        {"stage": "fit", "arm": arm, "fold": fold, "training_rows": int(training.sum())},
    )


def _load_models(seal: Path, output: Path, fold: int) -> dict[str, FixedEncoder]:
    models = {}
    training_pin = None
    for arm in ARMS:
        folder = _folder(output, fold, arm, "fit")
        receipt = _verify_stage(folder, seal, {"model.npz", "training.json"})
        if receipt["arm"] != arm or receipt["fold"] != fold:
            raise ValueError("Fit identity differs")
        pin = receipt["files"]["training.json"]["sha256"]
        if training_pin is not None and pin != training_pin:
            raise ValueError("Matched fit cohorts differ")
        training_pin = pin
        with np.load(folder / "model.npz", allow_pickle=False) as saved:
            models[arm] = FixedEncoder(**{key: saved[key] for key in saved.files})
    return models


def score_stage(seal: Path, output: Path, fold: int, arm: str) -> None:
    """Score a complete heldout fold using shared candidates and source-positive votes."""
    started = time.monotonic()
    folder = _folder(output, fold, arm, "score")
    if folder.exists():
        raise ValueError("Fresh score stage required")
    _verify_tree(output)
    data, full = load_inputs(seal)
    models = _load_models(seal, output, fold)
    nominated = prior.nominate(data, data.inner_folds != fold)
    intrinsic, candidate_vectors = {}, {}
    joint = np.ones(len(nominated), dtype=bool)
    for name, model in models.items():
        features = full if name.endswith("518") else data.features
        vectors, ok = transform(model, features[nominated])
        intrinsic[name] = data.ids[nominated[ok]].tolist()
        candidate_vectors[name] = vectors
        joint &= ok
    candidates = nominated[joint]
    vectors = candidate_vectors[arm][joint]
    union = np.asarray(data.targets[candidates].sum(axis=0)).ravel() > 0
    queries = np.flatnonzero(data.inner_folds == fold)
    components, inverse = np.unique(data.groups[queries], return_inverse=True)
    stats = np.zeros((len(components), 11))
    common_stats = np.zeros_like(stats)
    label_counts = np.zeros((len(data.labels), 2), dtype=np.int64)
    features = full if arm.endswith("518") else data.features
    folder.mkdir(parents=True, exist_ok=False)
    with zstandard.open(folder / "ranks.jsonl.zst", "wt") as stream:
        for start in range(0, len(queries), 256):
            rows = queries[start : start + 256]
            vv, ok = transform(models[arm], features[rows])
            common = np.ones(len(rows), dtype=bool)
            for name, model in models.items():
                bank = full if name.endswith("518") else data.features
                _, supported = transform(model, bank[rows])
                common &= supported
            scores = vv @ vectors.T
            nearest = np.argsort(-scores, axis=1, kind="stable")[:, :10]
            for j, row in enumerate(rows):
                positives = data.targets.indices[
                    data.targets.indptr[row] : data.targets.indptr[row + 1]
                ].tolist()
                neighbors = candidates[nearest[j]].tolist() if ok[j] else []
                ranking = prior.transfer(neighbors, data.targets)
                values = balanced.query_stats(positives, ranking, union)
                stats[inverse[start + j]] += values
                if common[j]:
                    common_stats[inverse[start + j]] += values
                for label in positives:
                    label_counts[label] += [label in ranking[:10], 1]
                stream.write(
                    json.dumps(
                        {
                            "track_id": int(data.ids[row]),
                            "component_id": int(data.groups[row]),
                            "targets": positives,
                            "ranking": ranking,
                            "neighbor_ids": data.ids[neighbors].tolist(),
                            "cosine_distances": (1 - scores[j, nearest[j]]).tolist()
                            if ok[j]
                            else [],
                            "descriptor_available": bool(ok[j]),
                            "common_query": bool(common[j]),
                        },
                        separators=(",", ":"),
                    )
                    + "\n"
                )
    np.savez(
        folder / "statistics.npz",
        components=components,
        values=stats,
        common_values=common_stats,
        label_counts=label_counts,
    )
    fit_support = np.asarray(data.targets[data.inner_folds != fold].sum(axis=0)).ravel()
    _write(
        folder / "candidates.json",
        {
            "nominated_ids": data.ids[nominated].tolist(),
            "intrinsic_ids": intrinsic,
            "common_ids": data.ids[candidates].tolist(),
            "label_union_indices": np.flatnonzero(union).tolist(),
            "fit_label_support": fit_support.tolist(),
            "labels": data.labels,
        },
    )
    _receipt(
        folder, seal, started, {"stage": "score", "arm": arm, "fold": fold, "queries": len(queries)}
    )


def summarize(seal: Path, output: Path) -> None:  # noqa: C901 - closed four-arm summary.
    """Verify all twenty scored stages and preserve component and label denominators."""
    started = time.monotonic()
    data, _full = load_inputs(seal)
    directory = output / "summary"
    if directory.exists():
        raise ValueError("Fresh summary required")
    report = {"interpretation": verify_seal(seal)["protocol"]["interpretation"], "arms": {}}
    for arm in ARMS:
        values, common, groups, labels, rare = [], [], [], [], []
        for fold in range(5):
            folder = _folder(output, fold, arm, "score")
            receipt = _verify_stage(
                folder, seal, {"statistics.npz", "candidates.json", "ranks.jsonl.zst"}
            )
            if receipt["arm"] != arm or receipt["fold"] != fold:
                raise ValueError("Score identity differs")
            with np.load(folder / "statistics.npz", allow_pickle=False) as saved:
                expected, counts = np.unique(
                    data.groups[data.inner_folds == fold], return_counts=True
                )
                if (
                    not np.array_equal(saved["components"], expected)
                    or saved["values"].shape != (len(expected), 11)
                    or not np.array_equal(saved["values"][:, 0], counts)
                ):
                    raise ValueError("Heldout component or query roster differs")
                query_rows = np.flatnonzero(data.inner_folds == fold)
                pos = np.asarray(data.targets[query_rows].sum(axis=1)).ravel()
                component_index = np.searchsorted(expected, data.groups[query_rows])
                if not np.array_equal(
                    saved["values"][:, 1],
                    np.bincount(component_index, weights=pos > 0, minlength=len(expected)),
                ) or not np.array_equal(
                    saved["values"][:, 2],
                    np.bincount(component_index, weights=pos, minlength=len(expected)),
                ):
                    raise ValueError("Heldout annotation denominators differ")
                metrics.validate_stats(np.repeat(saved["values"][:, None, :], 3, axis=1))
                metrics.validate_stats(np.repeat(saved["common_values"][:, None, :], 3, axis=1))
                values.append(saved["values"])
                common.append(saved["common_values"])
                groups.extend(saved["components"].tolist())
                labels.append(saved["label_counts"])
                support = np.array(
                    json.loads((folder / "candidates.json").read_text())["fit_label_support"]
                )
                rare.append(
                    np.where(
                        ((support > 0) & (support <= RARE_SUPPORT))[:, None],
                        saved["label_counts"],
                        0,
                    )
                )
        ids, stats, shared = np.array(groups), np.concatenate(values), np.concatenate(common)
        if len(np.unique(ids)) != len(ids):
            raise ValueError("Component crosses heldout folds")
        label_total, rare_total = np.sum(labels, axis=0), np.sum(rare, axis=0)

        def measured(selected: np.ndarray) -> dict[str, Any]:
            rates = metrics.metrics(selected[:, None, :])[0]
            return {
                "metrics": {
                    name: metrics.nullable(v)
                    for name, v in zip(metrics.METRICS, rates, strict=True)
                },
                "totals": dict(
                    zip(balanced.STAT_NAMES, selected.sum(axis=0).tolist(), strict=True)
                ),
            }

        def macro(counts: np.ndarray) -> dict[str, Any]:
            eligible = counts[:, 1] > 0
            return {
                "recall10": float(np.mean(counts[eligible, 0] / counts[eligible, 1]))
                if eligible.any()
                else None,
                "labels": int(eligible.sum()),
                "definition": "heldout positives; rare=1..100 original innerfit positive rows",
            }

        report["arms"][arm] = {
            "all": measured(stats),
            "common_queries": measured(shared),
            "giant_component": measured(stats[ids == prior.GIANT_COMPONENT]),
            "other_components": measured(stats[ids != prior.GIANT_COMPONENT]),
            "macro": macro(label_total),
            "rare_macro": macro(rare_total),
        }
    report["comparisons"] = {}
    for left, right in (
        ("rff44", "linear44"),
        ("rff518", "linear518"),
        ("linear518", "linear44"),
        ("rff518", "rff44"),
    ):
        a, b = report["arms"][left]["all"]["metrics"], report["arms"][right]["all"]["metrics"]
        report["comparisons"][left + "_minus_" + right] = {
            name: a[name] - b[name] if a[name] is not None and b[name] is not None else None
            for name in metrics.METRICS
        }
    _verify_tree(output)
    directory.mkdir()
    _write(directory / "results.json", report)
    _write(
        directory / "receipt.pending",
        {
            "seal_sha256": balanced.digest(seal),
            "stage": "summary",
            "elapsed_seconds": time.monotonic() - started,
            "peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
            "files": {
                "results.json": {
                    "bytes": (directory / "results.json").stat().st_size,
                    "sha256": balanced.digest(directory / "results.json"),
                }
            },
        },
    )
    balanced._budget(output)  # noqa: SLF001 - unchanged guard.
    (directory / "receipt.pending").replace(directory / "receipt.json")


def verify_stage(output: Path, seal: Path, fold: int, arm: str, stage: str) -> dict[str, Any]:
    """Verify a closed completed stage before an orchestrator skips it on resume."""
    verify_seal(seal)
    expected = {
        "fit": {"model.npz", "training.json"},
        "score": {"statistics.npz", "candidates.json", "ranks.jsonl.zst"},
    }
    if stage not in expected:
        raise ValueError("Unknown stage")
    receipt = _verify_stage(_folder(output, fold, arm, stage), seal, expected[stage])
    if receipt["stage"] != stage or receipt["arm"] != arm or receipt["fold"] != fold:
        raise ValueError("Stage identity differs")
    return receipt


def _verify_tree(output: Path) -> None:
    allowed = {"summary", "summary/results.json", "summary/receipt.json"}
    for fold in range(5):
        prefix = f"fold-{fold}"
        allowed.add(prefix)
        for arm in ARMS:
            base = f"{prefix}/{arm}"
            allowed.add(base)
            for stage, names in (
                ("fit", ("model.npz", "training.json", "receipt.json")),
                ("score", ("statistics.npz", "candidates.json", "ranks.jsonl.zst", "receipt.json")),
            ):
                allowed.add(f"{base}/{stage}")
                allowed.update(f"{base}/{stage}/{name}" for name in names)
    if any(p.relative_to(output).as_posix() not in allowed for p in output.rglob("*")):
        raise ValueError("Unexpected experiment output")
    balanced._budget(output)  # noqa: SLF001 - preserve existing budget on resume.
