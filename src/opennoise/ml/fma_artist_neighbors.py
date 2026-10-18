"""Identity-safe retrieval over saved model-rank profiles, never acoustic similarity."""

import math
from dataclasses import dataclass
from typing import Any

import numpy as np

NEIGHBORS = 6
MAX_ARTISTS = 2000
POLICY = {
    "revision": "fma44-artist-rank-profile-neighbors-v1",
    "metric": "cosine over top10 mean reciprocal track ranks keyed by native genre ID",
    "pool": "same named historical partition; candidates are not training artists",
    "selection": (
        "positive overlap; exclude query component; one artist per component; native-ID ties"
    ),
    "limit": NEIGHBORS,
    "similarity": "model-rank-profile similarity only",
    "acoustic_similarity_established": False,
    "listener_relevance_established": False,
    "heldout_quality_established": False,
    "target_labels_consumed": False,
    "calibration_applied": False,
}


@dataclass(frozen=True)
class ProfileIndex:
    """Verified artist rows and their complete retained rank-profile coordinates."""

    rows: list[dict[str, Any]]
    columns: dict[int, int]
    matrix: np.ndarray
    norms: np.ndarray
    units: np.ndarray


def profile_index(rows: list[dict[str, Any]]) -> ProfileIndex:
    """Build the bounded candidate index without annotations or name joins."""
    if len(rows) > MAX_ARTISTS:
        raise ValueError("Artist profile neighbor pool exceeds resource cap")
    genres = sorted({g["genre_id"] for r in rows for g in r["ranked_source_annotation_candidates"]})
    columns = {genre: column for column, genre in enumerate(genres)}
    matrix = np.zeros((len(rows), len(genres)), dtype=np.float64)
    for i, row in enumerate(rows):
        for genre in row["ranked_source_annotation_candidates"]:
            score = genre["mean_reciprocal_track_rank"]
            if not math.isfinite(score) or score <= 0:
                raise ValueError("Artist profile weights require finite positive ranks")
            matrix[i, columns[genre["genre_id"]]] = score
    norms = np.linalg.norm(matrix, axis=1)
    units = matrix / np.where(norms > 0, norms, 1)[:, None]
    return ProfileIndex(rows, columns, matrix, norms, units)


def retrieve(
    index: ProfileIndex, vector: np.ndarray, norm: float, component: int
) -> dict[str, Any]:
    """Rank a real query vector against other native components with no identity substitution.

    The norm includes every query coordinate, including genres absent from the
    candidate vocabulary. The vector aligns only its shared coordinates.
    """
    rows = index.rows
    pool = [
        j
        for j, other in enumerate(rows)
        if other["component_id"] != component and index.norms[j] > 0
    ]
    edges = []
    if norm > 0:
        scores = index.units[pool] @ (vector / norm)
        ordered = sorted(
            zip(pool, scores, strict=True),
            key=lambda item: (-item[1], rows[item[0]]["artist_id"]),
        )
        seen = set()
        for j, score in ordered:
            other = rows[j]
            if score <= 0 or other["component_id"] in seen:
                continue
            seen.add(other["component_id"])
            shared = [
                g
                for g, column in index.columns.items()
                if vector[column] and index.matrix[j, column]
            ]
            edges.append(
                {
                    "artist_id": other["artist_id"],
                    "component_id": other["component_id"],
                    "cosine_distance": float(np.clip(1 - score, 0, 2)),
                    "shared_profile_genre_ids": shared,
                    "nominated_track_count": len(other["track_ids"]),
                    "ranking_supported_track_count": other["ranking_supported_track_count"],
                }
            )
            if len(edges) == NEIGHBORS:
                break
    return {
        "neighbors": edges,
        "reason": "empty_rank_profile" if norm == 0 else None if edges else "no_eligible_overlap",
        "eligible_candidate_artists": len(pool),
        "eligible_candidate_components": len({rows[j]["component_id"] for j in pool}),
    }


def attach_neighbors(partition: dict[str, Any]) -> None:
    """Extend verified ranked artist rows using only their retained rank candidates."""
    index = profile_index(partition["artists"])
    for i, row in enumerate(index.rows):
        row["profile_neighbors"] = retrieve(
            index, index.matrix[i], float(index.norms[i]), row["component_id"]
        )
