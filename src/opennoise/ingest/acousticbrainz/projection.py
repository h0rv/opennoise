"""Pure offline exact-credit selection and schema-aware acoustic metadata projection."""

from __future__ import annotations

import json
import math
from http import HTTPStatus
from typing import TYPE_CHECKING, cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, TypeAdapter

from opennoise.ingest.acousticbrainz.models import (
    RECORDINGS_PER_ARTIST,
    SEARCH_LIMIT,
    HighLevelModelOutput,
    ModelLabelScore,
    NumericDescriptor,
    SearchSelection,
    SelectedRecording,
    SourceCapture,
)

if TYPE_CHECKING:
    from collections.abc import Sequence
    from typing import Literal

LEGACY_NUMERIC_PATHS = (
    "rhythm.bpm",
    "rhythm.bpm_histogram_first_peak_bpm",
    "rhythm.bpm_histogram_second_peak_bpm",
    "rhythm.beats_count",
    "rhythm.beats_loudness.mean",
    "rhythm.onset_rate",
    "rhythm.danceability",
    "lowlevel.average_loudness",
    "lowlevel.dynamic_complexity",
    "lowlevel.loudness_ebu128.integrated",
    "lowlevel.loudness_ebu128.loudness_range",
    "lowlevel.rms.mean",
    "lowlevel.spectral_centroid.mean",
    "lowlevel.spectral_flux.mean",
    "lowlevel.zerocrossingrate.mean",
    "tonal.tuning_frequency",
    "tonal.hpcp_entropy.mean",
)
NUMERIC_PATHS = tuple(
    path + ".mean" if path.endswith("_peak_bpm") else path for path in LEGACY_NUMERIC_PATHS
)
RECORDING_ID_PATHS = (
    "mbid",
    "recording_mbid",
    "musicbrainz_recordingid",
    "metadata.tags.musicbrainz_trackid",
    "metadata.tags.musicbrainz_recordingid",
    "metadata.tags.musicbrainz_recording_id",
)


class AcousticIdentityError(ValueError):
    """Embedded recording identifiers differ from the exact requested recording."""


class _SourceBoundary(BaseModel):
    model_config = ConfigDict(strict=True, extra="ignore")


class _CreditArtist(_SourceBoundary):
    id: UUID


class _Credit(_SourceBoundary):
    artist: _CreditArtist


class _Recording(_SourceBoundary):
    id: UUID
    title: str
    artist_credit: tuple[_Credit | str, ...] = Field(alias="artist-credit", min_length=1)


class _SearchResponse(_SourceBoundary):
    recordings: tuple[_Recording, ...] = Field(max_length=SEARCH_LIMIT)


def _unique_object(pairs: Sequence[tuple[str, object]]) -> dict[str, object]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("source JSON contains duplicate keys")
        result[key] = value
    return result


def _invalid_constant(_value: str) -> None:
    raise ValueError("source JSON contains a nonfinite numeric constant")


def _finite_tree(value: object) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("source JSON contains a nonfinite number")
    if isinstance(value, dict):
        for item in value.values():
            _finite_tree(item)
    elif isinstance(value, list):
        for item in value:
            _finite_tree(item)


def json_document(payload: bytes) -> dict[str, object]:
    """Reject nonobjects, ambiguous duplicate keys, and nonfinite source numbers."""
    result = TypeAdapter(dict[str, object]).validate_python(
        json.loads(payload, object_pairs_hook=_unique_object, parse_constant=_invalid_constant)
    )
    _finite_tree(result)
    return result


