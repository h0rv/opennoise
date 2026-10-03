"""Conservative train-only support gates for comparable acoustic metadata distances."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, TypedDict

from opennoise.analysis.acoustic_representation import (
    ArtistDescriptors,
    fit_scales,
    sonic_neighbors,
)

if TYPE_CHECKING:
    from collections.abc import Sequence


@dataclass(frozen=True)
class DescriptorScale:
    """One numeric descriptor's normalization and exact training population."""

    feature: str
    center: float
    scale: float
    training_artist_ids: tuple[str, ...]


@dataclass(frozen=True)
class AcousticSupportPolicy:
    """Declared evidence and numeric range rules, never selected using evaluation labels."""

    minimum_recordings: int = 2
    minimum_population: int = 3
    minimum_features: int = 3
    maximum_standardized_offset: float = 6.0


_DEFAULT_POLICY = AcousticSupportPolicy()
_MIN_VARIANCE_POPULATION = 2


@dataclass(frozen=True)
class AcousticSupportFrame:
    """A fixed descriptor frame; range gates are conservative, not relevance calibration."""

    descriptors: tuple[DescriptorScale, ...]
    training_artist_ids: tuple[str, ...]
    policy: AcousticSupportPolicy


type AbstentionReason = Literal[
    "insufficient_training_support",
    "insufficient_recordings",
    "incomplete_descriptors",
    "outside_training_support",
    "no_supported_candidates",
]


class AcousticSupportResult(TypedDict):
    """Fixed-frame ranking or an explicit query abstention, preserving candidate failures."""

    artist_id: str
    status: str
    abstention_reason: AbstentionReason | None
    fixed_features: list[str]
    query_recording_count: int
    neighbors: list[dict[str, object]]
    candidate_abstentions: list[dict[str, str]]
    independent_musical_relevance_evaluated: bool


def _validate_profiles(profiles: Sequence[ArtistDescriptors]) -> None:
    seen = set()
    for profile in profiles:
        if not profile.artist_id or profile.artist_id in seen:
            raise ValueError("acoustic profiles require distinct nonempty artist identities")
        seen.add(profile.artist_id)
        if type(profile.recording_count) is not int or profile.recording_count < 0:
            raise ValueError("recording count must be a nonnegative integer")
        for feature in set(profile.values) | set(profile.observed_counts):
            value = profile.values.get(feature)
            count = profile.observed_counts.get(feature, 0)
            if type(count) is not int or not 0 <= count <= profile.recording_count:
                raise ValueError("observed descriptor count differs from recording coverage")
            if (value is None) != (count == 0):
                raise ValueError("descriptor missingness differs from its observed count")
            if value is not None and (isinstance(value, bool) or not math.isfinite(value)):
                raise ValueError("acoustic descriptors must be finite numeric observations")


def fit_acoustic_support(
    training: Sequence[ArtistDescriptors],
    features: Sequence[str],
    *,
    policy: AcousticSupportPolicy = _DEFAULT_POLICY,
) -> AcousticSupportFrame:
    """Fit on declared training profiles only, omitting constant and undersupported features.

    Counts enforce repeated recording evidence, without treating observations as
    independent artist votes. The six-standard-deviation default is an explicit
    range rule, not a calibrated probability of musical or population novelty.
    """
    _validate_profiles(training)
    if (
        type(policy.minimum_recordings) is not int
        or policy.minimum_recordings < 1
        or type(policy.minimum_population) is not int
        or policy.minimum_population < _MIN_VARIANCE_POPULATION
        or type(policy.minimum_features) is not int
        or policy.minimum_features < 1
        or not math.isfinite(policy.maximum_standardized_offset)
        or policy.maximum_standardized_offset <= 0
        or len(set(features)) != len(features)
    ):
        raise ValueError("positive support budgets and distinct descriptor names are required")
    eligible = tuple(
        sorted(
            (row for row in training if row.recording_count >= policy.minimum_recordings),
            key=lambda row: row.artist_id,
        )
    )
    scales = []
    for feature in sorted(features):
        population = tuple(
            row
            for row in eligible
            if row.observed_counts.get(feature, 0) >= policy.minimum_recordings
        )
        if len(population) < policy.minimum_population:
            continue
        scale = fit_scales(population, (feature,)).get(feature)
        if scale is None:
            continue
        values = [row.values[feature] for row in population]
        center = sum(float(value) for value in values if value is not None) / len(population)
        scales.append(
            DescriptorScale(feature, center, scale, tuple(row.artist_id for row in population))
        )
    return AcousticSupportFrame(
        tuple(scales),
        tuple(row.artist_id for row in eligible),
        policy,
    )


def _support_reason(
    profile: ArtistDescriptors, frame: AcousticSupportFrame
) -> AbstentionReason | None:
    if len(frame.descriptors) < frame.policy.minimum_features:
        return "insufficient_training_support"
    if profile.recording_count < frame.policy.minimum_recordings:
        return "insufficient_recordings"
    for descriptor in frame.descriptors:
        value = profile.values.get(descriptor.feature)
        if (
            value is None
            or profile.observed_counts.get(descriptor.feature, 0) < frame.policy.minimum_recordings
        ):
            return "incomplete_descriptors"
    for descriptor in frame.descriptors:
        value = profile.values[descriptor.feature]
        if (
            value is not None
            and abs((value - descriptor.center) / descriptor.scale)
            > frame.policy.maximum_standardized_offset
        ):
            return "outside_training_support"
    return None


def supported_sonic_neighbors(
    query: ArtistDescriptors,
    candidates: Sequence[ArtistDescriptors],
    frame: AcousticSupportFrame,
) -> AcousticSupportResult:
    """Reuse the baseline distance only for profiles sharing the full fixed feature frame."""
    _validate_profiles((query,))
    _validate_profiles(candidates)
    reason = _support_reason(query, frame)
    accepted = []
    abstentions = []
    for candidate in sorted(candidates, key=lambda row: row.artist_id):
        if candidate.artist_id == query.artist_id:
            continue
        candidate_reason = _support_reason(candidate, frame)
        if candidate_reason is not None:
            abstentions.append({"artist_id": candidate.artist_id, "reason": candidate_reason})
        else:
            accepted.append(candidate)
    neighbors = []
    if reason is None:
        scales = {row.feature: row.scale for row in frame.descriptors}
        neighbors = sonic_neighbors(query, accepted, scales, minimum_shared=len(scales))
        if not neighbors:
            reason = "no_supported_candidates"
    return {
        "artist_id": query.artist_id,
        "status": "abstained" if reason is not None else "supported_metadata_comparison",
        "abstention_reason": reason,
        "fixed_features": [row.feature for row in frame.descriptors],
        "query_recording_count": query.recording_count,
        "neighbors": neighbors,
        "candidate_abstentions": abstentions,
        "independent_musical_relevance_evaluated": False,
    }
