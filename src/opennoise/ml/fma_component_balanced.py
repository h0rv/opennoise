"""Prespecified component-balanced Gaussian; original-training CV only."""

import hashlib
import json
import platform
import resource
import time
from dataclasses import asdict, dataclass
from importlib.metadata import version
from pathlib import Path
from typing import Any, cast

import numpy as np
import zstandard
from scipy import sparse

from opennoise.ml import fma_acoustic_baseline as baseline
from opennoise.ml.fma_acoustic_baseline import (
    MIN_LABEL_SUPPORT,
    MIN_VARIANCE,
    VARIANCE_SHRINKAGE,
    PositiveGaussian,
)
from opennoise.ml.fma_component_balanced_metrics import summarize

FOLD_SCOPE = "fma-component-balanced-cv-v1"
FOLD_COUNT = 5


def component_fold(component_id: int) -> int:
    """Assign whole native identity components without consulting labels or features."""
    if type(component_id) is not int or component_id <= 0:
        raise ValueError("Expected positive native component ID")
    digest = hashlib.sha256(f"{FOLD_SCOPE}\0{component_id}".encode()).digest()
    return int.from_bytes(digest, "big") % FOLD_COUNT


def equal_component_weights(components: np.ndarray) -> np.ndarray:
    """Each represented component contributes unit total mass."""
    _, inverse, counts = np.unique(components, return_inverse=True, return_counts=True)
    return 1.0 / counts[inverse]


def fit_component_gaussian(
    features: np.ndarray,
    targets: sparse.csr_matrix,
    training: np.ndarray,
    components: np.ndarray,
) -> PositiveGaussian:
    """Equal finite components globally; equal positive components within each label."""
    if (
        features.ndim != 2  # noqa: PLR2004 - feature matrix dimensions.
        or training.dtype != np.bool_
        or training.shape != (len(features),)
        or components.shape != training.shape
        or targets.shape[0] != len(features)
        or (components[training] <= 0).any()
    ):
        raise ValueError("Unaligned component training inputs")
    targets = cast("sparse.csr_matrix", targets.tocsr(copy=True))
    targets.sum_duplicates()
    targets.eliminate_zeros()
    if not np.isin(targets.data, [1]).all():
        raise ValueError("Targets must be binary source-positive indicators")
    finite = training & np.isfinite(features).all(axis=1)
    x = np.asarray(features[finite], dtype=np.float64)
    if len(x) < MIN_LABEL_SUPPORT:
        raise ValueError("Insufficient finite training rows")
    groups = components[finite]
    weights = equal_component_weights(groups)
    center = np.average(x, axis=0, weights=weights)
    scale = np.sqrt(np.average((x - center) ** 2, axis=0, weights=weights))
    if not np.isfinite(center).all() or not np.isfinite(scale).all():
        raise ValueError("Nonfinite training moments")
    active = scale > 0
    if not active.any():
        raise ValueError("No varying training features")
    z = (x[:, active] - center[active]) / scale[active]
    labels = targets[finite].tocsc()
    support = np.asarray(labels.sum(axis=0)).ravel()
    means = np.zeros((targets.shape[1], int(active.sum())))
    variances = np.zeros_like(means)
    for label in range(targets.shape[1]):
        rows = labels.indices[labels.indptr[label] : labels.indptr[label + 1]]
        if not len(rows):
            continue
        positive_weights = equal_component_weights(groups[rows])
        means[label] = np.average(z[rows], axis=0, weights=positive_weights)
        variances[label] = np.average(
            (z[rows] - means[label]) ** 2, axis=0, weights=positive_weights
        )
    variances = np.maximum((1 - VARIANCE_SHRINKAGE) * variances + VARIANCE_SHRINKAGE, MIN_VARIANCE)
    prior_weights = equal_component_weights(components[training])
    prior = (np.asarray(targets[training].T @ prior_weights).ravel() + 0.5) / (
        prior_weights.sum() + 1
    )
    active_labels = support >= MIN_LABEL_SUPPORT
    intercept = -0.5 * np.sum(means * means / variances + np.log(variances), axis=1) + np.log(prior)
    intercept[~active_labels] = -np.inf
    return PositiveGaussian(
        center,
        scale,
        active,
        -0.5 / variances,
        means / variances,
        intercept,
        active_labels,
        support,
        int(finite.sum()),
    )


