"""Fixed-rank component uncertainty; no model fitting or scoring imports."""

import collections
import hashlib
import json
import resource
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import numpy as np
import zstandard

ANALYSIS_SHA256 = "1af99b2e6d22888dd525f534201281b54ea92035f33a170a226c70c562ee37f5"
MIN_COMPONENTS = 2
STAT_COLUMNS = 7
MAX_OUTPUT_BYTES = 10000000
REPLAY_TOLERANCE = 1e-12


def _verify(spec: dict[Any, Any]) -> None:
    for name, pin in spec["inputs"].items():
        p = Path(name)
        if not p.stat().st_size == pin["bytes"]:
            raise ValueError(
                "Diagnostic input or saved metric does not match its declared contract"
            )
        if not hashlib.sha256(p.read_bytes()).hexdigest() == pin["sha256"]:
            raise ValueError(
                "Diagnostic input or saved metric does not match its declared contract"
            )


def _rows(path: Path) -> Iterator[dict[Any, Any]]:
    with zstandard.open(path, "rt") as f:
        for line in f:
            yield json.loads(line)


def _metrics(v: np.ndarray) -> np.ndarray:
    return np.array([v[3] / v[2], v[4] / v[2], v[5] / v[1], v[6] / v[1]])


def concentration(a: np.ndarray) -> dict[Any, Any]:
    """Report mass concentration and inverse Herfindahl effective component count."""
    a = np.array(a, dtype=float)
    a = np.sort(a)[::-1]
    s = a.sum()
    return {
        "largest_share": float(a[0] / s),
        "top5_share": float(a[:5].sum() / s),
        "top10_share": float(a[:10].sum() / s),
        "inverse_herfindahl_effective_components": float(s * s / (a @ a)),
    }


