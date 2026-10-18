"""Fixed reciprocal-rank artist evidence from saved predictions, without source targets."""

import math
from collections import defaultdict
from typing import Any

TOP_K = 10
PROTOCOL_SHA256 = "971efc50e483c189b0fbabe68ae29840704675c8f48a980cccb99f60d2b294c8"


def rank_artist_genres(track_ids: list[int], rankings: dict[int, dict[str, Any]]) -> dict[str, Any]:
    """Average reciprocal track ranks; all nominated tracks remain in the denominator."""
    if not track_ids or len(set(track_ids)) != len(track_ids):
        raise ValueError("Artist ranking requires distinct nominated track IDs")
    contributions: dict[int, list[float]] = defaultdict(list)
    supported = 0
    for track in sorted(track_ids):
        if track not in rankings:
            raise ValueError("Artist ranking lacks a nominated saved query")
        row = rankings[track]
        labels = row["ranked_genre_ids"]
        if len(labels) != len(set(labels)) or (row["reason"] is not None and labels):
            raise ValueError("Invalid saved ranking or nonempty abstention")
        if not labels:
            continue
        supported += 1
        for rank, genre in enumerate(labels, 1):
            contributions[genre].append(1 / rank)
    scores = {genre: math.fsum(values) / len(track_ids) for genre, values in contributions.items()}
    return {
        "ranking_supported_track_count": supported,
        "ranked_source_annotation_candidates": [
            {
                "genre_id": genre,
                "mean_reciprocal_track_rank": scores[genre],
                "contributing_track_count": len(contributions[genre]),
            }
            for genre in sorted(scores, key=lambda genre: (-scores[genre], genre))[:TOP_K]
        ],
    }
