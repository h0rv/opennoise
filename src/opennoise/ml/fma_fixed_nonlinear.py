"""Fixed, streamed component-weighted linear and random Fourier ridge encoders."""

from dataclasses import dataclass

import numpy as np
from scipy import sparse

from opennoise.ml import fma_acoustic_baseline as baseline
from opennoise.ml import fma_component_balanced as balanced
from opennoise.ml.fma_component_embedding import compressed_encoder

BATCH = 512
DIMENSIONS = 128
SEED = 20261017
BANDWIDTH_PAIRS = 2048


@dataclass
class FixedEncoder:
    """All train-derived state needed for feature-only inference."""

    center: np.ndarray
    scale: np.ndarray
    active_columns: np.ndarray
    frequencies: np.ndarray
    phases: np.ndarray
    bandwidth: np.ndarray
    map_center: np.ndarray
    active_labels: np.ndarray
    target_mean: np.ndarray
    coefficients: np.ndarray
    singular_values: np.ndarray
    encoder: np.ndarray


def _map(z: np.ndarray, frequencies: np.ndarray, phases: np.ndarray) -> np.ndarray:
    return np.sqrt(2.0) * np.cos(z @ frequencies + phases) if phases.size else z


def fit_encoder(  # noqa: C901, PLR0915 - streamed fixed sufficient-statistic fit.
    features: np.ndarray,
    targets: sparse.csr_matrix,
    training: np.ndarray,
    groups: np.ndarray,
    *,
    nonlinear: bool,
) -> FixedEncoder:
    """Fit one fixed arm without reading heldout values, labels, or groups."""
    if (
        features.ndim != 2  # noqa: PLR2004 - matrix dimensionality.
        or training.dtype != np.bool_
        or training.shape != (len(features),)
        or groups.shape != training.shape
        or targets.shape[0] != len(features)
    ):
        raise ValueError("Unaligned fit inputs")
    rows = np.flatnonzero(training)
    rows = np.concatenate(
        [
            part[np.isfinite(features[part]).all(axis=1)]
            for part in np.array_split(rows, max(1, (len(rows) + BATCH - 1) // BATCH))
        ]
    )
    if len(rows) < baseline.MIN_LABEL_SUPPORT:
        raise ValueError("Insufficient finite fit rows")
    weights = balanced.equal_component_weights(groups[rows])
    weights /= weights.sum()
    center = np.zeros(features.shape[1])
    minimum, maximum = np.full_like(center, np.inf), np.full_like(center, -np.inf)
    for start in range(0, len(rows), BATCH):
        ix = rows[start : start + BATCH]
        x = np.asarray(features[ix], dtype=np.float64)
        center += weights[start : start + BATCH] @ x
        minimum, maximum = np.minimum(minimum, x.min(axis=0)), np.maximum(maximum, x.max(axis=0))
    variance = np.zeros_like(center)
    for start in range(0, len(rows), BATCH):
        x = np.asarray(features[rows[start : start + BATCH]], dtype=np.float64)
        variance += weights[start : start + BATCH] @ ((x - center) ** 2)
    scale = np.sqrt(variance)
    active = (scale > 0) & (maximum > minimum)
    if not active.any() or not np.isfinite(center).all() or not np.isfinite(scale).all():
        raise ValueError("Invalid fit normalization")
    dimensions = int(active.sum())
    rng = np.random.Generator(np.random.PCG64(SEED))
    bandwidth = 0.0
    frequencies, phases = np.zeros((dimensions, 0)), np.zeros(0)
    if nonlinear:
        left = rng.choice(len(rows), size=BANDWIDTH_PAIRS, p=weights)
        right = rng.choice(len(rows), size=BANDWIDTH_PAIRS, p=weights)
        a = np.asarray(features[rows[left]][:, active], dtype=np.float64)
        b = np.asarray(features[rows[right]][:, active], dtype=np.float64)
        distance = np.linalg.norm((a - b) / scale[active], axis=1)
        positive = distance[distance > 0]
        if not len(positive):
            raise ValueError("No positive training bandwidth distances")
        bandwidth = float(np.median(positive))
        frequencies = rng.standard_normal((dimensions, DIMENSIONS)) / bandwidth
        phases = rng.uniform(0, 2 * np.pi, DIMENSIONS)
    width = DIMENSIONS if nonlinear else dimensions
    support = np.asarray(targets[rows].sum(axis=0)).ravel()
    active_labels = support >= baseline.MIN_LABEL_SUPPORT
    target_mean = np.zeros(int(active_labels.sum()))
    map_center = np.zeros(width)
    gram, cross = np.zeros((width, width)), np.zeros((width, len(target_mean)))
    for start in range(0, len(rows), BATCH):
        ix = rows[start : start + BATCH]
        w = weights[start : start + BATCH]
        x = np.asarray(features[ix][:, active], dtype=np.float64)
        phi = _map((x - center[active]) / scale[active], frequencies, phases)
        y = targets[ix][:, active_labels].toarray()
        if not np.isin(y, [0, 1]).all():
            raise ValueError("Source targets must be binary")
        map_center += w @ phi
        target_mean += w @ y
        gram += phi.T @ (w[:, None] * phi)
        cross += phi.T @ (w[:, None] * y)
    gram -= np.outer(map_center, map_center)
    cross -= np.outer(map_center, target_mean)
    cross[:, support[active_labels] == len(rows)] = 0
    coefficients = np.linalg.solve(gram + np.eye(width), cross)
    if not np.isfinite(coefficients).all():
        raise ValueError("Nonfinite ridge coefficients")
    encoder, singular = compressed_encoder(coefficients)
    return FixedEncoder(
        center,
        scale,
        active,
        frequencies,
        phases,
        np.asarray(bandwidth),
        map_center,
        active_labels,
        target_mean,
        coefficients,
        singular,
        encoder,
    )


def transform(model: FixedEncoder, features: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Apply saved state; unsupported queries stay zero and in metric denominators."""
    z = (
        np.asarray(features[:, model.active_columns], dtype=np.float64)
        - model.center[model.active_columns]
    ) / model.scale[model.active_columns]
    eligible = np.isfinite(features).all(axis=1) & (
        np.abs(z) <= baseline.MAX_STANDARDIZED_OFFSET
    ).all(axis=1)
    phi = _map(np.where(eligible[:, None], z, 0), model.frequencies, model.phases)
    vector = (phi - model.map_center) @ model.encoder
    norm = np.linalg.norm(vector, axis=1)
    eligible &= np.isfinite(norm) & (norm > 0)
    return np.divide(
        vector, norm[:, None], out=np.zeros_like(vector), where=eligible[:, None]
    ), eligible
