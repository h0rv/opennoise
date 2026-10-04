"""Separate training-component calibration; inspected outer folds are diagnostics only."""

from __future__ import annotations

import hashlib
from typing import Any

from opennoise.ml.fma_memberships import MIN_COMPONENTS, component_threshold, suggest

REVISION = "fma-training-component-memberships-v1"
ROLE_SEED = "opennoise-fma-training-only-membership-roles-v1"
DECLARATION_SHA256 = "5697578e85b92f355020edb56b9351583c9e10208f8fe99ec3782d930801ef09"


def role(fold: int, component: int | None, *, artist_known: bool) -> str:
    """Assign whole original training components without reading labels, features or sizes."""
    if not artist_known:
        return "unresolved_artist"
    if type(component) is not int or component <= 0 or fold not in (0, 1, 2):
        raise ValueError("known artist requires native component and original fold")
    if fold:
        return "validation_diagnostic" if fold == 1 else "test_diagnostic"
    bucket = (
        int.from_bytes(hashlib.sha256(f"{ROLE_SEED}\0{component}".encode()).digest(), "big") % 5
    )
    return "inner_calibration" if bucket == 0 else "inner_fit"


def fit_thresholds(rows: list[dict[str, Any]], labels: list[int]) -> dict[int, dict[str, Any]]:
    """Reject all nontraining or incorrectly assigned rows; retain missing positive ranks."""
    observations: dict[int, dict[int, int]] = {label: {} for label in labels}
    seen = set()
    for row in rows:
        if (
            row["role"] != "inner_calibration"
            or role(row["fold"], row["component_id"], artist_known=row["artist_known"])
            != "inner_calibration"
            or row["track_id"] in seen
        ):
            raise ValueError("non-calibration or repeated query entered threshold fitting")
        seen.add(row["track_id"])
        ranks = {label: i + 1 for i, label in enumerate(row["ranked_genre_ids"])}
        for label in row["genre_ids"] or []:
            value = ranks.get(label, len(labels) + 1)
            previous = observations[label].get(row["component_id"], 0)
            observations[label][row["component_id"]] = max(value, previous)
    result = {}
    for label, values in observations.items():
        threshold = component_threshold(list(values.values()), len(labels))
        result[label] = {
            "threshold_rank": threshold,
            "positive_components": len(values),
            "component_worst_positive_ranks": sorted(values.values()),
            "abstention": "insufficient_calibration_components"
            if len(values) < MIN_COMPONENTS
            else "unsupported_positive_rank_tail"
            if threshold is None
            else None,
        }
    return result


def training_suggest(row: dict[str, Any], thresholds: dict[int, dict[str, Any]]) -> dict[str, Any]:
    """Keep historical suggestions, but bound stability against every potential entrant."""
    output = suggest(row, thresholds)
    output["namespace"] = REVISION
    selected = {item["genre_id"] for item in output["memberships"]}
    # Include labels currently outside their threshold that could enter after rank -2.
    competitors = [
        max(1, rank - 2) / threshold
        for rank, label in enumerate(row["ranked_genre_ids"], 1)
        if label not in selected
        and (threshold := thresholds[label]["threshold_rank"]) is not None
        and max(1, rank - 2) <= threshold
    ]
    for item in output["memberships"]:
        item["set_stable_under_plus_minus_2_rank"] = item[
            "threshold_stable_under_plus_minus_2_rank"
        ] and (item["raw_acoustic_rank"] + 2) / item["calibration_threshold_rank"] < min(
            competitors, default=float("inf")
        )
    output["set_stability_is_conservative_sufficient_condition"] = True
    return output
