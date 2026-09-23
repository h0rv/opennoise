"""Bounded local join and summary for playlist recordings' native MB genres."""

from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple

if TYPE_CHECKING:
    from uuid import UUID

    from opennoise.ingest.musicbrainz.entity_genre_observation import EntityGenreObservationReport

PLAYLIST_RECORDING_DENOMINATOR = 527
RECORDING_GENRE_COVERAGE_THRESHOLD = 2


class RecordingGenreProbeSummary(NamedTuple):
    """Counts from the native recording facet; tags stay an independent facet."""

    observed_recordings: int
    proper_genre_observations: int
    positive_tag_observations: int
    recordings_with_positive_proper_genre: int
    recording_genre_coverage_threshold_exceeded: bool


def exact_recording_overlap(
    playlist_recording_ids: frozenset[UUID], catalog_recording_ids: frozenset[UUID]
) -> tuple[UUID, ...]:
    """Select only exact UUID overlap, in deterministic order."""
    return tuple(sorted(playlist_recording_ids & catalog_recording_ids, key=str))


def summarize_recording_genres(
    report: EntityGenreObservationReport,
) -> RecordingGenreProbeSummary:
    """Count native recording genres and positive tags without propagation."""
    recordings = {
        receipt.entity_mbid
        for receipt in report.source_receipts
        if receipt.entity_kind == "recording"
    }
    genres = tuple(
        observation
        for observation in report.observations
        if observation.entity_kind == "recording" and observation.facet == "musicbrainz_genre"
    )
    tags = tuple(
        observation
        for observation in report.observations
        if observation.entity_kind == "recording" and observation.facet == "musicbrainz_tag"
    )
    positive_genres = tuple(
        observation
        for observation in genres
        if observation.genre_vote_count is not None and observation.genre_vote_count > 0
    )
    positive_genre_recordings = {observation.entity_mbid for observation in positive_genres}
    return RecordingGenreProbeSummary(
        observed_recordings=len(recordings),
        proper_genre_observations=len(genres),
        positive_tag_observations=len(tags),
        recordings_with_positive_proper_genre=len(positive_genre_recordings),
        recording_genre_coverage_threshold_exceeded=(
            len(positive_genre_recordings) > RECORDING_GENRE_COVERAGE_THRESHOLD
        ),
    )
