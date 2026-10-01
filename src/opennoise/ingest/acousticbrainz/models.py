"""Typed exact-ID source receipts and separate unvalidated acoustic projections."""

from __future__ import annotations

from typing import Literal
from uuid import UUID  # noqa: TC003 - Pydantic resolves runtime field annotations.

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, JsonValue

from opennoise.types import Sha256  # noqa: TC001 - runtime Pydantic scalar contract.

MAX_ARTISTS = 10
SEARCH_LIMIT = 25
RECORDINGS_PER_ARTIST = 3
MAX_RECORDINGS = MAX_ARTISTS * RECORDINGS_PER_ARTIST
MAX_API_REQUESTS = MAX_ARTISTS + 2 * MAX_RECORDINGS
MAX_RIGHTS_REQUESTS = 1
MAX_RESPONSE_BYTES = 262_144
MAX_TOTAL_BYTES = 3_145_728
MUSICBRAINZ_ORIGIN = "https://musicbrainz.org"
ACOUSTICBRAINZ_ORIGIN = "https://acousticbrainz.org"
RIGHTS_URL = ACOUSTICBRAINZ_ORIGIN + "/"
USER_AGENT = "OpenNoise/0.1 (bounded metadata research; https://github.com/h0rv/opennoise)"
REVISION = "acousticbrainz-exact-recording-benchmark-metadata-v1"


class Boundary(BaseModel):
    """Frozen research artifacts reject unexpected contract fields."""

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")


class BenchmarkArtist(Boundary):
    """An exact cohort artist ID; its name is display context only."""

    artist_mbid: UUID
    name: str = Field(min_length=1)


class SourceCapture(Boundary):
    """One attempted HTTP request and bounded decoded entity-body bytes."""

    request_index: int = Field(ge=1, le=MAX_API_REQUESTS + MAX_RIGHTS_REQUESTS)
    kind: Literal["rights", "search", "high-level", "low-level"]
    requested_url: str
    fetched_at: str
    artist_mbid: UUID | None = None
    recording_mbid: UUID | None = None
    status_code: int | None = Field(default=None, ge=100, le=599)
    response_headers: dict[str, str]
    payload_path: str
    payload_sha256: Sha256
    payload_bytes: int = Field(ge=0, le=MAX_RESPONSE_BYTES)
    payload_complete: bool
    body_encoding: Literal["httpx_decoded_entity_body"] = "httpx_decoded_entity_body"
    error_kind: (
        Literal["transport_error", "response_byte_bound", "unexpected_media_type"] | None
    ) = None


class SelectedRecording(Boundary):
    """A selected source recording with an independently exact credited artist ID."""

    artist_mbid: UUID
    recording_mbid: UUID
    title: str
    credited_artist_mbids: tuple[UUID, ...]
    search_capture_index: int


class SearchSelection(Boundary):
    """Explain every source artist search, including failed or inexact results."""

    artist_mbid: UUID
    search_capture_index: int
    response_state: Literal["available", "request_failed", "http_error", "invalid_schema"]
    returned_recording_count: int = Field(ge=0, le=SEARCH_LIMIT)
    exact_credit_recording_count: int = Field(ge=0, le=SEARCH_LIMIT)
    rejected_credit_recording_mbids: tuple[UUID, ...]
    selected_recording_mbids: tuple[UUID, ...] = Field(max_length=RECORDINGS_PER_ARTIST)


class QueryManifest(Boundary):
    """Freeze bounded exact source credits and recording selection before features."""

    revision: Literal["acousticbrainz-exact-recording-benchmark-metadata-v1"] = REVISION
    benchmark_source_sha256: Sha256
    declaration_sha256: Sha256
    rights_capture_sha256: Sha256
    artist_search_captures_sha256: Sha256
    artists: tuple[BenchmarkArtist, ...] = Field(min_length=1, max_length=MAX_ARTISTS)
    searches: tuple[SearchSelection, ...] = Field(max_length=MAX_ARTISTS)
    recordings: tuple[SelectedRecording, ...] = Field(max_length=MAX_RECORDINGS)
    selection: Literal["first_three_uuid_sorted_exact_credits_within_first_search_25"] = (
        "first_three_uuid_sorted_exact_credits_within_first_search_25"
    )
    representative_sample: Literal[False] = False
    names_used_for_identity: Literal[False] = False


class NumericDescriptor(Boundary):
    """A named raw numeric descriptor; None means absent, while zero remains zero."""

    path: str
    value: FiniteFloat | None


class ModelLabelScore(Boundary):
    """An opaque model's raw reported score, without assumed calibration or range."""

    label: str
    raw_reported_score: FiniteFloat


class HighLevelModelOutput(Boundary):
    """Keep each classifier family and implementation metadata separate."""

    family: str
    predicted_label: str | None
    reported_probability: FiniteFloat | None = None
    label_scores: tuple[ModelLabelScore, ...]
    implementation_metadata: dict[str, JsonValue]
    role: Literal["derived_unvalidated_acoustic_model_output"] = (
        "derived_unvalidated_acoustic_model_output"
    )
    calibrated: Literal[False] = False
    native_genre_fact: Literal[False] = False


class FeatureOutcome(Boundary):
    """One planned recording/facet lookup, with failure and identity states explicit."""

    artist_mbid: UUID
    recording_mbid: UUID
    level: Literal["high-level", "low-level"]
    request_index: int | None
    state: Literal[
        "available",
        "missing_http_404",
        "http_error",
        "request_failed",
        "review_identity_mismatch",
        "review_invalid_schema",
        "not_requested_byte_budget",
    ]
    embedded_identity: Literal["matched", "not_present", "not_checked"]
    numeric_descriptors: tuple[NumericDescriptor, ...] = ()
    high_level_models: tuple[HighLevelModelOutput, ...] = ()
    recording_level_only: Literal[True] = True
    artist_genre_membership: Literal[False] = False


class ArtistCoverage(Boundary):
    """Sample-specific coverage, never an artist's overall source coverage estimate."""

    artist_mbid: UUID
    name: str
    selected_recordings: int
    high_level_state_counts: dict[str, int]
    low_level_state_counts: dict[str, int]


class BenchmarkSummary(Boundary):
    """Metadata availability and separate derived projections for an exact cohort."""

    revision: Literal["acousticbrainz-exact-recording-benchmark-metadata-v1"] = REVISION
    source_license: Literal["CC0-1.0"] = "CC0-1.0"
    numeric_projection_revision: Literal["v1", "v2"] = "v1"
    source_attribution: Literal["AcousticBrainz / MusicBrainz contributors"] = (
        "AcousticBrainz / MusicBrainz contributors"
    )
    manifest_sha256: Sha256
    selected_recording_count: int = Field(ge=0, le=MAX_RECORDINGS)
    api_request_count: int = Field(ge=0, le=MAX_API_REQUESTS)
    rights_request_count: int = Field(ge=0, le=MAX_RIGHTS_REQUESTS)
    retained_response_bytes: int = Field(ge=0, le=MAX_TOTAL_BYTES)
    state_counts: dict[str, dict[str, int]]
    numeric_descriptor_available_counts: dict[str, int]
    artists: tuple[ArtistCoverage, ...]
    outcomes: tuple[FeatureOutcome, ...] = Field(max_length=2 * MAX_RECORDINGS)
    metadata_only: Literal[True] = True
    audio_requested: Literal[False] = False
    source_audio_analysis_preexisting: Literal[True] = True
    model_input_allowed: Literal[False] = False
    product_promotion_allowed: Literal[False] = False
    representative_sample: Literal[False] = False
    calibrated: Literal[False] = False
