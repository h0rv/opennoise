"""Identity-safe retrieval over saved model-rank profiles, never acoustic similarity."""

import math
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


def attach_neighbors(partition: dict[str, Any]) -> None:
    """Extend verified ranked artist rows using only their retained rank candidates."""
    rows = partition["artists"]
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
    for i, row in enumerate(rows):
        pool = [
            j
            for j, other in enumerate(rows)
            if other["component_id"] != row["component_id"] and norms[j] > 0
        ]
        edges = []
        if norms[i] > 0:
            scores = units[pool] @ units[i]
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
                    g for g, column in columns.items() if matrix[i, column] and matrix[j, column]
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
        row["profile_neighbors"] = {
            "neighbors": edges,
            "reason": "empty_rank_profile"
            if norms[i] == 0
            else None
            if edges
            else "no_eligible_overlap",
            "eligible_candidate_artists": len(pool),
            "eligible_candidate_components": len({rows[j]["component_id"] for j in pool}),
        }
