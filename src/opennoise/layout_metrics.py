import numpy as np
from scipy.spatial.distance import cdist
from scipy.stats import spearmanr


def nearest(points, k=10, metric="euclidean"):
    points = np.asarray(points)
    if k < 1:
        raise ValueError("k must be positive")
    if points.ndim != 2 or not np.isfinite(points).all():
        raise ValueError("points must be a finite matrix")
    distances = cdist(points, points, metric=metric)
    np.fill_diagonal(distances, np.inf)
    return np.argsort(distances, axis=1, kind="stable")[:, : min(k, max(0, len(points) - 1))]


def neighbor_overlap(points, reference, k=10, reference_metric="euclidean"):
    if len(points) != len(reference):
        raise ValueError("point counts differ")
    predicted = nearest(points, k)
    expected = nearest(reference, k, reference_metric)
    if not predicted.size:
        return None
    return float(
        np.mean(
            [
                len(set(a) & set(b)) / predicted.shape[1]
                for a, b in zip(predicted, expected, strict=True)
            ]
        )
    )


def layout_scores(points, reference, vectors, total_test, axes=True):
    if total_test < len(points) or total_test < 0:
        raise ValueError("total_test is smaller than placed test set")
    scores = {
        "neighbor_overlap@10": neighbor_overlap(points, reference),
        "vector_overlap@10": neighbor_overlap(points, vectors, reference_metric="cosine"),
        "coverage": len(points) / total_test if total_test else 0.0,
        "placed": len(points),
        "total": total_test,
    }
    if axes:
        for i, axis in enumerate(["x", "y"]):
            value = None
            if len(points) > 1 and np.ptp(points[:, i]) and np.ptp(reference[:, i]):
                value = float(spearmanr(points[:, i], reference[:, i])[0])
            scores[f"spearman_{axis}"] = value
    return scores


def evaluation_scores(points, reference, vectors, test, folds, total_test, fold_totals, axes=True):
    scores = {
        f"test_{key}": value
        for key, value in layout_scores(
            points[test], reference[test], vectors[test], total_test, axes
        ).items()
    }
    validation = []
    for fold, total in enumerate(fold_totals):
        mask = (~test) & (folds == fold)
        validation.append(layout_scores(points[mask], reference[mask], vectors[mask], total, axes))
    for key in validation[0]:
        values = [row[key] for row in validation if row[key] is not None]
        scores[f"cv_{key}"] = float(np.mean(values)) if values else None
    scores["cv_placed"] = int((~test).sum())
    scores["cv_total"] = int(sum(fold_totals))
    scores["cv_coverage"] = scores["cv_placed"] / scores["cv_total"] if scores["cv_total"] else 0
    scores["cv_fold_overlap@10"] = [row["neighbor_overlap@10"] for row in validation]
    return scores
