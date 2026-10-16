"""Fixed-prediction component summaries and paired descriptive bootstrap intervals."""

from __future__ import annotations

from typing import Any

import numpy as np

ARMS = ("recording_gaussian", "component_gaussian", "recording_popularity")
COLUMNS = (
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
METRICS = (
    "positive_recall10",
    "query_mrr",
    "positive_weighted_mrr",
    "query_coverage",
    "positive_coverage",
    "label_support_ceiling",
    "joint_support_ceiling",
    "labeled_query_coverage",
    "component_mean_recall10",
    "component_mean_mrr",
    "component_mean_coverage",
)
PAIRS = ((1, 0), (0, 2), (1, 2))
DRAWS = 2000
SEED = 20261016


def ratios(numerator: np.ndarray, denominator: np.ndarray) -> np.ndarray:
    """Keep zero denominators undefined, including an entirely unlabeled cohort."""
    return np.divide(
        numerator,
        denominator,
        out=np.full_like(numerator, np.nan, dtype=float),
        where=denominator > 0,
    )


def metrics(stats: np.ndarray) -> np.ndarray:
    """Calculate pooled ratios of sums and separately equal-component means."""
    totals = stats.sum(axis=0)
    pooled = ratios(totals[:, [3, 4, 5, 6, 7, 8, 9, 10]], totals[:, [2, 1, 2, 0, 2, 2, 2, 1]])
    component = ratios(stats[:, :, [3, 4, 6]], stats[:, :, [2, 1, 0]])
    valid = np.isfinite(component)
    means = ratios(np.where(valid, component, 0).sum(axis=0), valid.sum(axis=0))
    return np.concatenate((pooled, means), axis=1)


def nullable(value: float) -> float | None:
    """Use JSON null, never NaN, for an undefined estimand."""
    return float(value) if np.isfinite(value) else None


def arm_summary(stats: np.ndarray) -> dict[str, Any]:
    """Preserve denominator totals and the number of defined component rates."""
    values = metrics(stats)
    totals = stats.sum(axis=0)
    return {
        name: {
            "totals": dict(zip(COLUMNS, totals[i].tolist(), strict=True)),
            "metrics": {
                metric: nullable(value) for metric, value in zip(METRICS, values[i], strict=True)
            },
            "components": len(stats),
            "defined_recall_components": int(np.count_nonzero(stats[:, i, 2])),
            "defined_mrr_components": int(np.count_nonzero(stats[:, i, 1])),
            "defined_coverage_components": int(np.count_nonzero(stats[:, i, 0])),
        }
        for i, name in enumerate(ARMS)
    }


def validate_stats(stats: np.ndarray) -> None:
    """Reject incompatible paired denominators and impossible counts."""
    if stats.ndim != len(("component", "arm", "statistic")) or stats.shape[1:] != (
        len(ARMS),
        len(COLUMNS),
    ):
        raise ValueError("component statistics shape differs")
    if not np.isfinite(stats).all() or np.any(stats < 0):
        raise ValueError("component statistics must be finite and nonnegative")
    if not np.array_equal(stats[:, :, :3], np.repeat(stats[:, :1, :3], len(ARMS), axis=1)):
        raise ValueError("paired arms must share query and positive denominators")
    if np.any(stats[:, :, 1] > stats[:, :, 0]) or np.any(stats[:, :, 2] < stats[:, :, 1]):
        raise ValueError("query and positive denominator bounds differ")
    for numerator, denominator in (
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
    ):
        if np.any(stats[:, :, numerator] > stats[:, :, denominator] + 1e-9):
            raise ValueError("component numerator exceeds its denominator")


def summarize(stats: np.ndarray, *, bootstrap: bool = True) -> dict[str, Any]:
    """Summarize components supplied in ascending native-ID order without refitting.

    The caller retains the native IDs in that same order. The largest component's
    zero-based index identifies it without inventing an ID or dropping any row.
    """
    stats = np.asarray(stats, dtype=float)
    validate_stats(stats)
    count = len(stats)
    largest = int(np.argmax(stats[:, 0, 0])) if count else None
    result: dict[str, Any] = {
        "arms": arm_summary(stats),
        "largest_query_component": None
        if largest is None
        else {
            "component_index": largest,
            "arms": arm_summary(stats[largest : largest + 1]),
        },
        "paired_bootstrap": None,
    }
    if not bootstrap:
        return result
    rng = np.random.Generator(np.random.PCG64(SEED))
    samples = np.full((DRAWS, len(PAIRS), len(METRICS)), np.nan)
    for draw in range(DRAWS):
        indices = rng.integers(0, count, size=count) if count else np.array([], dtype=int)
        values = metrics(stats[indices])
        for pair, (left, right) in enumerate(PAIRS):
            samples[draw, pair] = values[left] - values[right]
    point = metrics(stats)
    comparisons = {}
    for pair, (left, right) in enumerate(PAIRS):
        values = {}
        for index, metric in enumerate(METRICS):
            finite = samples[:, pair, index][np.isfinite(samples[:, pair, index])]
            values[metric] = {
                "difference": nullable(point[left, index] - point[right, index]),
                "interval": np.quantile(finite, [0.025, 0.975], method="linear").tolist()
                if len(finite)
                else None,
                "valid_draws": len(finite),
                "undefined_draws": DRAWS - len(finite),
            }
        comparisons[f"{ARMS[left]}_minus_{ARMS[right]}"] = values
    result["paired_bootstrap"] = {
        "draws": DRAWS,
        "seed": SEED,
        "rng": "PCG64",
        "sampling": (
            "Draw-by-draw integers(0,C,size=C) over ascending native component IDs; paired arms"
        ),
        "quantile_method": "linear",
        "interpretation": (
            "Descriptive fixed-prediction resampling; no refit or population confidence claim"
        ),
        "comparisons": comparisons,
    }
    return result
