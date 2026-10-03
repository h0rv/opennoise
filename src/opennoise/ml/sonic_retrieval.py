"""Training-only numeric retrieval, distinct from independently judged music relevance."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

import numpy as np

if TYPE_CHECKING:
    from collections.abc import Sequence

QUERY_BATCH_ROWS = 1024


@dataclass(frozen=True)
class NumericIndex:
    """Finite training descriptors and their train-fitted normalization."""

    identities: np.ndarray
    components: np.ndarray
    normalized: np.ndarray
    center: np.ndarray
    scale: np.ndarray
    active: np.ndarray


def freeze_queries(identities: Sequence[int], seed: str, limit: int) -> list[int]:
    """Select identities without inspecting descriptors, targets or model scores."""
    if (
        len(set(identities)) != len(identities)
        or any(type(identity) is not int or identity <= 0 for identity in identities)
        or limit <= 0
        or not seed
    ):
        raise ValueError("query roster requires unique IDs, a seed and positive limit")
    return sorted(
        identities,
        key=lambda identity: (hashlib.sha256(f"{seed}\0{identity}".encode()).digest(), identity),
    )[:limit]


def fit_index(
    identities: np.ndarray, components: np.ndarray, features: np.ndarray, training: np.ndarray
) -> NumericIndex:
    """Fit normalization only on finite training rows; reject incomplete input contracts."""
    if (
        features.ndim != 2  # noqa: PLR2004 - descriptor matrix has exactly two dimensions.
        or len(identities) != len(features)
        or len(components) != len(features)
        or training.shape != (len(features),)
        or training.dtype != bool
        or identities.dtype.kind not in "iu"
        or components.dtype.kind not in "iu"
        or (identities <= 0).any()
        or len(set(identities.tolist())) != len(identities)
    ):
        raise ValueError("numeric index identity/feature/training shapes differ")
    eligible = training & np.isfinite(features).all(axis=1) & (components > 0)
    if not eligible.any():
        raise ValueError("no finite training rows with resolved components")
    values = np.asarray(features[eligible], dtype=np.float64)
    with np.errstate(over="ignore", invalid="ignore"):
        center, scale = values.mean(axis=0), values.std(axis=0)
    if not np.isfinite(center).all() or not np.isfinite(scale).all():
        raise ValueError("training normalization overflows finite numeric support")
    active = scale > 0
    if not active.any():
        raise ValueError("training descriptors contain no varying dimensions")
    return NumericIndex(
        identities[eligible],
        components[eligible],
        (values[:, active] - center[active]) / scale[active],
        center,
        scale,
        active,
    )


def nearest(
    index: NumericIndex,
    query: np.ndarray,
    component: int,
    *,
    limit: int = 10,
    max_offset: float = 12,
) -> tuple[list[int], list[float], str | None]:
    """Return cross-component nearest training rows with deterministic exact tie ordering."""
    if query.shape != index.center.shape or limit <= 0 or max_offset <= 0:
        raise ValueError("numeric query shape or bounds differ")
    if component <= 0:
        return [], [], "unresolved_component"
    if not np.isfinite(query).all():
        return [], [], "missing_descriptors"
    normalized = (query[index.active] - index.center[index.active]) / index.scale[index.active]
    if np.abs(normalized).max() > max_offset:
        return [], [], "outside_training_support"
    mask = index.components != component
    if not mask.any():
        return [], [], "no_cross_component_candidates"
    identities = index.identities[mask]
    positions = np.flatnonzero(mask)
    distances = np.empty(len(positions), dtype=np.float64)
    for offset in range(0, len(positions), QUERY_BATCH_ROWS):
        selected = positions[offset : offset + QUERY_BATCH_ROWS]
        distances[offset : offset + len(selected)] = np.sum(
            (index.normalized[selected] - normalized) ** 2, axis=1
        )
    # Full stable ordering avoids argpartition ties depending on memory layout.
    order = np.lexsort((identities, distances))[:limit]
    return (
        cast("list[int]", identities[order].astype(int).tolist()),
        cast("list[float]", np.sqrt(distances[order]).tolist()),
        None,
    )


def source_overlap(
    query_labels: Sequence[int], neighbor_labels: Sequence[Sequence[int]]
) -> dict[str, object]:
    """Measure observed annotation recovery; absence is never a musical negative."""
    target = set(query_labels)
    union = {label for labels in neighbor_labels for label in labels}
    recovered = len(target & union)
    return {
        "observed_positives": len(target),
        "recovered_positives": recovered,
        "any_observed_overlap": bool(recovered),
        "neighbors_with_unknown_annotations": sum(not labels for labels in neighbor_labels),
        "musical_precision_available": False,
    }