def select_recordings(
    source: SourceCapture, payload: bytes
) -> tuple[SearchSelection, tuple[SelectedRecording, ...]]:
    """Select exact credited UUIDs only, retaining source failures and homonym exclusions."""
    if source.artist_mbid is None:
        raise ValueError("recording selection requires the queried artist UUID")
    empty = {
        "artist_mbid": source.artist_mbid,
        "search_capture_index": source.request_index,
        "returned_recording_count": 0,
        "exact_credit_recording_count": 0,
        "rejected_credit_recording_mbids": (),
        "selected_recording_mbids": (),
    }
    if source.error_kind or not source.payload_complete:
        return SearchSelection(**empty, response_state="request_failed"), ()
    if source.status_code != HTTPStatus.OK:
        return SearchSelection(**empty, response_state="http_error"), ()
    try:
        json_document(payload)
        response = _SearchResponse.model_validate_json(payload)
        by_id: dict[UUID, _Recording] = {}
        for recording in response.recordings:
            if recording.id in by_id and recording != by_id[recording.id]:
                raise ValueError(  # noqa: TRY301 - preserve invalid-source selection state.
                    "recording search repeats conflicting recording metadata"
                )
            by_id[recording.id] = recording
    except ValueError:
        return SearchSelection(**empty, response_state="invalid_schema"), ()
    eligible: list[SelectedRecording] = []
    rejected: list[UUID] = []
    for identifier, recording in sorted(by_id.items(), key=lambda item: str(item[0])):
        credit_ids = tuple(
            sorted(
                {
                    credit.artist.id
                    for credit in recording.artist_credit
                    if isinstance(credit, _Credit)
                },
                key=str,
            )
        )
        if source.artist_mbid not in credit_ids:
            rejected.append(identifier)
            continue
        eligible.append(
            SelectedRecording(
                artist_mbid=source.artist_mbid,
                recording_mbid=identifier,
                title=recording.title,
                credited_artist_mbids=credit_ids,
                search_capture_index=source.request_index,
            )
        )
    selected = tuple(eligible[:RECORDINGS_PER_ARTIST])
    return (
        SearchSelection(
            artist_mbid=source.artist_mbid,
            search_capture_index=source.request_index,
            response_state="available",
            returned_recording_count=len(response.recordings),
            exact_credit_recording_count=len(eligible),
            rejected_credit_recording_mbids=tuple(rejected),
            selected_recording_mbids=tuple(row.recording_mbid for row in selected),
        ),
        selected,
    )


def _path(document: dict[str, object], path: str) -> object:
    current: object = document
    for key in path.split("."):
        if not isinstance(current, dict) or key not in current:
            return None
        current = current[key]
    return current


def verify_embedded_recording(
    document: dict[str, object], recording: UUID
) -> Literal["matched", "not_present"]:
    """Reject every present recording-ID alias that differs; never merge aliases."""
    found = False
    for path in RECORDING_ID_PATHS:
        raw = _path(document, path)
        if raw is None:
            continue
        identifiers = raw if isinstance(raw, list) else [raw]
        for identifier in identifiers:
            try:
                matches = isinstance(identifier, str) and UUID(identifier) == recording
            except ValueError:
                matches = False
            if not matches:
                raise AcousticIdentityError("embedded recording identifier differs from request")
            found = True
    return "matched" if found else "not_present"


def project_low_level(
    document: dict[str, object], *, revision: Literal["v1", "v2"] = "v2"
) -> tuple[NumericDescriptor, ...]:
    """Keep fixed numeric descriptors; schema presence and finite values are the only gates."""
    if not isinstance(document.get("lowlevel"), dict) or not isinstance(
        document.get("rhythm"), dict
    ):
        raise ValueError("low-level response lacks descriptor sections")  # noqa: TRY004 - source schema rejection.
    result = []
    paths = LEGACY_NUMERIC_PATHS if revision == "v1" else NUMERIC_PATHS
    for path in paths:
        value = _path(document, path)
        if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float))):
            raise ValueError("selected numeric descriptor has an unexpected source type")
        result.append(NumericDescriptor(path=path, value=cast("float | None", value)))
    return tuple(result)


def project_high_level(document: dict[str, object]) -> tuple[HighLevelModelOutput, ...]:
    """Retain each raw classifier family independently, with no native genre claims."""
    families = TypeAdapter(dict[str, dict[str, object]]).validate_python(document["highlevel"])
    if not families:
        raise ValueError("high-level response contains no classifier families")
    result = []
    for name, family in sorted(families.items()):
        scores = TypeAdapter(dict[str, float]).validate_python(family.get("all", {}), strict=True)
        result.append(
            HighLevelModelOutput(
                family=name,
                predicted_label=cast("str | None", family.get("value")),
                reported_probability=cast("float | None", family.get("probability")),
                label_scores=tuple(
                    ModelLabelScore(label=label, raw_reported_score=score)
                    for label, score in sorted(scores.items())
                ),
                implementation_metadata=TypeAdapter(dict[str, JsonValue]).validate_python(
                    family.get("version", {})
                ),
            )
        )
    return tuple(result)
