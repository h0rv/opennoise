"""Train-only H2 calibration for an explicitly non-production name-plus-artist experiment."""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from musix.history.historical_replica import bounded_name_tfidf_cosine, deterministic_h2_split
from musix.history.signals.historical_signal_model import (
    _idf_candidates,
    _legacy_vocabulary,
    _load_memberships,
)
from musix.models.calibrated_replica import CalibratedReplicaReport, ReplicaGridResult
from musix.models.historical_signal import HistoricalSignalSettings

if TYPE_CHECKING:
    from pathlib import Path

    from musix.models.historical import HistoricalCompatibilityManifest


def _coordinate_neighbors(
    ids: tuple[str, ...],
    coordinates: dict[str, tuple[float, float]],
    k: int,
) -> dict[str, set[str]]:
    points = np.array([coordinates[genre_id] for genre_id in ids], dtype=np.float64)
    return {
        genre_id: {
            ids[int(item)]
            for item in np.argsort(np.sum(np.square(points - points[index]), axis=1))[1 : k + 1]
        }
        for index, genre_id in enumerate(ids)
    }


def _recall(
    ids: tuple[str, ...],
    expected: dict[str, set[str]],
    scores: dict[tuple[str, str], float],
    k: int,
) -> float:
    actual: dict[str, list[tuple[str, float]]] = {genre_id: [] for genre_id in ids}
    allowed = set(ids)
    for (left, right), score in scores.items():
        if left in allowed and right in allowed:
            actual[left].append((right, score))
            actual[right].append((left, score))
    return sum(
        len(
            {
                neighbor
                for neighbor, _score in sorted(
                    actual[genre_id], key=lambda item: (-item[1], item[0])
                )[:k]
            }
            & expected[genre_id]
        )
        / k
        for genre_id in ids
    ) / len(ids)


def _blend(
    artist_scores: dict[tuple[str, str], float],
    name_scores: dict[tuple[str, str], float],
    artist_weight: float,
) -> dict[tuple[str, str], float]:
    """Exclude zero-weight candidates so a pure artist setting is exactly artist-only."""
    return {
        pair: score
        for pair in artist_scores | name_scores
        if (
            score := artist_weight * artist_scores.get(pair, 0.0)
            + (1.0 - artist_weight) * name_scores.get(pair, 0.0)
        )
        > 0.0
    }


def evaluate_calibrated_replica(
    *,
    historical: HistoricalCompatibilityManifest,
    membership_database_path: Path,
    h3_artifact_sha256: str,
) -> CalibratedReplicaReport:
    """Select blend parameters on deterministic train genres, then score untouched holdout."""
    vocabulary = _legacy_vocabulary(historical)
    names = dict(vocabulary)
    genre_ids = tuple(names)
    train, holdout = deterministic_h2_split(genre_ids)
    train_ids, holdout_ids = tuple(sorted(train)), tuple(sorted(holdout))
    coordinates = {
        genre.external_id: (genre.coordinate.x_px, genre.coordinate.y_px)
        for genre in historical.genres
    }
    name_scores = bounded_name_tfidf_cosine(names)
    train_expected = {k: _coordinate_neighbors(train_ids, coordinates, k) for k in (10, 20)}
    results: list[ReplicaGridResult] = []
    cached: dict[int, dict[tuple[str, str], float]] = {}
    memberships, _database_sha, _rows = _load_memberships(
        membership_database_path, vocabulary, h3_artifact_sha256
    )
    for cutoff in (4, 8, 16):
        candidates, _artist_degrees = _idf_candidates(
            memberships, HistoricalSignalSettings(maximum_artist_genre_degree=cutoff)
        )
        cached[cutoff] = {
            (genre_ids[left], genre_ids[right]): candidate.weighted_jaccard
            for (left, right), candidate in candidates.items()
        }
        for artist_weight in (0.0, 0.25, 0.5, 0.75, 1.0):
            for k in (10, 20):
                blended = _blend(cached[cutoff], name_scores, artist_weight)
                results.append(
                    ReplicaGridResult(
                        artist_weight=artist_weight,
                        maximum_artist_genre_degree=cutoff,
                        neighbors_per_genre=k,
                        train_recall_at_k=_recall(train_ids, train_expected[k], blended, k),
                    )
                )
    selected = max(
        results,
        key=lambda item: (item.train_recall_at_k, item.artist_weight, -item.neighbors_per_genre),
    )
    chosen = _blend(
        cached[selected.maximum_artist_genre_degree], name_scores, selected.artist_weight
    )
    artist_only = cached[selected.maximum_artist_genre_degree]
    expected_holdout = _coordinate_neighbors(holdout_ids, coordinates, selected.neighbors_per_genre)
    holdout_score = _recall(holdout_ids, expected_holdout, chosen, selected.neighbors_per_genre)
    artist_only_score = _recall(
        holdout_ids, expected_holdout, artist_only, selected.neighbors_per_genre
    )
    return CalibratedReplicaReport(
        h2_artifact_sha256=historical.artifact.content_sha256,
        h3_artifact_sha256=h3_artifact_sha256,
        train_genre_count=len(train_ids),
        holdout_genre_count=len(holdout_ids),
        random_holdout_recall_at_k=selected.neighbors_per_genre / (len(holdout_ids) - 1),
        grid=tuple(results),
        selected=selected,
        holdout_recall_at_k=holdout_score,
        holdout_lift_over_artist_only=holdout_score - artist_only_score,
    )
