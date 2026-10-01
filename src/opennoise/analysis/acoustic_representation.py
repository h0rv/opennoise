"""Research-only descriptor aggregation with independent sonic and cultural distances."""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass
from statistics import median
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence


@dataclass(frozen=True)
class RecordingDescriptors:
    """An exact-credit recording and its observed finite metadata, never imputed."""

    artist_id: str
    recording_id: str
    descriptors: Mapping[str, float | None]


@dataclass(frozen=True)
class ArtistDescriptors:
    """Median recording descriptors and explicit per-feature sample counts."""

    artist_id: str
    recording_count: int
    values: Mapping[str, float | None]
    observed_counts: Mapping[str, int]


def aggregate_recordings(
    recordings: Sequence[RecordingDescriptors], features: Sequence[str]
) -> tuple[ArtistDescriptors, ...]:
    """Aggregate unique recordings; reject conflicting duplicates and nonfinite data."""
    by_artist: dict[str, dict[str, RecordingDescriptors]] = defaultdict(dict)
    for row in recordings:
        previous = by_artist[row.artist_id].get(row.recording_id)
        if previous is not None and previous != row:
            raise ValueError("conflicting duplicate recording descriptors")
        for value in row.descriptors.values():
            if value is not None and (isinstance(value, bool) or not math.isfinite(value)):
                raise ValueError("descriptor must be finite or explicitly missing")
        by_artist[row.artist_id][row.recording_id] = row
    output = []
    for artist_id, rows in sorted(by_artist.items()):
        observed = {
            feature: [
                value
                for row in rows.values()
                if (value := row.descriptors.get(feature)) is not None
            ]
            for feature in features
        }
        output.append(
            ArtistDescriptors(
                artist_id,
                len(rows),
                {key: median(values) if values else None for key, values in observed.items()},
                {key: len(values) for key, values in observed.items()},
            )
        )
    return tuple(output)


def fit_scales(training: Sequence[ArtistDescriptors], features: Sequence[str]) -> dict[str, float]:
    """Fit standard deviations only on supplied training artists; omit constants."""
    scales = {}
    for feature in features:
        values = [value for row in training if (value := row.values.get(feature)) is not None]
        if len(values) < 2:  # noqa: PLR2004 - variance needs multiple observations.
            continue
        mean = sum(values) / len(values)
        scale = math.sqrt(sum((value - mean) ** 2 for value in values) / len(values))
        if scale > 0:
            scales[feature] = scale
    return scales


def sonic_neighbors(
    query: ArtistDescriptors,
    candidates: Sequence[ArtistDescriptors],
    scales: Mapping[str, float],
    *,
    minimum_shared: int = 3,
) -> list[dict[str, object]]:
    """Rank standardized RMS distances, reporting comparable descriptor coverage."""
    if minimum_shared < 1 or any(not math.isfinite(v) or v <= 0 for v in scales.values()):
        raise ValueError("positive scales and minimum shared feature count are required")
    result: list[dict[str, object]] = []
    for candidate in candidates:
        if candidate.artist_id == query.artist_id:
            continue
        differences = []
        shared = []
        for feature, scale in scales.items():
            left, right = query.values.get(feature), candidate.values.get(feature)
            if left is not None and right is not None:
                differences.append(((left - right) / scale) ** 2)
                shared.append(feature)
        if len(shared) >= minimum_shared:
            result.append(
                {
                    "artist_id": candidate.artist_id,
                    "distance": math.sqrt(sum(differences) / len(differences)),
                    "shared_features": shared,
                    "shared_feature_count": len(shared),
                    "candidate_recording_count": candidate.recording_count,
                    "role": "unvalidated_metadata_sonic_distance",
                }
            )
    return sorted(result, key=lambda row: (float(str(row["distance"])), str(row["artist_id"])))


def cultural_neighbors(
    query_id: str, memberships: Mapping[str, frozenset[str]]
) -> list[dict[str, object]]:
    """Rank independently inferred community overlap; never read sonic descriptors."""
    query = memberships.get(query_id, frozenset())
    if not query:
        return []
    result: list[dict[str, object]] = []
    for artist_id, values in memberships.items():
        if artist_id == query_id or not values:
            continue
        shared = query & values
        if shared:
            result.append(
                {
                    "artist_id": artist_id,
                    "similarity": len(shared) / len(query | values),
                    "shared_community_ids": sorted(shared),
                    "role": "inferred_cultural_community_overlap",
                }
            )
    return sorted(result, key=lambda row: (-float(str(row["similarity"])), str(row["artist_id"])))
