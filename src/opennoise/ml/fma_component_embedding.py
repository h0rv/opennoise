"""One frozen supervised ridge embedding; feature-only application on original-training CV."""

import hashlib
import json
import platform
import resource
import time
from dataclasses import asdict, dataclass
from importlib.metadata import version
from pathlib import Path
from typing import Any

import numpy as np
import zstandard
from scipy import sparse

from opennoise.ml import fma_acoustic_baseline as gaussian
from opennoise.ml import fma_component_balanced as balanced
from opennoise.ml import fma_component_balanced_metrics as metric

PROTOCOL_SHA256 = "8323b4e1e9a6aba9a1fc5d04e1864b8b415647cc596e72ddd7fb23308934849a"
ARMS = (
    "raw44_neighbors",
    "ridge8_neighbors",
    "recording_gaussian",
    "balanced_gaussian",
    "recording_popularity",
)
GIANT_COMPONENT = 2
RANK = 8
CANDIDATES = 2048
BATCH = 256
NEIGHBORS = 10
STATS = (
    *balanced.STAT_NAMES,
    "descriptor_queries",
    "neighbor_queries",
    "descriptor_supported_positives",
)
PAIRS = ((1, 0), (1, 3), (1, 4))


@dataclass
class RidgeEmbedding:
    """Persisted ridge coefficients and deterministic low-rank geometry."""

    center: np.ndarray
    scale: np.ndarray
    active_columns: np.ndarray
    active_labels: np.ndarray
    target_mean: np.ndarray
    coefficients: np.ndarray
    singular_values: np.ndarray
    encoder: np.ndarray


