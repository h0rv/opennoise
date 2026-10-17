"""Paired descriptive counts for the fixed second-representative experiment."""

from __future__ import annotations

from collections import Counter
from math import isfinite
from typing import Any

from opennoise.ml.fma_retrieval_loss import BUCKETS

RECOVERED = 4

ARMS = ("raw44_neighbors", "two_representatives", "recording_popularity")
METRICS = (
    "queries",
    "labeled_queries",
    "positives",
    "hits10",
    "rr_sum",
    "descriptor_queries",
    "neighbor_queries",
    "ranking_queries",
)


def bucket(
    label: int, pool: set[int], selected: set[int], ranking: list[int], reason: str | None
) -> int:
    """Assign one observed positive to its ordered, noncausal loss category."""
    if reason is not None:
        return 0
    if label not in pool:
        return 1
    if label not in selected:
        return 2
    return 4 if label in ranking[:10] else 3


def empty_component(component: int, fold: int) -> dict[str, Any]:
    """Allocate paired counts without filtering unlabeled or unsupported queries."""
    return {
        "component_id": component,
        "fold": fold,
        "statistics": [[0.0] * len(METRICS) for _ in ARMS],
        "buckets": [[0] * 5 for _ in range(2)],
        "transitions": [[0] * 5 for _ in range(5)],
        "new_recovered_old_pool": 0,
        "new_recovered_added_pool": 0,
        "gained_old_pool": 0,
        "gained_added_pool": 0,
        "lost_hits": 0,
        "selected_records": [{}, {}],
        "selected_components": [{}, {}],
        "selected_label_counts": [{}, {}],
    }


def accumulate(  # noqa: PLR0913, PLR0917 - paired data dimensions.
    component: dict[str, Any],
    positives: set[int],
    predictions: list[dict[str, Any]],
    pools: list[set[int]],
    labels: dict[int, set[int]],
    groups: dict[int, int],
) -> None:
    """Accumulate exact paired source-positive transitions and full-denominator metrics."""
    selected = []
    for index, prediction in enumerate(predictions):
        ranking = prediction["ranking"]
        neighbors = prediction.get("neighbor_ids", [])
        selected.append(set[int]().union(*(labels[track] for track in neighbors)))
        if index < len(ARMS) - 1:
            for track in neighbors:
                for field, key in [
                    ("selected_records", track),
                    ("selected_components", groups[track]),
                    ("selected_label_counts", len(labels[track])),
                ]:
                    counts = component[field][index]
                    counts[str(key)] = counts.get(str(key), 0) + 1
        reciprocal = next(
            (1 / rank for rank, label in enumerate(ranking, 1) if label in positives), 0
        )
        values = [
            1,
            bool(positives),
            len(positives),
            len(positives.intersection(ranking[:10])),
            reciprocal,
            prediction["descriptor_available"],
            bool(neighbors),
            bool(ranking),
        ]
        component["statistics"][index] = [
            a + b for a, b in zip(component["statistics"][index], values, strict=True)
        ]
    for label in sorted(positives):
        states = [
            bucket(
                label,
                pools[index],
                selected[index],
                predictions[index]["ranking"],
                predictions[index]["reason"],
            )
            for index in range(2)
        ]
        for index, state in enumerate(states):
            component["buckets"][index][state] += 1
        old, new = states
        component["transitions"][old][new] += 1
        if new == RECOVERED:
            suffix = "old_pool" if label in pools[0] else "added_pool"
            component["new_recovered_" + suffix] += 1
            if old != RECOVERED:
                component["gained_" + suffix] += 1
        elif old == RECOVERED:
            component["lost_hits"] += 1


