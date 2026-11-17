import numpy as np
from scipy import sparse
from scipy.stats import rankdata

AXES = {
    "x": {"danceability": 1, "onset_rate": 1, "dynamic_complexity": -1},
    "y": {"mood_acoustic_acoustic": 1, "mood_electronic_electronic": -1},
}
FILL_NEIGHBORS = 10


def artist_axes(features, artists):
    columns = [c for axis in AXES.values() for c in axis]
    frame = artists.select("item").join(
        features.select("item", *columns),
        on="item",
        how="left",
        maintain_order="left",
        validate="1:1",
    )
    values = frame.select(columns).to_numpy().astype(float)
    present = np.isfinite(values).any(axis=1)
    points = np.zeros((len(artists), 2))
    if present.any():
        values = values[present]
        if not np.isfinite(values).any(axis=0).all():
            raise ValueError("Audio feature has no finite observations")
        values = np.where(np.isfinite(values), values, np.nan)
        values = np.where(np.isnan(values), np.nanmean(values, axis=0), values)
        values = (values - values.mean(0)) / np.maximum(values.std(0), 1e-9)
        for i, axis in enumerate(AXES.values()):
            points[present, i] = np.mean(
                [values[:, columns.index(c)] * sign for c, sign in axis.items()], axis=0
            )
    return points, present


def genre_axes(membership, points, present, listeners, min_members):
    membership = membership.tocsr(copy=True)
    membership.eliminate_zeros()
    bearing = (membership @ sparse.diags(np.asarray(present, dtype=float))).tocsr()
    bearing.eliminate_zeros()
    counts = np.diff(bearing.indptr)
    weighted = bearing @ sparse.diags(np.log(np.maximum(listeners, 2)))
    totals = np.asarray(weighted.sum(axis=1)).ravel()
    centers = (weighted @ points) / np.maximum(totals[:, None], 1e-12)
    return centers, (counts >= min_members) & (totals > 0), counts


def fill_artists(points, present, vectors):
    vectors = np.asarray(vectors, dtype=np.float32)
    norms = np.linalg.norm(vectors, axis=1)
    usable = np.isfinite(vectors).all(axis=1) & (norms > 0)
    donors = np.flatnonzero(present & usable)
    targets = np.flatnonzero(~present & usable)
    points, present = points.copy(), present.copy()
    k = min(FILL_NEIGHBORS, len(donors))
    if not k:
        return points, present
    unit = vectors / np.maximum(norms[:, None], 1e-12)
    for start in range(0, len(targets), 512):
        batch = targets[start : start + 512]
        similarities = unit[batch] @ unit[donors].T
        top = np.argpartition(-similarities, k - 1, axis=1)[:, :k]
        scores = np.take_along_axis(similarities, top, axis=1)
        order = np.argsort(-scores, axis=1, kind="stable")
        ids = donors[np.take_along_axis(top, order, axis=1)]
        weights = np.maximum(np.take_along_axis(scores, order, axis=1), 0)
        totals = weights.sum(axis=1)
        filled = totals > 0
        points[batch[filled]] = (points[ids[filled]] * weights[filled, :, None]).sum(
            axis=1
        ) / totals[filled, None]
        present[batch[filled]] = True
    return points, present


def rank_transform(reference, points):
    reference, points = np.asarray(reference), np.asarray(points)
    result = np.empty(points.shape, dtype=float)
    for axis in range(2):
        values, indices = np.unique(reference[:, axis], return_index=True)
        ranks = rankdata(reference[:, axis], method="average")[indices]
        if len(values) == 1:
            result[:, axis] = 0.5
        else:
            ranks = (ranks - ranks.min()) / (ranks.max() - ranks.min())
            result[:, axis] = np.interp(points[:, axis], values, ranks)
    return result


def project(artist_points, audio, artists, membership, min_members):
    genre_points, placed, counts = genre_axes(
        membership, artist_points, audio, artists["listeners"].to_numpy(), min_members
    )
    reference = genre_points[placed]
    if not len(reference):
        return np.empty((0, 2)), np.empty((0, 2)), placed, np.zeros_like(audio), counts
    return (
        rank_transform(reference, genre_points[placed]),
        rank_transform(reference, artist_points[audio]),
        placed,
        audio,
        counts,
    )
