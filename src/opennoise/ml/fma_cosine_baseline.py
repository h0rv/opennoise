"""Fixed directional positive-class comparator for the native FMA Gaussian baseline."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

from opennoise.ml.fma_acoustic_baseline import MAX_STANDARDIZED_OFFSET, MIN_LABEL_SUPPORT

if TYPE_CHECKING:
    from collections.abc import Mapping

MINIMUM_NORM = 1e-12


@dataclass(frozen=True)
class PositiveCosine:
    """Training-standardized class directions, never calibrated membership probabilities."""

    center: np.ndarray
    scale: np.ndarray
    active_columns: np.ndarray
    directions: np.ndarray
    active_labels: np.ndarray
    label_feature_support: np.ndarray
    labels: np.ndarray

    @classmethod
    def from_gaussian(cls, arrays: Mapping[str, np.ndarray]) -> PositiveCosine:
        """Recover positive means from already verified training-only sufficient statistics."""
        quadratic, linear = arrays["quadratic"], arrays["linear"]
        if (
            quadratic.shape != linear.shape
            or quadratic.ndim != 2  # noqa: PLR2004 - label-by-feature matrix.
            or not np.isfinite(quadratic).all()
            or not np.isfinite(linear).all()
            or not (quadratic < 0).all()
        ):
            raise ValueError("invalid Gaussian sufficient statistics")
        with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
            means = linear / (-2 * quadratic)
            norms = np.linalg.norm(means, axis=1)
        if not np.isfinite(means).all() or not np.isfinite(norms).all():
            raise ValueError("nonfinite recovered class directions")
        active = (arrays["label_feature_support"] >= MIN_LABEL_SUPPORT) & (norms > MINIMUM_NORM)
        directions = np.zeros_like(means)
        directions[active] = means[active] / norms[active, None]
        return cls(
            arrays["center"].copy(),
            arrays["scale"].copy(),
            arrays["active_columns"].copy(),
            directions,
            active,
            arrays["label_feature_support"].copy(),
            arrays["labels"].copy(),
        )

    def score(self, features: np.ndarray) -> tuple[np.ndarray, list[str | None]]:
        """Preserve missing/range abstention and additionally reject directionless queries."""
        selected = np.asarray(features[:, self.active_columns], dtype=np.float64)
        z = (selected - self.center[self.active_columns]) / self.scale[self.active_columns]
        complete = np.isfinite(z).all(axis=1)
        in_range = complete & (np.abs(z) <= MAX_STANDARDIZED_OFFSET).all(axis=1)
        norms = np.linalg.norm(np.where(in_range[:, None], z, 0), axis=1)
        supported = in_range & (norms > MINIMUM_NORM)
        scores = np.full((len(features), len(self.labels)), -np.inf)
        scores[supported] = (z[supported] / norms[supported, None]) @ self.directions.T
        scores[:, ~self.active_labels] = -np.inf
        reasons = [
            "missing_descriptors"
            if not complete[i]
            else "outside_training_support"
            if not in_range[i]
            else "zero_query_norm"
            if not supported[i]
            else "no_supported_prototypes"
            if not self.active_labels.any()
            else None
            for i in range(len(features))
        ]
        return scores, reasons