def validate_component(row: dict[str, Any]) -> None:
    """Conserve each paired denominator, loss partition and recovered-label split."""
    stats, bins, transitions = row["statistics"], row["buckets"], row["transitions"]
    if len(stats) != len(ARMS) or any(len(values) != len(METRICS) for values in stats):
        raise ValueError("Component statistics schema differs")
    if any(not isfinite(value) or value < 0 for values in stats for value in values):
        raise ValueError("Invalid sufficient statistics")
    if (
        len(bins) != len(ARMS) - 1
        or any(len(values) != len(BUCKETS) for values in bins)
        or len(transitions) != len(BUCKETS)
        or any(len(values) != len(BUCKETS) for values in transitions)
    ):
        raise ValueError("Loss array shape differs")
    if any(
        type(value) is not int or value < 0 for values in [*bins, *transitions] for value in values
    ):
        raise ValueError("Loss counts must be nonnegative integers")
    if any(values[:3] != stats[0][:3] for values in stats):
        raise ValueError("Paired query and positive denominators differ")
    positives = stats[0][2]
    if any(
        sum(values) != positives or values[4] != stats[index][3]
        for index, values in enumerate(bins)
    ):
        raise ValueError("Loss buckets do not conserve")
    if [sum(values) for values in transitions] != bins[0] or [
        sum(values[index] for values in transitions) for index in range(5)
    ] != bins[1]:
        raise ValueError("Paired transitions do not conserve")
    if (
        row["new_recovered_old_pool"] + row["new_recovered_added_pool"] != stats[1][3]
        or row["gained_old_pool"] + row["gained_added_pool"] - row["lost_hits"]
        != stats[1][3] - stats[0][3]
    ):
        raise ValueError("Recovered-label transition split differs")


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Report descriptive pooled and component-equal rates with undefined ratios null."""
    for row in rows:
        validate_component(row)
    arms = {}
    for index, arm in enumerate(ARMS):
        totals = [sum(row["statistics"][index][col] for row in rows) for col in range(len(METRICS))]
        labeled = [row for row in rows if row["statistics"][index][1]]
        positive = [row for row in rows if row["statistics"][index][2]]
        value = {
            "totals": dict(zip(METRICS, totals, strict=True)),
            "positive_recall10": totals[3] / totals[2] if totals[2] else None,
            "query_mrr": totals[4] / totals[1] if totals[1] else None,
            "component_equal_recall10": sum(
                row["statistics"][index][3] / row["statistics"][index][2] for row in positive
            )
            / len(positive)
            if positive
            else None,
            "component_equal_mrr": sum(
                row["statistics"][index][4] / row["statistics"][index][1] for row in labeled
            )
            / len(labeled)
            if labeled
            else None,
            "positive_components": len(positive),
            "labeled_components": len(labeled),
        }
        if index < len(ARMS) - 1:
            for field in ("selected_records", "selected_components", "selected_label_counts"):
                counts: Counter[int] = Counter()
                for row in rows:
                    counts.update({int(key): count for key, count in row[field][index].items()})
                value[field] = (
                    concentration(dict(counts))
                    if field != "selected_label_counts"
                    else [[key, count] for key, count in sorted(counts.items())]
                )
            bins = [sum(row["buckets"][index][col] for row in rows) for col in range(5)]
            value.update(
                buckets=dict(zip(BUCKETS, bins, strict=True)),
                positive_fractions=[count / totals[2] for count in bins] if totals[2] else None,
                component_equal_fractions=[
                    sum(
                        row["buckets"][index][col] / row["statistics"][index][2] for row in positive
                    )
                    / len(positive)
                    for col in range(5)
                ]
                if positive
                else None,
            )
        arms[arm] = value
    return {
        "components": len(rows),
        "arms": arms,
        "transitions": [
            [sum(row["transitions"][old][new] for row in rows) for new in range(5)]
            for old in range(5)
        ],
        **{
            key: sum(row[key] for row in rows)
            for key in (
                "new_recovered_old_pool",
                "new_recovered_added_pool",
                "gained_old_pool",
                "gained_added_pool",
                "lost_hits",
            )
        },
    }


def concentration(counts: dict[int, int]) -> dict[str, Any]:
    """Describe use concentration without interpreting it as independent musical evidence."""
    total = sum(counts.values())
    return {
        "slots": total,
        "distinct_ids": len(counts),
        "largest_share": max(counts.values()) / total if total else None,
        "top100_share": sum(sorted(counts.values(), reverse=True)[:100]) / total if total else None,
        "inverse_herfindahl": total * total / sum(count * count for count in counts.values())
        if total
        else None,
        "herfindahl": sum((count / total) ** 2 for count in counts.values()) if total else None,
    }


def label_histogram(ids: list[int], labels: dict[int, set[int]]) -> list[list[int]]:
    """Preserve the distribution of observed annotation counts, including empty records."""
    return [
        [size, count]
        for size, count in sorted(Counter(len(labels[track]) for track in ids).items())
    ]