def run(declaration: Path, baseline: Path, metadata: Path, output: Path) -> dict[Any, Any]:
    """Replay frozen ranks and report prespecified connected-component diagnostics."""
    started = time.monotonic()
    spec = json.loads(declaration.read_text())
    if not spec["revision"] == "fma-fixed-rank-component-diagnostics-v1":
        raise ValueError("Diagnostic input or saved metric does not match its declared contract")
    if not spec["limits"] == {
        "wall_seconds": 120,
        "address_space_bytes": 1000000000,
        "new_output_bytes": 10000000,
    }:
        raise ValueError("Diagnostic input or saved metric does not match its declared contract")
    analysis_hash = hashlib.sha256(
        json.dumps(spec["prespecified_analysis"], sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    if analysis_hash != ANALYSIS_SHA256:
        raise ValueError("Unsupported prespecified analysis; do not silently change parameters")
    _verify(spec)
    for path in [
        baseline / n
        for n in [
            "evaluation.json",
            "declaration.json",
            "model.npz",
            "native-folds.jsonl.zst",
            "validation-acoustic-ranks.jsonl.zst",
            "test-acoustic-ranks.jsonl.zst",
        ]
    ] + [metadata / n for n in ["tracks.jsonl.zst", "corpus-receipt.json"]]:
        if str(path.resolve()) not in spec["inputs"]:
            raise ValueError(
                "Diagnostic input or saved metric does not match its declared contract"
            )
    output.mkdir(parents=True, exist_ok=False)
    ledger, targets, support, popularity = _load_data(baseline, metadata)
    saved = json.loads((baseline / "evaluation.json").read_text())
    results = {}
    for fold, name in [(1, "validation"), (2, "test")]:
        sums, abst, hits, positive = _aggregate(baseline, name, fold, ledger, targets, popularity)
        ids = sorted(sums)
        a = np.array([sums[c] for c in ids])
        total = a.sum(axis=0)
        m = _metrics(total)
        _reproduce(saved, name, total, m, positive, hits, support, abst)
        out = summarize_components(ids, a, abst)
        results[name] = out
        _write_json(
            output,
            f"{name}-component-sufficient-statistics.json",
            {
                "columns": [
                    "queries",
                    "labeled_queries",
                    "source_positives",
                    "acoustic_hits10",
                    "popularity_hits10",
                    "acoustic_rr_sum",
                    "popularity_rr_sum",
                ],
                "rows": [{"component_id": c, "values": sums[c].tolist()} for c in ids],
            },
        )
    _verify(spec)
    result = {
        "revision": spec["revision"],
        "status": "pass",
        "declaration_sha256": hashlib.sha256(declaration.read_bytes()).hexdigest(),
        "analysis_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "results": results,
        "limits": spec["limits"],
        "elapsed_seconds": time.monotonic() - started,
        "peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
        "interpretation": spec["interpretation"],
    }
    _write_json(output, "results.json", result)
    return result


def _load_data(baseline: Path, metadata: Path) -> tuple[Any, ...]:  # noqa: C901
    ledger = {}
    cf = {}
    for row in _rows(baseline / "native-folds.jsonl.zst"):
        tid = row["track_id"]
        if not tid not in ledger:
            raise ValueError(
                "Diagnostic input or saved metric does not match its declared contract"
            )
        ledger[tid] = row
        c = row["component_id"]
        if c is not None:
            if row["fold"] not in (0, 1, 2):
                raise ValueError(
                    "Diagnostic input or saved metric does not match its declared contract"
                )
            if not cf.setdefault(c, row["fold"]) == row["fold"]:
                raise ValueError(
                    "Diagnostic input or saved metric does not match its declared contract"
                )
        elif row["fold"] != -1:
            raise ValueError(
                "Diagnostic input or saved metric does not match its declared contract"
            )
    targets = {}
    support = collections.Counter()
    for row in _rows(metadata / "tracks.jsonl.zst"):
        tid = row["track_id"]
        if not tid not in targets:
            raise ValueError(
                "Diagnostic input or saved metric does not match its declared contract"
            )
        labels = row["genre_ids"] or []
        if not len(labels) == len(set(labels)):
            raise ValueError(
                "Diagnostic input or saved metric does not match its declared contract"
            )
        targets[tid] = set(labels)
        if not row["artist_id"] == ledger[tid]["artist_id"]:
            raise ValueError(
                "Diagnostic input or saved metric does not match its declared contract"
            )
        if ledger[tid]["fold"] == 0 and ledger[tid]["artist_known"]:
            support.update(labels)
    if not targets.keys() == ledger.keys():
        raise ValueError("Diagnostic input or saved metric does not match its declared contract")
    popularity = sorted(support, key=lambda x: (-support[x], x))
    return (ledger, targets, support, popularity)


def _aggregate(  # noqa: PLR0913, PLR0917
    baseline: Path,
    name: str,
    fold: int,
    ledger: dict[Any, Any],
    targets: dict[Any, Any],
    popularity: list[int],
) -> tuple[Any, ...]:
    sums = collections.defaultdict(lambda: np.zeros(7, dtype=float))
    seen = set()
    abst = collections.Counter()
    hits = [collections.Counter(), collections.Counter()]
    positive = collections.Counter()
    for row in _rows(baseline / f"{name}-acoustic-ranks.jsonl.zst"):
        tid = row["track_id"]
        if not tid not in seen:
            raise ValueError(
                "Diagnostic input or saved metric does not match its declared contract"
            )
        seen.add(tid)
        identity = ledger[tid]
        if not (
            identity["fold"] == fold
            and identity["artist_known"]
            and (identity["component_id"] is not None)
        ):
            raise ValueError(
                "Diagnostic input or saved metric does not match its declared contract"
            )
        ranked = row["ranked_genre_ids"]
        if not len(ranked) == len(set(ranked)):
            raise ValueError(
                "Diagnostic input or saved metric does not match its declared contract"
            )
        if row["reason"] is not None:
            abst[row["reason"]] += 1
            if ranked:
                raise ValueError(
                    "Diagnostic input or saved metric does not match its declared contract"
                )
        pos = targets[tid]
        positive.update(pos)
        v = sums[identity["component_id"]]
        v[:3] += [1, bool(pos), len(pos)]
        for arm, ranks in enumerate([ranked, popularity]):
            found = pos.intersection(ranks[:10])
            hits[arm].update(found)
            v[3 + arm] += len(found)
            v[5 + arm] += next((1 / i for i, label in enumerate(ranks, 1) if label in pos), 0)
    if not seen == {
        t for t, identity in ledger.items() if identity["fold"] == fold and identity["artist_known"]
    }:
        raise ValueError("Diagnostic input or saved metric does not match its declared contract")
    return (sums, abst, hits, positive)


def _reproduce(  # noqa: PLR0913, PLR0917
    saved: dict[Any, Any],
    name: str,
    total: np.ndarray,
    m: np.ndarray,
    positive: dict[Any, Any],
    hits: list[dict[int, int]],
    support: dict[Any, Any],
    abst: dict[Any, Any],
) -> None:
    for arm, armname in enumerate(["acoustic", "popularity"]):
        expected = saved["evaluation"][name][armname]
        if not (
            int(total[0]) == expected["queries"]
            and int(total[1]) == expected["labeled_queries"]
            and (int(total[2]) == expected["source_positive_count"])
        ):
            raise ValueError(
                "Diagnostic input or saved metric does not match its declared contract"
            )
        if not abs(m[arm] - expected["recall_at_10"]) < REPLAY_TOLERANCE:
            raise ValueError(
                "Diagnostic input or saved metric does not match its declared contract"
            )
        if not abs(m[2 + arm] - expected["mean_reciprocal_rank"]) < REPLAY_TOLERANCE:
            raise ValueError(
                "Diagnostic input or saved metric does not match its declared contract"
            )
        for label in expected["per_label"]:
            g = label["genre_id"]
            if not label["held_out_positive_count"] == positive[g]:
                raise ValueError(
                    "Diagnostic input or saved metric does not match its declared contract"
                )
            if not label["hits_at_10"] == hits[arm][g]:
                raise ValueError(
                    "Diagnostic input or saved metric does not match its declared contract"
                )
            if not label["training_positive_count"] == support[g]:
                raise ValueError(
                    "Diagnostic input or saved metric does not match its declared contract"
                )
    if not dict(abst) == saved["evaluation"][name]["acoustic"]["abstentions"]:
        raise ValueError("Diagnostic input or saved metric does not match its declared contract")


def summarize_components(ids: list[int], a: np.ndarray, abst: dict[Any, Any]) -> dict[Any, Any]:
    """Compute paired whole-component diagnostics from seven sufficient statistics."""
    if (
        a.ndim != MIN_COMPONENTS
        or a.shape[1] != STAT_COLUMNS
        or len(ids) != len(a)
        or len(set(ids)) != len(ids)
    ):
        raise ValueError("Expected distinct components with seven sufficient statistics")
    if not np.isfinite(a).all() or (a < 0).any():
        raise ValueError("Invalid sufficient statistics")
    if (a[:, 1] > 0).sum() < MIN_COMPONENTS or (a[:, 2] > 0).sum() < MIN_COMPONENTS:
        raise ValueError("At least two labeled components required for deletion sensitivity")
    total = a.sum(axis=0)
    m = _metrics(total)
    rng = np.random.Generator(np.random.PCG64(20261015))
    boots = []
    omitted = 0
    for _ in range(2000):
        b = a[rng.integers(0, len(a), size=len(a))].sum(axis=0)
        if b[1] == 0 or b[2] == 0:
            omitted += 1
            continue
        v = _metrics(b)
        boots.append([*v, v[0] - v[1], v[2] - v[3]])
    ci = np.quantile(np.array(boots), [0.025, 0.975], axis=0)
    jack = []
    for i in range(len(a)):
        v = _metrics(total - a[i])
        jack.append([v[0] - v[1], v[2] - v[3]])
    jack = np.array(jack)
    keys = [
        "acoustic_recall10",
        "popularity_recall10",
        "acoustic_mrr",
        "popularity_mrr",
        "paired_recall10_difference",
        "paired_mrr_difference",
    ]
    point = [*m, m[0] - m[1], m[2] - m[3]]
    out = {
        "components": len(a),
        "queries": int(total[0]),
        "labeled_queries": int(total[1]),
        "source_positives": int(total[2]),
        "abstentions": dict(abst),
        "reproduction": (
            "Recall@10, MRR, per-label hits/support and denominators reproduce saved values"
        ),
        "metrics": {
            k: {
                "point": float(point[i]),
                "component_bootstrap_percentile95": [float(ci[0, i]), float(ci[1, i])],
            }
            for i, k in enumerate(keys)
        },
        "bootstrap_replicates": len(boots),
        "omitted_empty_denominator_replicates": omitted,
        "query_concentration": concentration(a[:, 0]),
        "positive_concentration": concentration(a[:, 2]),
        "component_equal": {},
        "leave_one_component_out": {},
    }
    for k, n, d in [
        ("acoustic_recall10", 3, 2),
        ("popularity_recall10", 4, 2),
        ("acoustic_mrr", 5, 1),
        ("popularity_mrr", 6, 1),
    ]:
        valid = a[:, d] > 0
        out["component_equal"][k] = {
            "mean": float(np.mean(a[valid, n] / a[valid, d])),
            "components_with_denominator": int(valid.sum()),
        }
    for j, k in enumerate(["paired_recall10_difference", "paired_mrr_difference"]):
        lo = int(np.argmin(jack[:, j]))
        hi = int(np.argmax(jack[:, j]))
        out["leave_one_component_out"][k] = {
            "min": float(jack[lo, j]),
            "min_deleted_component": ids[lo],
            "max": float(jack[hi, j]),
            "max_deleted_component": ids[hi],
        }
    out["largest_components_by_queries"] = [
        {"component_id": ids[i], "queries": int(a[i, 0]), "source_positives": int(a[i, 2])}
        for i in sorted(range(len(a)), key=lambda i: (-a[i, 0], ids[i]))[:10]
    ]
    return out


def _write_json(output: Path, name: str, value: dict[Any, Any]) -> None:
    payload = (json.dumps(value, indent=2) + "\n").encode()
    used = sum(p.stat().st_size for p in output.iterdir() if p.is_file())
    if used + len(payload) > MAX_OUTPUT_BYTES:
        raise ValueError("Diagnostic output exceeds declared byte limit")
    with (output / name).open("xb") as stream:
        stream.write(payload)
