import numpy as np
from scipy import sparse
from scipy.interpolate import RegularGridInterpolator
from scipy.linalg import orthogonal_procrustes
from scipy.ndimage import gaussian_filter
from scipy.stats import rankdata
from sklearn.preprocessing import normalize
from umap import UMAP

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


def repulsion_transform(fields, points):
    points = np.array(points, dtype=float, copy=True)
    if points.ndim != 2 or points.shape[1] != 2 or not np.isfinite(points).all():
        raise ValueError("Repulsion points must be a finite (n, 2) array")
    axis = np.linspace(0, 1, 33)
    for field in fields:
        if np.shape(field) != (33, 33, 2) or not np.isfinite(field).all():
            raise ValueError("Repulsion fields must be finite (33, 33, 2) arrays")
        velocity = RegularGridInterpolator((axis, axis), field)(np.clip(points, 0, 1))
        points = np.clip(points + velocity, 0, 1)
    return points


def fit_repulsion(points, steps):
    if not isinstance(steps, int) or steps < 0:
        raise ValueError("Repulsion steps must be a nonnegative integer")
    points = repulsion_transform([], points)
    if not len(points):
        raise ValueError("Repulsion needs training points")
    fields = []
    for _ in range(steps):
        histogram = np.histogram2d(points[:, 0], points[:, 1], bins=33, range=[[0, 1], [0, 1]])[0]
        density = gaussian_filter(histogram, 1.5, mode="reflect")
        gradient = np.stack(np.gradient(np.log(density + 0.1 * density.mean()), 1 / 32), axis=-1)
        velocity = -0.0002 * gradient
        velocity *= np.minimum(1, 0.004 / np.maximum(np.linalg.norm(velocity, axis=-1), 1e-12))[
            ..., None
        ]
        velocity[0, :, 0] = velocity[-1, :, 0] = 0
        velocity[:, 0, 1] = velocity[:, -1, 1] = 0
        fields.append(velocity)
        points = repulsion_transform([velocity], points)
    return fields


def fit(vectors, audio, train, config):
    if train.sum() < 3:
        raise ValueError("Sonic UMAP needs at least three training genres")
    model = UMAP(
        n_neighbors=config["sonic_neighbors"],
        min_dist=config["sonic_min_dist"],
        n_epochs=config.get("sonic_epochs", config["umap_epochs"]),
        metric="cosine",
        init="spectral",
        random_state=config["seed"],
        n_jobs=1,
        compatibility_layout=True,
    )
    points = np.empty((len(vectors), 2))
    points[train] = model.fit_transform(vectors[train])
    center = points[train].mean(0)
    rotation, _ = orthogonal_procrustes(points[train] - center, audio[train] - audio[train].mean(0))
    if (~train).any():
        points[~train] = model.transform(vectors[~train])
    points = (points - center) @ rotation
    state = {"model": model, "center": center, "rotation": rotation, "reference": points[train]}
    ranked = rank_transform(state["reference"], points)
    state["repulsion"] = fit_repulsion(ranked[train], config.get("sonic_repulsion_steps", 0))
    return state, repulsion_transform(state["repulsion"], ranked)


def transform(state, vectors):
    if not len(vectors):
        return np.empty((0, 2))
    points = (state["model"].transform(vectors) - state["center"]) @ state["rotation"]
    return repulsion_transform(
        state.get("repulsion", []), rank_transform(state["reference"], points)
    )


def place(state, membership, vectors, min_members):
    matrix = membership.tocsr(copy=True)
    matrix.eliminate_zeros()
    centers = normalize(matrix @ np.asarray(vectors, dtype=float))
    counts = np.diff(matrix.indptr)
    placed = (counts >= min_members) & (np.linalg.norm(centers, axis=1) > 0)
    return transform(state, centers[placed]), placed, counts
