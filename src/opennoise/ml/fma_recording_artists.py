"""Saved-recording to artist retrieval in historical FMA rank-profile space only."""

from typing import Any

import numpy as np

from opennoise.ml import fma_artist_neighbors as neighbors
from opennoise.ml.fma_artist_ranking import TOP_K
from opennoise.ml.fma_inference import MAX_QUERIES, MAX_TRACK_ID

POLICY = {
    **neighbors.POLICY,
    "revision": "fma44-saved-recording-artist-retrieval-v1",
    "metric": "cosine: query top10 reciprocal ranks against artist top10 mean reciprocal ranks",
    "request_order": "preserved; duplicates permitted; at most 100 explicit native track IDs",
    "saved_abstentions": "preserved; no fallback",
    "fresh_feature_inference": False,
}


def validate_requests(track_ids: list[int]) -> None:
    """Apply the existing native inference request bounds before input replay."""
    if not 1 <= len(track_ids) <= MAX_QUERIES or any(
        type(i) is not int or not 1 <= i <= MAX_TRACK_ID for i in track_ids
    ):
        raise ValueError(f"Request requires 1..{MAX_QUERIES} positive uint32 native track IDs")


def query_recordings(
    track_ids: list[int],
    rankings: dict[int, dict[str, Any]],
    identities: dict[int, dict[str, Any]],
    partitions: dict[str, Any],
) -> list[dict[str, Any]]:
    """Retrieve using saved predictions and native identities, without query targets."""
    validate_requests(track_ids)
    indices = {name: neighbors.profile_index(p["artists"]) for name, p in partitions.items()}
    track_partitions = {
        track: name
        for name, partition in partitions.items()
        for track in [
            *(t for artist in partition["artists"] for t in artist["track_ids"]),
            *partition.get("unresolved_artist_track_ids", []),
        ]
    }
    output = []
    for track in track_ids:
        identity = identities.get(track)
        saved = rankings.get(track)
        name = track_partitions.get(track)
        reason = (
            "unknown_native_track_id"
            if identity is None
            else "no_saved_prediction"
            if saved is None
            else saved["reason"]
            if saved["reason"] is not None
            else "unresolved_artist"
            if not identity["artist_known"] or not identity["component_id"]
            else "no_saved_partition"
            if name is None
            else None
        )
        profile: list[dict[str, Any]] = []
        result = {
            "neighbors": [],
            "eligible_candidate_artists": 0,
            "eligible_candidate_components": 0,
        }
        if reason is None and saved is not None and identity is not None and name is not None:
            labels = saved["ranked_genre_ids"][:TOP_K]
            profile = [
                {"genre_id": genre, "reciprocal_rank": 1 / rank}
                for rank, genre in enumerate(labels, 1)
            ]
            index = indices[name]
            vector = np.zeros(len(index.columns), dtype=np.float64)
            for genre in profile:
                if genre["genre_id"] in index.columns:
                    vector[index.columns[genre["genre_id"]]] = genre["reciprocal_rank"]
            norm = float(np.linalg.norm([g["reciprocal_rank"] for g in profile]))
            result = neighbors.retrieve(index, vector, norm, identity["component_id"])
            reason = result.pop("reason")
        output.append(
            {
                "track_id": track,
                "artist_id": identity["artist_id"] if identity else None,
                "component_id": identity["component_id"] if identity else None,
                "native_fold": identity["fold"] if identity else None,
                "partition": name,
                "saved_abstention": saved["reason"] if saved else None,
                "query_rank_profile": profile,
                "reason": reason,
                **result,
            }
        )
    return output
