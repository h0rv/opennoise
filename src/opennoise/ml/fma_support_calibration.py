"""Experimental descriptor coverage calibration; existing support defaults stay fixed."""

import hashlib

import numpy as np

from opennoise.ml.fma_fixed_nonlinear import FixedEncoder

LEVELS = (0.90, 0.95, 0.99)
SPLIT_DOMAIN = "fma-support-calibration-v1"


def calibration_mask(groups: np.ndarray) -> np.ndarray:
    """Reserve whole components by a fixed label-independent one-in-five hash."""
    selected = {
        int(g): int.from_bytes(hashlib.sha256(f"{SPLIT_DOMAIN}\0{int(g)}".encode()).digest(), "big")
        % 5
        == 0
        for g in np.unique(groups)
    }
    return np.array([selected[int(g)] for g in groups], dtype=bool)


def descriptor_state(
    model: FixedEncoder, features: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return max-coordinate scores and ungated linear vectors; never change default inference."""
    if model.phases.size:
        raise ValueError("Only predeclared linear encoders are supported")
    z = (
        np.asarray(features[:, model.active_columns], dtype=np.float64)
        - model.center[model.active_columns]
    ) / model.scale[model.active_columns]
    finite = np.isfinite(features).all(axis=1) & np.isfinite(z).all(axis=1)
    score = np.max(np.abs(z), axis=1)
    score[~finite] = np.inf
    vector = (np.where(finite[:, None], z, 0) - model.map_center) @ model.encoder
    norm = np.linalg.norm(vector, axis=1)
    valid = finite & np.isfinite(norm) & (norm > 0)
    vector = np.divide(vector, norm[:, None], out=np.zeros_like(vector), where=valid[:, None])
    return score, vector, valid


def component_quantiles(scores: np.ndarray, groups: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Smallest observed scores meeting fixed weighted empirical acceptance levels."""
    if (
        scores.ndim != 1
        or groups.shape != scores.shape
        or not len(scores)
        or not np.isfinite(scores).all()
    ):
        raise ValueError("Nonempty finite calibration scores and aligned components required")
    _, inverse, counts = np.unique(groups, return_inverse=True, return_counts=True)
    weights = 1.0 / counts[inverse]
    weights /= weights.sum()
    order = np.argsort(scores, kind="stable")
    cumulative = np.cumsum(weights[order])
    thresholds = np.array(
        [
            scores[order[min(int(np.searchsorted(cumulative, q, side="left")), len(order) - 1)]]
            for q in LEVELS
        ]
    )
    return thresholds, weights