def compressed_encoder(coefficients: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Fail ambiguous rank boundaries; never choose an outcome-dependent fallback."""
    if not coefficients.shape[1]:
        return np.zeros((coefficients.shape[0], 0)), np.zeros(0)
    u, singular, decoder = np.linalg.svd(coefficients, full_matrices=False)
    tolerance = max(coefficients.shape) * np.finfo(np.float64).eps * singular[0]
    rank = int(np.count_nonzero(singular > tolerance))
    if rank > RANK and abs(singular[RANK - 1] - singular[RANK]) <= 1e-10 * singular[0]:
        raise ValueError("ambiguous_rank8_boundary")
    used = min(RANK, rank)
    axes = u[:, :used].copy()
    for i in range(used):
        if axes[np.argmax(np.abs(axes[:, i])), i] < 0:
            axes[:, i] *= -1
            decoder[i] *= -1
    return axes * singular[:used], singular


def fit_embedding(
    features: np.ndarray, targets: sparse.csr_matrix, training: np.ndarray, groups: np.ndarray
) -> RidgeEmbedding:
    """Train only on finite innerfit rows and their supplied weak source labels."""
    if (
        training.dtype != np.bool_
        or training.shape != (len(features),)
        or groups.shape != training.shape
    ):
        raise ValueError("Unaligned training mask")
    finite = training & np.isfinite(features).all(axis=1)
    x = np.asarray(features[finite], dtype=np.float64)
    if len(x) < gaussian.MIN_LABEL_SUPPORT:
        raise ValueError("Insufficient finite fit rows")
    weights = balanced.equal_component_weights(groups[finite])
    weights /= weights.sum()
    center = np.average(x, axis=0, weights=weights)
    scale = np.sqrt(np.average((x - center) ** 2, axis=0, weights=weights))
    active = scale > 0
    if not active.any() or not np.isfinite(center).all() or not np.isfinite(scale).all():
        raise ValueError("Invalid fit normalization")
    z = (x[:, active] - center[active]) / scale[active]
    support = np.asarray(targets[finite].sum(axis=0)).ravel()
    active_labels = support >= gaussian.MIN_LABEL_SUPPORT
    y = targets[finite][:, active_labels].toarray()
    if not np.isin(y, [0, 1]).all():
        raise ValueError("Source targets must be binary")
    target_mean = weights @ y
    gram = z.T @ (weights[:, None] * z)
    cross = z.T @ (weights[:, None] * (y - target_mean))
    coefficients = np.linalg.solve(gram + np.eye(len(gram)), cross)
    if not np.isfinite(coefficients).all():
        raise ValueError("Nonfinite ridge coefficients")
    encoder, singular = compressed_encoder(coefficients)
    return RidgeEmbedding(
        center, scale, active, active_labels, target_mean, coefficients, singular, encoder
    )


def representations(
    model: RidgeEmbedding, features: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Return two feature-only unit vectors and separately auditable support masks."""
    complete = np.asarray(np.isfinite(features).all(axis=1), dtype=bool)
    z = (
        np.asarray(features[:, model.active_columns], dtype=np.float64)
        - model.center[model.active_columns]
    ) / model.scale[model.active_columns]
    descriptor = complete & (np.abs(z) <= gaussian.MAX_STANDARDIZED_OFFSET).all(axis=1)
    z = np.where(descriptor[:, None], z, 0)
    embedded = z @ model.encoder
    raw_norm, embedding_norm = np.linalg.norm(z, axis=1), np.linalg.norm(embedded, axis=1)
    raw_ok = descriptor & (raw_norm > 0)
    embedding_ok = descriptor & (embedding_norm > 0)
    raw = np.divide(z, raw_norm[:, None], out=np.zeros_like(z), where=raw_norm[:, None] > 0)
    embedded = np.divide(
        embedded,
        embedding_norm[:, None],
        out=np.zeros_like(embedded),
        where=embedding_norm[:, None] > 0,
    )
    return raw, embedded, descriptor, raw_ok, embedding_ok


def _hash_order(scope: str, identity: int) -> tuple[bytes, int]:
    return hashlib.sha256(f"{scope}\0{identity}".encode()).digest(), identity


def nominate(data: balanced.Corpus, fit: np.ndarray) -> np.ndarray:
    """Nominate finite representatives without reading any source genre labels."""
    representatives: dict[int, int] = {}
    for i in np.flatnonzero(fit & np.isfinite(data.features).all(axis=1)):
        group = int(data.groups[i])
        old = representatives.get(group)
        if old is None or _hash_order(
            "fma-ridge-representative-v1", int(data.ids[i])
        ) < _hash_order("fma-ridge-representative-v1", int(data.ids[old])):
            representatives[group] = int(i)
    selected = sorted(
        representatives, key=lambda c: _hash_order("fma-ridge-candidate-components-v1", c)
    )[:CANDIDATES]
    return np.array(
        sorted((representatives[c] for c in selected), key=lambda i: data.ids[i]), dtype=int
    )


def transfer(neighbor_rows: list[int], targets: sparse.csr_matrix) -> list[int]:
    """Transfer only positive training-candidate votes, with stable native genre ties."""
    votes = np.asarray(targets[neighbor_rows].sum(axis=0)).ravel()
    return [int(i) for i in np.argsort(-votes, kind="stable") if votes[i] > 0]


def _json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def _versions() -> dict[str, str]:
    return {
        "python": platform.python_version(),
        **{n: version(n) for n in ("numpy", "scipy", "zstandard")},
    }


def _code() -> dict[str, str]:
    root = Path(__file__).resolve().parents[3]
    names = [
        "src/opennoise/ml/fma_component_embedding.py",
        "scripts/run_fma_component_embedding.py",
        "src/opennoise/ml/fma_component_balanced.py",
        "src/opennoise/ml/fma_component_balanced_metrics.py",
        "src/opennoise/ml/fma_acoustic_baseline.py",
        "src/opennoise/ml/fma_split_audit.py",
    ]
    return {n: balanced.digest(root / n) for n in names}


def freeze(protocol: Path, source: Path, output: Path) -> dict[str, Any]:
    """Seal reviewed source and environment before any retained-data model outcomes."""
    if output.exists() or balanced.digest(protocol) != PROTOCOL_SHA256:
        raise ValueError("Exact approved protocol and fresh seal required")
    if balanced.digest(source / "MANIFEST.json") != balanced.MANIFEST_SHA256:
        raise ValueError("Numeric input manifest differs")
    seal = {
        "revision": "fma-ridge-embedding-execution-v1",
        "protocol_sha256": PROTOCOL_SHA256,
        "protocol": json.loads(protocol.read_text()),
        "source": str(source.resolve()),
        "code": _code(),
        "versions": _versions(),
    }
    _json(output, seal)
    return seal


def verify_seal(path: Path) -> dict[str, Any]:
    """Reject altered design, code or numerical environment."""
    seal = json.loads(path.read_text())
    if (
        seal["revision"] != "fma-ridge-embedding-execution-v1"
        or seal["code"] != _code()
        or seal["versions"] != _versions()
        or seal["protocol_sha256"] != PROTOCOL_SHA256
        or hashlib.sha256((json.dumps(seal["protocol"], indent=2) + "\n").encode()).hexdigest()
        != PROTOCOL_SHA256
    ):
        raise ValueError("Execution seal differs")
    return seal


def _receipt(directory: Path, seal: Path, started: float, metadata: dict[str, Any]) -> None:
    metadata.update(
        seal_sha256=balanced.digest(seal),
        elapsed_seconds=time.monotonic() - started,
        peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
        files={
            p.name: {"bytes": p.stat().st_size, "sha256": balanced.digest(p)}
            for p in directory.iterdir()
            if p.is_file()
        },
    )
    _json(directory / "receipt.json", metadata)
    balanced._budget(directory.parent)  # noqa: SLF001 - preserve sealed prior output guard.


def run_fold(seal: Path, output: Path, fold: int) -> dict[str, Any]:  # noqa: C901, PLR0912, PLR0915 - fixed five-arm matched stage.
    """Fit one prespecified innerfold and score every original-training heldout query."""
    started = time.monotonic()
    if fold not in range(5):
        raise ValueError("Invalid fold")
    data = balanced.load_corpus(verify_seal(seal))
    fit = data.inner_folds != fold
    query = np.flatnonzero(~fit)
    directory = output / f"fold-{fold}"
    if any(p.is_symlink() for p in (directory, *directory.parents)):
        raise ValueError("Symlink output path")
    directory.mkdir(parents=True, exist_ok=False)
    encoder = fit_embedding(data.features, data.targets, fit, data.groups)
    models = {
        "recording_gaussian": gaussian.fit_positive_gaussian(data.features, data.targets, fit),
        "balanced_gaussian": balanced.fit_component_gaussian(
            data.features, data.targets, fit, data.groups
        ),
    }
    if not np.allclose(
        encoder.center, models["balanced_gaussian"].center, rtol=1e-12, atol=1e-12
    ) or not np.allclose(encoder.scale, models["balanced_gaussian"].scale, rtol=1e-12, atol=1e-12):
        raise ValueError("Matched normalization differs")
    nominated = nominate(data, fit)
    raw, embedded, descriptor, raw_ok, embedding_ok = representations(
        encoder, data.features[nominated]
    )
    joint = raw_ok & embedding_ok
    candidates = nominated[joint]
    raw_candidates, embedded_candidates = raw[joint], embedded[joint]
    union = np.asarray(data.targets[candidates].sum(axis=0)).ravel() > 0
    source_support = np.asarray(data.targets[fit].sum(axis=0)).ravel()
    popularity, _ = gaussian.training_baseline_rankings(source_support)
    components, inverse = np.unique(data.groups[query], return_inverse=True)
    stats = np.zeros((len(components), len(ARMS), len(STATS)))
    reasons: dict[str, dict[str, int]] = {arm: {} for arm in ARMS}
    with zstandard.open(directory / "ranks.jsonl.zst", "wt") as stream:
        for start in range(0, len(query), BATCH):
            batch = query[start : start + BATCH]
            rv, ev, supported, rok, eok = representations(encoder, data.features[batch])
            score = {
                "raw44_neighbors": rv @ raw_candidates.T,
                "ridge8_neighbors": ev @ embedded_candidates.T,
            }
            nearest = {
                arm: np.argsort(-values, axis=1, kind="stable")[:, :NEIGHBORS]
                for arm, values in score.items()
            }
            gaussian_scores = {
                arm: gaussian.score_positive_gaussian(model, data.features[batch])
                for arm, model in models.items()
            }
            for j, row in enumerate(batch):
                positives = data.targets.indices[
                    data.targets.indptr[row] : data.targets.indptr[row + 1]
                ].tolist()
                record = {
                    "track_id": int(data.ids[row]),
                    "component_id": int(data.groups[row]),
                    "inner_fold": fold,
                    "targets": [data.labels[i] for i in positives],
                    "arms": {},
                }
                for a, arm in enumerate(ARMS):
                    neighbors: list[int] = []
                    distances: list[float] = []
                    if arm in score:
                        okay = bool(rok[j] if a == 0 else eok[j])
                        reason = (
                            None
                            if okay
                            else (
                                "missing_descriptors"
                                if not np.isfinite(data.features[row]).all()
                                else "outside_training_support"
                            )
                            if not supported[j]
                            else "raw_zero_norm"
                            if a == 0
                            else "embedding_zero_rank"
                            if not encoder.encoder.shape[1]
                            else "embedding_zero_norm"
                        )
                        if okay and len(candidates):
                            neighbors = [int(i) for i in candidates[nearest[arm][j]]]
                            distances = [float(v) for v in (1 - score[arm][j, nearest[arm][j]])]
                        elif okay:
                            reason = "no_joint_candidates"
                        ranking, active = transfer(neighbors, data.targets), union
                        descriptor_available = okay
                    elif arm == "recording_popularity":
                        ranking, active, reason, descriptor_available = (
                            popularity,
                            source_support > 0,
                            None,
                            True,
                        )
                    else:
                        values, why = gaussian_scores[arm]
                        ranking = [
                            int(i)
                            for i in np.argsort(-values[j], kind="stable")
                            if np.isfinite(values[j, i])
                        ]
                        active, reason = models[arm].active_labels, why[j]
                        descriptor_available = reason is None
                    sufficient = balanced.query_stats(positives, ranking, active)
                    stats[inverse[start + j], a, :11] += sufficient
                    stats[inverse[start + j], a, 11:] += [
                        descriptor_available,
                        bool(neighbors),
                        sum(bool(active[i]) for i in positives) * descriptor_available,
                    ]
                    if reason is not None:
                        reasons[arm][reason] = reasons[arm].get(reason, 0) + 1
                    record["arms"][arm] = {
                        "ranking": [data.labels[i] for i in ranking],
                        "reason": reason,
                        "descriptor_available": descriptor_available,
                    }
                    if arm in score:
                        record["arms"][arm].update(
                            neighbor_ids=[int(data.ids[i]) for i in neighbors],
                            cosine_distances=distances,
                        )
                stream.write(json.dumps(record, separators=(",", ":")) + "\n")
    np.savez(directory / "embedding.npz", **asdict(encoder))
    for name, model in models.items():
        np.savez(directory / f"{name}.npz", **asdict(model))
    np.savez(directory / "statistics.npz", components=components, values=stats)
    _json(
        directory / "candidates.json",
        {
            "nominated_ids": data.ids[nominated].tolist(),
            "joint_ids": data.ids[candidates].tolist(),
            "intrinsic_descriptor_ids": data.ids[nominated[descriptor]].tolist(),
            "intrinsic_raw_ids": data.ids[nominated[raw_ok]].tolist(),
            "intrinsic_embedding_ids": data.ids[nominated[embedding_ok]].tolist(),
            "candidate_label_union": [data.labels[i] for i in np.flatnonzero(union)],
            "encoder_active_labels": [
                data.labels[i] for i in np.flatnonzero(encoder.active_labels)
            ],
        },
    )
    result = {
        "fold": fold,
        "fit_queries": int(fit.sum()),
        "heldout_queries": len(query),
        "components": len(components),
        "abstentions": reasons,
        "columns": STATS,
        "arms": ARMS,
        "embedding_dimensions": encoder.encoder.shape[1],
    }
    _receipt(directory, seal, started, result)
    return result


def _validate_statistics(stats: np.ndarray) -> None:
    if (
        stats.ndim != len(("component", "arm", "statistic"))
        or stats.shape[1:] != (len(ARMS), len(STATS))
        or not np.isfinite(stats).all()
        or (stats < 0).any()
    ):
        raise ValueError("Invalid component statistics")
    if not np.array_equal(stats[:, :, :3], np.repeat(stats[:, :1, :3], len(ARMS), axis=1)):
        raise ValueError("Paired denominators differ")
    for numerator, denominator in (
        (1, 0),
        (3, 2),
        (4, 1),
        (5, 2),
        (6, 0),
        (7, 2),
        (8, 2),
        (9, 8),
        (9, 7),
        (10, 1),
        (10, 6),
        (11, 0),
        (12, 11),
        (13, 8),
        (13, 2),
    ):
        if np.any(stats[:, :, numerator] > stats[:, :, denominator] + 1e-9):
            raise ValueError("Numerator exceeds declared denominator")


def summarize_statistics(stats: np.ndarray, *, bootstrap: bool = True) -> dict[str, Any]:
    """Preserve full denominators and resample fixed predictions by component."""
    _validate_statistics(stats)
    base = stats[:, :, :11]
    values = metric.metrics(base)
    totals = stats.sum(axis=0)
    result: dict[str, Any] = {"arms": {}, "paired_bootstrap": None}
    for a, arm in enumerate(ARMS):
        result["arms"][arm] = {
            "totals": dict(zip(STATS, totals[a].tolist(), strict=True)),
            "metrics": {
                name: metric.nullable(v) for name, v in zip(metric.METRICS, values[a], strict=True)
            },
            "descriptor_coverage": metric.nullable(totals[a, 11] / totals[a, 0])
            if totals[a, 0]
            else None,
            "neighbor_coverage": metric.nullable(totals[a, 12] / totals[a, 0])
            if totals[a, 0] and arm in ARMS[:2]
            else None,
            "descriptor_support_ceiling": metric.nullable(totals[a, 13] / totals[a, 2])
            if totals[a, 2]
            else None,
            "components": len(stats),
        }
    if not bootstrap:
        return result
    rng = np.random.Generator(np.random.PCG64(20261016))
    samples = np.full((2000, len(PAIRS), len(metric.METRICS)), np.nan)
    for draw in range(2000):
        selected = (
            rng.integers(0, len(stats), size=len(stats)) if len(stats) else np.array([], dtype=int)
        )
        current = metric.metrics(base[selected])
        for pair, (left, right) in enumerate(PAIRS):
            samples[draw, pair] = current[left] - current[right]
    comparisons = {}
    for pair, (left, right) in enumerate(PAIRS):
        metrics = {}
        for m, name in enumerate(metric.METRICS):
            finite = samples[:, pair, m][np.isfinite(samples[:, pair, m])]
            metrics[name] = {
                "difference": metric.nullable(values[left, m] - values[right, m]),
                "interval": np.quantile(finite, [0.025, 0.975], method="linear").tolist()
                if len(finite)
                else None,
                "valid_draws": len(finite),
                "undefined_draws": 2000 - len(finite),
            }
        comparisons[f"{ARMS[left]}_minus_{ARMS[right]}"] = metrics
    result["paired_bootstrap"] = {
        "draws": 2000,
        "seed": 20261016,
        "rng": "PCG64",
        "comparisons": comparisons,
        "interpretation": (
            "Conditional on fixed OOF predictions; overlapping training fits, "
            "no population or musical quality inference."
        ),
    }
    return result


def summarize_run(seal: Path, output: Path) -> dict[str, Any]:
    """Validate closed stage inventories and full original-training query coverage."""
    started = time.monotonic()
    data = balanced.load_corpus(verify_seal(seal))
    if output.is_symlink() or {p.name for p in output.iterdir()} != {f"fold-{i}" for i in range(5)}:
        raise ValueError("Run root inventory differs")
    directory = output / "summary"
    if directory.exists():
        raise ValueError("Summary must be fresh")
    values, groups, folds, receipts = [], [], {}, {}
    for fold in range(5):
        folder = output / f"fold-{fold}"
        receipt = json.loads((folder / "receipt.json").read_text())
        expected = {
            "embedding.npz",
            "recording_gaussian.npz",
            "balanced_gaussian.npz",
            "statistics.npz",
            "candidates.json",
            "ranks.jsonl.zst",
        }
        if (
            receipt["seal_sha256"] != balanced.digest(seal)
            or receipt["fold"] != fold
            or set(receipt["files"]) != expected
            or {p.name for p in folder.iterdir()} != expected | {"receipt.json"}
        ):
            raise ValueError("Incomplete or mismatched fold")
        for name, binding in receipt["files"].items():
            p = folder / name
            if (
                p.is_symlink()
                or p.stat().st_size != binding["bytes"]
                or balanced.digest(p) != binding["sha256"]
            ):
                raise ValueError("Fold file changed")
        with np.load(folder / "statistics.npz", allow_pickle=False) as saved:
            ids, stats = saved["components"], saved["values"]
        expected_ids, counts = np.unique(data.groups[data.inner_folds == fold], return_counts=True)
        if (
            not np.array_equal(ids, expected_ids)
            or stats.shape != (len(ids), len(ARMS), len(STATS))
            or not np.array_equal(stats[:, :, 0], np.repeat(counts[:, None], len(ARMS), axis=1))
        ):
            raise ValueError("Heldout query or component roster differs")
        values.append(stats)
        groups.extend(ids.tolist())
        folds[str(fold)] = summarize_statistics(stats, bootstrap=False)
        receipts[str(fold)] = balanced.digest(folder / "receipt.json")
    ids = np.array(groups)
    order = np.argsort(ids)
    ids = ids[order]
    stats = np.concatenate(values)[order]
    if len(np.unique(ids)) != len(ids):
        raise ValueError("Component crosses folds")
    result = summarize_statistics(stats)
    result.update(
        component_ids=ids.tolist(),
        per_fold=folds,
        fold_receipts=receipts,
        giant_component_id=GIANT_COMPONENT,
        giant_component=summarize_statistics(stats[ids == GIANT_COMPONENT], bootstrap=False),
        other_components=summarize_statistics(stats[ids != GIANT_COMPONENT], bootstrap=False),
        interpretation=verify_seal(seal)["protocol"]["interpretation"],
    )
    directory.mkdir()
    _json(directory / "results.json", result)
    _receipt(directory, seal, started, {"stage": "summary"})
    return result