PROTOCOL_SHA256 = "a5f9683bfade167b5d89eb87e9c7e1a91db5aba788c39760be54873207a669e6"
MANIFEST_SHA256 = "4344e609efd7442bf2c598fefb9d1f5abb08884b59f922a53a05643c60d0a323"
MAX_OUTPUT_BYTES = 100000000
ARMS = ("recording", "balanced", "popularity")
STAT_NAMES = (
    "queries",
    "labeled_queries",
    "positives",
    "hits10",
    "rr_sum",
    "positive_rr_sum",
    "covered_queries",
    "covered_positives",
    "active_label_positives",
    "recoverable_positives",
    "covered_labeled_queries",
)


def digest(path: Path) -> str:
    """Hash exact artifact bytes."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _rows(path: Path) -> list[dict[str, Any]]:
    with zstandard.open(path, "rt") as stream:
        return [json.loads(line) for line in stream]


def _json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def _code_paths() -> dict[str, Path]:
    root = Path(__file__).resolve().parents[3]
    return {
        name: root / name
        for name in (
            "src/opennoise/ml/fma_component_balanced.py",
            "src/opennoise/ml/fma_acoustic_baseline.py",
            "src/opennoise/ml/fma_split_audit.py",
            "scripts/run_fma_component_balanced.py",
            "src/opennoise/ml/fma_component_balanced_metrics.py",
        )
    }


def _versions() -> dict[str, str]:
    return {
        "python": platform.python_version(),
        **{name: version(name) for name in ("numpy", "scipy", "zstandard")},
    }


def freeze(protocol: Path, source: Path, output: Path) -> dict[str, Any]:
    """Seal exact approved design, numeric input root and code before model outcomes."""
    if output.exists() or digest(protocol) != PROTOCOL_SHA256:
        raise ValueError("Fresh seal path and exact approved protocol required")
    if digest(source / "MANIFEST.json") != MANIFEST_SHA256:
        raise ValueError("Numeric source manifest differs")
    seal = {
        "revision": "fma-component-balanced-execution-v1",
        "protocol": json.loads(protocol.read_text()),
        "protocol_sha256": PROTOCOL_SHA256,
        "source": str(source.resolve()),
        "versions": _versions(),
        "code": {name: digest(path) for name, path in _code_paths().items()},
    }
    _json(output, seal)
    return seal


def verify_seal(path: Path) -> dict[str, Any]:
    """Reject changes to approved policy or sealed implementation."""
    spec = json.loads(path.read_text())
    protocol_bytes = (json.dumps(spec["protocol"], indent=2) + "\n").encode()
    if (
        spec["revision"] != "fma-component-balanced-execution-v1"
        or spec.get("versions") != _versions()
        or spec["protocol_sha256"] != PROTOCOL_SHA256
        or hashlib.sha256(protocol_bytes).hexdigest() != PROTOCOL_SHA256
        or spec["code"] != {name: digest(p) for name, p in _code_paths().items()}
    ):
        raise ValueError("Protocol or producer differs from execution seal")
    return spec


@dataclass
class Corpus:
    """Only original-training rows enter fit/score arrays."""

    ids: np.ndarray
    groups: np.ndarray
    inner_folds: np.ndarray
    features: np.ndarray
    targets: sparse.csr_matrix
    labels: tuple[int, ...]
    artists: np.ndarray
    albums: np.ndarray


def training_roster(
    tracks: tuple[baseline.NativeTrack, ...], groups: dict[int, int], ledger: list[dict[str, Any]]
) -> list[baseline.NativeTrack]:
    """Replay tentative identity folds, then exclude unresolved artists from training."""
    by_id = {r["track_id"]: r for r in ledger}
    if len(by_id) != len(tracks) or len(ledger) != len(tracks):
        raise ValueError("Ledger roster differs")
    selected = []
    for row in tracks:
        group = groups.get(row.artist_id)
        fold = baseline.artist_group_fold(group) if group is not None else -1
        expected = {
            "track_id": row.track_id,
            "artist_id": row.artist_id,
            "album_id": row.album_id,
            "artist_known": row.artist_known,
            "component_id": group,
            "fold": fold,
        }
        if by_id.get(row.track_id) != expected:
            raise ValueError("Native component or original fold replay differs")
        if fold == 0 and row.artist_known:
            selected.append(row)
    return selected


def load_corpus(spec: dict[str, Any]) -> Corpus:
    """Validate closed retained source, replay identity graph, select original fold0 only."""
    root = Path(spec["source"])
    if digest(root / "MANIFEST.json") != MANIFEST_SHA256:
        raise ValueError("Numeric input manifest differs")
    manifest = json.loads((root / "MANIFEST.json").read_text())
    actual = {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}
    if actual != set(manifest["files"]) | {"MANIFEST.json"}:
        raise ValueError("Source inventory differs")
    for name, binding in manifest["files"].items():
        p = root / name
        if p.is_symlink() or p.stat().st_size != binding["bytes"] or digest(p) != binding["sha256"]:
            raise ValueError("Source bytes differ")
    records = _rows(root / "tracks-numeric.jsonl.zst")
    tracks = tuple(
        sorted(
            (
                baseline.NativeTrack(
                    r["track_id"],
                    r["artist_id"],
                    r["artist_id_status"] == "source_known",
                    r["album_id"],
                    tuple(sorted(r["genre_ids"] or [])),
                    r["genre_ids"] is None,
                )
                for r in records
            ),
            key=lambda r: r.track_id,
        )
    )
    groups = baseline.native_components(
        tracks, json.loads((root / "duplicate-native-feature-cells.json").read_text())
    )
    ledger = _rows(root / "saved-replay/native-folds.jsonl.zst")
    selected = training_roster(tracks, groups, ledger)
    labels = tuple(sorted(r["genre_id"] for r in _rows(root / "genres-numeric.jsonl.zst")))
    columns = {label: i for i, label in enumerate(labels)}
    native_ids = np.fromfile(root / "track_ids.uint32", dtype="<u4")
    raw = np.memmap(root / "features.float32", dtype="<f4", mode="r", shape=(len(native_ids), 44))
    lookup = {int(t): i for i, t in enumerate(native_ids)}
    x = np.full((len(selected), 44), np.nan, dtype=np.float32)
    rr, cc = [], []
    for i, row in enumerate(selected):
        if row.track_id in lookup:
            x[i] = raw[lookup[row.track_id]]
        for label in row.genre_ids:
            rr.append(i)
            cc.append(columns[label])
    y = sparse.csr_matrix((np.ones(len(rr)), (rr, cc)), shape=(len(selected), len(labels)))
    components = np.array([groups[cast("int", r.artist_id)] for r in selected], dtype=np.int64)
    return Corpus(
        np.array([r.track_id for r in selected]),
        components,
        np.array([component_fold(int(g)) for g in components]),
        x,
        y,
        labels,
        np.array([r.artist_id for r in selected]),
        np.array([r.album_id or 0 for r in selected]),
    )


def _budget(root: Path) -> None:
    if any(p.is_symlink() for p in root.rglob("*")):
        raise ValueError("Symlink in output")
    if sum(p.stat().st_size for p in root.rglob("*") if p.is_file()) > MAX_OUTPUT_BYTES:
        raise ValueError("Combined output exceeds100MB; do not raise bound")


def preflight(seal: Path, output: Path) -> dict[str, Any]:
    """Descriptive training concentration only; no scoring."""
    data = load_corpus(verify_seal(seal))
    output.mkdir(parents=True, exist_ok=False)
    ids, inv = np.unique(data.groups, return_inverse=True)
    positives = np.asarray(data.targets.sum(axis=1)).ravel()
    rows = np.bincount(inv)
    finite = np.asarray(np.isfinite(data.features).all(axis=1), dtype=bool)
    masses = np.column_stack(
        [
            rows,
            np.bincount(inv, weights=finite),
            np.bincount(inv, weights=positives > 0),
            np.bincount(inv, weights=positives),
        ]
    )
    biggest = int(ids[np.argmax(rows)])
    concentration = {}
    for j, name in enumerate(("queries", "finite", "labeled", "positives")):
        a = np.sort(masses[:, j])[::-1]
        concentration[name] = {
            "total": float(a.sum()),
            "largest_share": float(a[0] / a.sum()),
            "top5_share": float(a[:5].sum() / a.sum()),
            "top10_share": float(a[:10].sum() / a.sum()),
            "effective_components": float(a.sum() ** 2 / (a @ a)),
        }
    folds = [
        {
            "fold": f,
            "queries": int((data.inner_folds == f).sum()),
            "components": len(np.unique(data.groups[data.inner_folds == f])),
            "positives": float(positives[data.inner_folds == f].sum()),
            "finite": int(finite[data.inner_folds == f].sum()),
        }
        for f in range(FOLD_COUNT)
    ]
    per_label = []
    csc = data.targets.tocsc()
    for label, identity in enumerate(data.labels):
        selected_rows = csc.indices[csc.indptr[label] : csc.indptr[label + 1]]
        _, counts = np.unique(data.groups[selected_rows], return_counts=True)
        ordered = np.sort(counts)[::-1]
        per_label.append(
            {
                "genre_id": identity,
                "positive_rows": len(selected_rows),
                "positive_components": len(counts),
                "finite_positive_rows": int(finite[selected_rows].sum()),
                "finite_positive_components": len(
                    np.unique(data.groups[selected_rows[finite[selected_rows]]])
                ),
                "largest_share": float(ordered[0] / ordered.sum()) if len(ordered) else None,
                "top5_share": float(ordered[:5].sum() / ordered.sum()) if len(ordered) else None,
                "top10_share": float(ordered[:10].sum() / ordered.sum()) if len(ordered) else None,
                "effective_components": float(ordered.sum() ** 2 / (ordered @ ordered))
                if len(ordered)
                else None,
            }
        )
    result = {
        "per_label": per_label,
        "concentration": concentration,
        "inner_folds": folds,
        "largest_component": {
            "component_id": biggest,
            "rows": int((data.groups == biggest).sum()),
            "artists": len(np.unique(data.artists[data.groups == biggest])),
            "nonnull_albums": len(set(data.albums[data.groups == biggest]) - {0}),
        },
        "components": len(ids),
        "seal_sha256": digest(seal),
    }
    _json(output / "preflight.json", result)
    _budget(output)
    return result


def query_stats(positives: list[int], ranking: list[int], active: np.ndarray) -> np.ndarray:
    """All observed positives remain denominators, even when model support is absent."""
    p = set(positives)
    hits = len(p & set(ranking[:10]))
    rr = next((1.0 / k for k, label in enumerate(ranking, 1) if label in p), 0.0)
    available = sum(bool(active[i]) for i in p)
    covered = bool(ranking)
    return np.array(
        [
            1,
            bool(p),
            len(p),
            hits,
            rr,
            len(p) * rr,
            covered,
            len(p) * covered,
            available,
            available * covered,
            bool(p) * covered,
        ],
        dtype=float,
    )


def _receipt(directory: Path, seal: Path, started: float, metadata: dict[str, Any]) -> None:
    metadata.update(
        seal_sha256=digest(seal),
        elapsed_seconds=time.monotonic() - started,
        peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
        files={
            p.name: {"bytes": p.stat().st_size, "sha256": digest(p)}
            for p in directory.iterdir()
            if p.is_file()
        },
    )
    _json(directory / "receipt.json", metadata)
    _budget(directory.parent)


def run_fold(seal: Path, output: Path, fold: int) -> dict[str, Any]:
    """One bounded stage fits both fixed arms then scores one untouched innerfold."""
    started = time.monotonic()
    if fold not in range(FOLD_COUNT):
        raise ValueError("Invalid innerfold")
    data = load_corpus(verify_seal(seal))
    fit = data.inner_folds != fold
    query = np.flatnonzero(~fit)
    directory = output / f"fold-{fold}"
    directory.mkdir(parents=True, exist_ok=False)
    models = {
        "recording": baseline.fit_positive_gaussian(data.features, data.targets, fit),
        "balanced": fit_component_gaussian(data.features, data.targets, fit, data.groups),
    }
    source_support = np.asarray(data.targets[fit].sum(axis=0)).ravel()
    popularity, _ = baseline.training_baseline_rankings(source_support)
    components, inverse = np.unique(data.groups[query], return_inverse=True)
    stats = np.zeros((len(components), len(ARMS), len(STAT_NAMES)))
    abstentions: dict[str, dict[str, int]] = {arm: {} for arm in ARMS}
    label_components = []
    finite_fit = fit & np.isfinite(data.features).all(axis=1)
    csc = data.targets.tocsc()
    for label in range(len(data.labels)):
        rows = csc.indices[csc.indptr[label] : csc.indptr[label + 1]]
        label_components.append(len(np.unique(data.groups[rows[finite_fit[rows]]])))
    with zstandard.open(directory / "ranks.jsonl.zst", "wt") as stream:
        for start in range(0, len(query), 2048):
            batch = query[start : start + 2048]
            scored = {
                name: baseline.score_positive_gaussian(model, data.features[batch])
                for name, model in models.items()
            }
            for offset, row in enumerate(batch):
                targets = data.targets.indices[
                    data.targets.indptr[row] : data.targets.indptr[row + 1]
                ].tolist()
                record = {
                    "track_id": int(data.ids[row]),
                    "component_id": int(data.groups[row]),
                    "inner_fold": fold,
                    "targets": [data.labels[i] for i in targets],
                    "arms": {},
                }
                for arm_index, arm in enumerate(ARMS):
                    if arm == "popularity":
                        ranking, reason, active = popularity, None, source_support > 0
                    else:
                        scores, reasons = scored[arm]
                        ranking = [
                            int(i)
                            for i in np.argsort(-scores[offset], kind="stable")
                            if np.isfinite(scores[offset, i])
                        ]
                        reason, active = reasons[offset], models[arm].active_labels
                    if reason is not None:
                        abstentions[arm][reason] = abstentions[arm].get(reason, 0) + 1
                    stats[inverse[start + offset], arm_index] += query_stats(
                        targets, ranking, active
                    )
                    if arm != "popularity":
                        record["arms"][arm] = {
                            "ranking": [data.labels[i] for i in ranking],
                            "reason": reason,
                        }
                stream.write(json.dumps(record, separators=(",", ":")) + "\n")
    for name, model in models.items():
        np.savez(directory / f"{name}.npz", **asdict(model))
    np.savez(directory / "statistics.npz", components=components, values=stats)
    _json(
        directory / "support.json",
        {
            "labels": data.labels,
            "source_positive_rows": source_support.tolist(),
            "finite_positive_rows": models["recording"].label_feature_support.tolist(),
            "positive_components": label_components,
            "active_labels_with_below_five_components": [
                data.labels[i]
                for i, count in enumerate(label_components)
                if count < MIN_LABEL_SUPPORT and models["recording"].active_labels[i]
            ],
            "popularity_ranking": [data.labels[i] for i in popularity],
        },
    )
    metadata = {
        "fold": fold,
        "abstentions": abstentions,
        "training_queries": int(fit.sum()),
        "heldout_queries": len(query),
        "heldout_components": len(components),
        "columns": STAT_NAMES,
        "arms": ARMS,
    }
    _receipt(directory, seal, started, metadata)
    return metadata


def summarize_run(seal: Path, output: Path) -> dict[str, Any]:
    """Verify complete fivefold result custody and summarize fixed OOF predictions."""
    started = time.monotonic()
    data = load_corpus(verify_seal(seal))
    directory = output / "summary"
    if directory.exists():
        raise ValueError("Summary output must be fresh")
    values, groups, fold_reports, receipts = [], [], {}, {}
    for fold in range(FOLD_COUNT):
        folder = output / f"fold-{fold}"
        receipt = json.loads((folder / "receipt.json").read_text())
        expected = {
            "recording.npz",
            "balanced.npz",
            "statistics.npz",
            "support.json",
            "ranks.jsonl.zst",
        }
        if (
            receipt["seal_sha256"] != digest(seal)
            or receipt["fold"] != fold
            or set(receipt["files"]) != expected
            or {p.name for p in folder.iterdir()} != expected | {"receipt.json"}
        ):
            raise ValueError("Incomplete or mismatched fold output")
        for name, binding in receipt["files"].items():
            p = folder / name
            if (
                p.is_symlink()
                or p.stat().st_size != binding["bytes"]
                or digest(p) != binding["sha256"]
            ):
                raise ValueError("Fold artifact differs")
        with np.load(folder / "statistics.npz", allow_pickle=False) as saved:
            ids, stats = saved["components"], saved["values"]
        query = data.inner_folds == fold
        expected_ids, expected_queries = np.unique(data.groups[query], return_counts=True)
        if not np.array_equal(ids, expected_ids) or stats.shape != (len(ids), 3, len(STAT_NAMES)):
            raise ValueError("Statistics component roster differs")
        for arm in range(3):
            if not np.array_equal(stats[:, arm, 0], expected_queries):
                raise ValueError("Missing query denominators")
        values.append(stats)
        groups.extend(ids.tolist())
        fold_reports[str(fold)] = summarize(stats, bootstrap=False)
        receipts[str(fold)] = digest(folder / "receipt.json")
    stats = np.concatenate(values)
    order = np.argsort(groups)
    stats, ids = stats[order], np.array(groups)[order]
    if len(np.unique(ids)) != len(ids):
        raise ValueError("Component crosses innerfolds")
    result = summarize(stats)
    result.update(
        component_ids=ids.tolist(),
        per_fold=fold_reports,
        fold_receipts=receipts,
        seal_sha256=digest(seal),
        metric_columns=STAT_NAMES,
        interpretation=verify_seal(seal)["protocol"]["interpretation"],
        largest_component_id=int(ids[np.argmax(stats[:, 0, 0])]),
    )
    directory.mkdir()
    _json(directory / "results.json", result)
    _receipt(directory, seal, started, {"stage": "summary"})
    return result
