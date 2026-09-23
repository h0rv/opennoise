"""Bounded exact-MBID recording coverage measurement against MusicBrainz.

This local-only probe deliberately uses the recording lookup endpoint, not a
name search or the large canonical-data dump.  Its report retains no titles,
credited names, releases, audio, genres, or raw response bodies; raw JSON is
instead held in a bounded local-only custody cache for offline replay.
"""

from __future__ import annotations

import asyncio
import hashlib
import stat
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal, TypedDict
from uuid import UUID  # noqa: TC003  # Pydantic resolves this annotation at definition.

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from opennoise.models import FrozenModel
from opennoise.types import Sha256  # noqa: TC001  # Pydantic resolves the alias at definition.

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from pathlib import Path

    from opennoise.analysis.listenbrainz_recording_co_listen import RecordingIdCohortArtifact

MUSICBRAINZ_API_BASE = "https://musicbrainz.org/ws/2"
MUSICBRAINZ_MIN_REQUEST_INTERVAL_SECONDS = 1.0
_MAXIMUM_SAMPLE_RECORDINGS = 32
_HTTP_NOT_FOUND = 404
_HTTP_REDIRECT_MINIMUM = 300
_HTTP_CLIENT_ERROR_MINIMUM = 400
_MAXIMUM_RESPONSE_BYTES = 512 * 1024


class MusicBrainzRecordingCoverageError(RuntimeError):
    """Report a failed bounded exact-recording coverage measurement."""


class RecordingLookupSettings(FrozenModel):
    """Make the deterministic prefix and upstream request ceiling explicit."""

    selection_strategy: Literal["sorted_cohort_prefix"] = "sorted_cohort_prefix"
    maximum_recordings: int = Field(default=24, gt=0, le=_MAXIMUM_SAMPLE_RECORDINGS)
    timeout_seconds: float = Field(default=30.0, gt=0, le=60.0)


class _ApiArtist(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True, extra="ignore")

    id: UUID


class _ApiArtistCredit(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True, extra="ignore")

    artist: _ApiArtist


class _ApiRecording(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True, extra="ignore")

    id: UUID
    artist_credit: tuple[_ApiArtistCredit, ...] = Field(default=(), alias="artist-credit")


class _ReceiptBase(TypedDict):
    requested_recording_id: UUID
    http_status_code: int
    response_object: LocalResponseObject
    fetched_at_utc: datetime


class LocalResponseObject(FrozenModel):
    """Name one bounded raw response retained only in the local custody cache."""

    sha256: Sha256
    byte_size: int = Field(ge=0, le=_MAXIMUM_RESPONSE_BYTES)


class RecordingLookupReceipt(FrozenModel):
    """One source receipt without a recording title or any artist display text."""

    requested_recording_id: UUID
    outcome: Literal[
        "exact_match",
        "http_not_found",
        "http_redirect",
        "http_error",
        "invalid_response",
        "nonexact_response",
    ]
    http_status_code: int = Field(ge=100, le=599)
    response_object: LocalResponseObject
    fetched_at_utc: datetime
    response_recording_id: UUID | None = None
    artist_credit_artist_ids: tuple[UUID, ...] = ()

    @model_validator(mode="after")
    def require_exact_identity_and_unique_credit_order(self) -> RecordingLookupReceipt:
        """Require artist IDs only for a successful exact recording response."""
        if (
            self.outcome == "exact_match"
            and self.response_recording_id != self.requested_recording_id
        ):
            raise ValueError("exact lookup response recording ID does not equal requested ID")
        if self.outcome != "exact_match" and self.artist_credit_artist_ids:
            raise ValueError("an abstained lookup cannot retain artist credit IDs")
        if len(self.artist_credit_artist_ids) != len(set(self.artist_credit_artist_ids)):
            raise ValueError("MusicBrainz artist credit repeats an artist ID")
        return self


class RecordingLookupCoverage(FrozenModel):
    """Aggregate exact-lookup and credit-cardinality results for the frozen sample."""

    requested_recording_count: int = Field(ge=0)
    successful_exact_lookup_count: int = Field(ge=0)
    artist_credit_present_count: int = Field(ge=0)
    multiple_artist_credit_count: int = Field(ge=0)
    unique_artist_id_count: int = Field(ge=0)


class MusicBrainzRecordingCoverageArtifact(FrozenModel):
    """Receipt-bound local research result; it is neither a catalog nor a bridge."""

    revision: Literal["musicbrainz-recording-exact-coverage-v2"] = (
        "musicbrainz-recording-exact-coverage-v2"
    )
    local_only: Literal[True] = True
    export_allowed: Literal[False] = False
    serving_allowed: Literal[False] = False
    source_kind: Literal["musicbrainz_recording_exact_lookup"] = (
        "musicbrainz_recording_exact_lookup"
    )
    source_documentation_url: Literal["https://musicbrainz.org/doc/MusicBrainz_API"] = (
        "https://musicbrainz.org/doc/MusicBrainz_API"
    )
    cohort_artifact_file_sha256: Sha256
    cohort_source_artifact_sha256: Sha256
    cohort_recording_id_set_sha256: Sha256
    cohort_recording_id_count: int = Field(ge=0)
    settings: RecordingLookupSettings
    selected_recording_ids: tuple[UUID, ...]
    selected_recording_id_set_sha256: Sha256
    lookups: tuple[RecordingLookupReceipt, ...]
    coverage: RecordingLookupCoverage

    @model_validator(mode="after")
    def require_complete_deterministic_measurement(self) -> MusicBrainzRecordingCoverageArtifact:
        """Prevent a partial or reordered response set from looking complete."""
        if self.selected_recording_ids != tuple(sorted(self.selected_recording_ids, key=str)):
            raise ValueError("selected recording IDs must be sorted")
        if len(self.selected_recording_ids) != len(set(self.selected_recording_ids)):
            raise ValueError("selected recording IDs must be unique")
        if self.selected_recording_id_set_sha256 != _uuid_set_sha256(self.selected_recording_ids):
            raise ValueError("selected recording ID-set hash does not match")
        if (
            tuple(item.requested_recording_id for item in self.lookups)
            != self.selected_recording_ids
        ):
            raise ValueError("lookups must exactly and deterministically cover the selected IDs")
        if self.coverage.requested_recording_count != len(self.selected_recording_ids):
            raise ValueError("requested count does not match selected IDs")
        return self


def _uuid_set_sha256(values: tuple[UUID, ...]) -> str:
    return hashlib.sha256("\n".join(map(str, values)).encode()).hexdigest()


def _receipt_from_response(
    recording_id: UUID,
    response: httpx.Response,
    *,
    fetched_at_utc: datetime,
    response_object: LocalResponseObject,
) -> RecordingLookupReceipt:
    """Project one HTTP response into a safe exact-ID receipt or abstention."""
    receipt_base: _ReceiptBase = {
        "requested_recording_id": recording_id,
        "http_status_code": response.status_code,
        "response_object": response_object,
        "fetched_at_utc": fetched_at_utc,
    }
    if response.status_code == _HTTP_NOT_FOUND:
        return RecordingLookupReceipt(outcome="http_not_found", **receipt_base)
    if _HTTP_REDIRECT_MINIMUM <= response.status_code < _HTTP_CLIENT_ERROR_MINIMUM:
        return RecordingLookupReceipt(outcome="http_redirect", **receipt_base)
    if response.is_error:
        return RecordingLookupReceipt(outcome="http_error", **receipt_base)
    try:
        parsed = _ApiRecording.model_validate_json(response.content)
    except (ValidationError, ValueError):
        return RecordingLookupReceipt(outcome="invalid_response", **receipt_base)
    if parsed.id != recording_id:
        return RecordingLookupReceipt(
            outcome="nonexact_response", response_recording_id=parsed.id, **receipt_base
        )
    return RecordingLookupReceipt(
        outcome="exact_match",
        response_recording_id=parsed.id,
        artist_credit_artist_ids=tuple(credit.artist.id for credit in parsed.artist_credit),
        **receipt_base,
    )


def _write_response_object(cache_directory: Path, content: bytes) -> LocalResponseObject:
    """Write one bounded raw API body under its content hash without overwriting it."""
    if len(content) > _MAXIMUM_RESPONSE_BYTES:
        raise MusicBrainzRecordingCoverageError("MusicBrainz response exceeds custody limit")
    digest = hashlib.sha256(content).hexdigest()
    path = cache_directory / "sha256" / f"{digest}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if _read_bounded_response_object(path) != content:
            raise MusicBrainzRecordingCoverageError("response custody object does not match hash")
    else:
        temporary = path.with_name(f".{path.name}.tmp")
        try:
            temporary.write_bytes(content)
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
    return LocalResponseObject(sha256=digest, byte_size=len(content))


def _read_bounded_response_object(path: Path) -> bytes:
    """Read one regular custody object without allocating beyond the response cap."""
    try:
        metadata = path.lstat()
    except OSError as error:
        raise MusicBrainzRecordingCoverageError("response custody object is missing") from error
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > _MAXIMUM_RESPONSE_BYTES:
        raise MusicBrainzRecordingCoverageError("response custody object exceeds boundary")
    try:
        with path.open("rb") as stream:
            content = stream.read(_MAXIMUM_RESPONSE_BYTES + 1)
    except OSError as error:
        raise MusicBrainzRecordingCoverageError("response custody object cannot be read") from error
    if len(content) > _MAXIMUM_RESPONSE_BYTES:
        raise MusicBrainzRecordingCoverageError("response custody object exceeds boundary")
    return content


async def _fetch_bounded_response(
    client: httpx.AsyncClient, endpoint: str, user_agent: str, *, inclusion: str = "artist-credits"
) -> httpx.Response:
    """Read a response incrementally so the custody byte cap also bounds memory."""
    content = bytearray()
    async with client.stream(
        "GET",
        endpoint,
        params={"fmt": "json", "inc": inclusion},
        headers={
            "User-Agent": user_agent,
            "Accept": "application/json",
            "Accept-Encoding": "identity",
        },
    ) as response:
        async for chunk in response.aiter_bytes():
            content.extend(chunk)
            if len(content) > _MAXIMUM_RESPONSE_BYTES:
                raise MusicBrainzRecordingCoverageError(
                    "MusicBrainz response exceeds custody limit"
                )
        return httpx.Response(
            response.status_code,
            headers=response.headers,
            content=bytes(content),
            request=response.request,
        )


def replay_exact_recording_coverage(
    artifact: MusicBrainzRecordingCoverageArtifact, cache_directory: Path
) -> MusicBrainzRecordingCoverageArtifact:
    """Validate every custody object and exactly reproduce its safe receipt offline."""
    replayed: list[RecordingLookupReceipt] = []
    for receipt in artifact.lookups:
        path = cache_directory / "sha256" / f"{receipt.response_object.sha256}.json"
        content = _read_bounded_response_object(path)
        if len(content) != receipt.response_object.byte_size:
            raise MusicBrainzRecordingCoverageError(
                "response custody object byte size does not match"
            )
        if hashlib.sha256(content).hexdigest() != receipt.response_object.sha256:
            raise MusicBrainzRecordingCoverageError("response custody object hash does not match")
        replayed.append(
            _receipt_from_response(
                receipt.requested_recording_id,
                httpx.Response(receipt.http_status_code, content=content),
                fetched_at_utc=receipt.fetched_at_utc,
                response_object=receipt.response_object,
            )
        )
    if tuple(replayed) != artifact.lookups:
        raise MusicBrainzRecordingCoverageError("offline response replay does not equal receipt")
    return artifact


async def measure_exact_recording_coverage(  # noqa: PLR0913  # Explicit bounded I/O boundary.
    cohort: RecordingIdCohortArtifact,
    client: httpx.AsyncClient,
    *,
    user_agent: str,
    cohort_artifact_file_sha256: str,
    settings: RecordingLookupSettings | None = None,
    response_cache_directory: Path,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> MusicBrainzRecordingCoverageArtifact:
    """Fetch a small sorted cohort prefix sequentially and retain safe projections."""
    if not user_agent.strip() or "/" not in user_agent or "(" not in user_agent:
        raise MusicBrainzRecordingCoverageError(
            "MusicBrainz user_agent must include an app version and contact"
        )
    resolved = settings or RecordingLookupSettings()
    selected = cohort.recording_ids[: resolved.maximum_recordings]
    if not selected:
        raise MusicBrainzRecordingCoverageError("recording cohort is empty")
    next_request_at = 0.0
    receipts: list[RecordingLookupReceipt] = []
    for recording_id in selected:
        delay = next_request_at - clock()
        if delay > 0:
            await sleep(delay)
        next_request_at = clock() + MUSICBRAINZ_MIN_REQUEST_INTERVAL_SECONDS
        endpoint = f"{MUSICBRAINZ_API_BASE}/recording/{recording_id}"
        try:
            response = await _fetch_bounded_response(client, endpoint, user_agent)
        except httpx.HTTPError as error:
            raise MusicBrainzRecordingCoverageError(
                f"MusicBrainz exact lookup failed for {recording_id}: {type(error).__name__}"
            ) from error
        response_object = _write_response_object(response_cache_directory, response.content)
        receipts.append(
            _receipt_from_response(
                recording_id,
                response,
                fetched_at_utc=datetime.now(UTC),
                response_object=response_object,
            )
        )
    unique_artists = frozenset(
        artist_id for receipt in receipts for artist_id in receipt.artist_credit_artist_ids
    )
    coverage = RecordingLookupCoverage(
        requested_recording_count=len(selected),
        successful_exact_lookup_count=sum(item.outcome == "exact_match" for item in receipts),
        artist_credit_present_count=sum(
            item.outcome == "exact_match" and bool(item.artist_credit_artist_ids)
            for item in receipts
        ),
        multiple_artist_credit_count=sum(
            len(item.artist_credit_artist_ids) > 1 for item in receipts
        ),
        unique_artist_id_count=len(unique_artists),
    )
    return MusicBrainzRecordingCoverageArtifact(
        cohort_artifact_file_sha256=cohort_artifact_file_sha256,
        cohort_source_artifact_sha256=cohort.source_artifact_sha256,
        cohort_recording_id_set_sha256=cohort.recording_id_set_sha256,
        cohort_recording_id_count=len(cohort.recording_ids),
        settings=resolved,
        selected_recording_ids=selected,
        selected_recording_id_set_sha256=_uuid_set_sha256(selected),
        lookups=tuple(receipts),
        coverage=coverage,
    )


class _ApiReleaseGroup(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True, extra="ignore")

    id: UUID
    primary_type: str | None = Field(default=None, alias="primary-type")
    secondary_types: tuple[str, ...] = Field(default=(), alias="secondary-types")


class _ApiRelease(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True, extra="ignore")

    id: UUID
    artist_credit: tuple[_ApiArtistCredit, ...] = Field(default=(), alias="artist-credit")
    release_group: _ApiReleaseGroup | None = Field(default=None, alias="release-group")


class _ApiRecordingWithReleases(_ApiRecording):
    releases: tuple[_ApiRelease, ...] = Field(default=(), max_length=25)


class RecordingReleaseLink(FrozenModel):
    """One exact release link, retaining IDs and classification but no display metadata."""

    release_id: UUID
    release_group_id: UUID | None = None
    primary_type: str | None = None
    compilation_secondary_type: bool
    release_artist_credit_artist_ids: tuple[UUID, ...]


class RecordingReleaseLookupReceipt(FrozenModel):
    """Safe projection of one bounded exact recording-to-release response."""

    requested_recording_id: UUID
    outcome: Literal[
        "exact_match",
        "http_not_found",
        "http_redirect",
        "http_error",
        "invalid_response",
        "nonexact_response",
    ]
    http_status_code: int = Field(ge=100, le=599)
    response_object: LocalResponseObject
    fetched_at_utc: datetime
    response_recording_id: UUID | None = None
    recording_artist_credit_artist_ids: tuple[UUID, ...] = ()
    releases: tuple[RecordingReleaseLink, ...] = ()

    @model_validator(mode="after")
    def require_safe_exact_release_projection(self) -> RecordingReleaseLookupReceipt:
        """Require release links only when the response preserves exact recording identity."""
        if (
            self.outcome == "exact_match"
            and self.response_recording_id != self.requested_recording_id
        ):
            raise ValueError(
                "exact release lookup response recording ID does not equal requested ID"
            )
        if self.outcome != "exact_match" and (
            self.releases or self.recording_artist_credit_artist_ids
        ):
            raise ValueError("an abstained release lookup cannot retain links or artist IDs")
        return self


class _ReleaseReceiptBase(TypedDict):
    requested_recording_id: UUID
    http_status_code: int
    response_object: LocalResponseObject
    fetched_at_utc: datetime


class RecordingReleaseCoverage(FrozenModel):
    """Counts only observed links and ambiguity; no representative-release selection."""

    requested_recording_count: int = Field(ge=0)
    successful_exact_lookup_count: int = Field(ge=0)
    recordings_with_release_group_count: int = Field(ge=0)
    release_link_count: int = Field(ge=0)
    release_group_count: int = Field(ge=0)
    primary_type_counts: dict[str, int]
    compilation_release_group_count: int = Field(ge=0)
    recordings_with_release_artist_credit_mismatch_count: int = Field(ge=0)
    release_artist_credit_mismatch_count: int = Field(ge=0)
    linked_entity_limit: Literal[25] = 25


class MusicBrainzRecordingReleaseCoverageArtifact(FrozenModel):
    """Local-only recording-to-release connectivity pilot with no ranking semantics."""

    revision: Literal["musicbrainz-recording-release-coverage-v1"] = (
        "musicbrainz-recording-release-coverage-v1"
    )
    local_only: Literal[True] = True
    export_allowed: Literal[False] = False
    serving_allowed: Literal[False] = False
    cohort_artifact_file_sha256: Sha256
    cohort_recording_id_set_sha256: Sha256
    selected_recording_ids: tuple[UUID, ...]
    selected_recording_id_set_sha256: Sha256
    lookups: tuple[RecordingReleaseLookupReceipt, ...]
    coverage: RecordingReleaseCoverage


def _release_receipt_from_response(
    recording_id: UUID,
    response: httpx.Response,
    *,
    fetched_at_utc: datetime,
    response_object: LocalResponseObject,
) -> RecordingReleaseLookupReceipt:
    """Parse an exact recording response with its bounded linked-release slice."""
    base: _ReleaseReceiptBase = {
        "requested_recording_id": recording_id,
        "http_status_code": response.status_code,
        "response_object": response_object,
        "fetched_at_utc": fetched_at_utc,
    }
    if response.status_code == _HTTP_NOT_FOUND:
        return RecordingReleaseLookupReceipt(outcome="http_not_found", **base)
    if _HTTP_REDIRECT_MINIMUM <= response.status_code < _HTTP_CLIENT_ERROR_MINIMUM:
        return RecordingReleaseLookupReceipt(outcome="http_redirect", **base)
    if response.is_error:
        return RecordingReleaseLookupReceipt(outcome="http_error", **base)
    try:
        parsed = _ApiRecordingWithReleases.model_validate_json(response.content)
    except (ValidationError, ValueError):
        return RecordingReleaseLookupReceipt(outcome="invalid_response", **base)
    if parsed.id != recording_id:
        return RecordingReleaseLookupReceipt(
            outcome="nonexact_response", response_recording_id=parsed.id, **base
        )
    links = tuple(
        RecordingReleaseLink(
            release_id=release.id,
            release_group_id=release.release_group.id if release.release_group else None,
            primary_type=release.release_group.primary_type if release.release_group else None,
            compilation_secondary_type=(
                "Compilation" in release.release_group.secondary_types
                if release.release_group
                else False
            ),
            release_artist_credit_artist_ids=tuple(
                item.artist.id for item in release.artist_credit
            ),
        )
        for release in parsed.releases
    )
    return RecordingReleaseLookupReceipt(
        outcome="exact_match",
        response_recording_id=parsed.id,
        recording_artist_credit_artist_ids=tuple(item.artist.id for item in parsed.artist_credit),
        releases=links,
        **base,
    )


async def measure_exact_recording_release_coverage(  # noqa: PLR0913
    cohort: RecordingIdCohortArtifact,
    client: httpx.AsyncClient,
    *,
    user_agent: str,
    cohort_artifact_file_sha256: str,
    response_cache_directory: Path,
    settings: RecordingLookupSettings | None = None,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> MusicBrainzRecordingReleaseCoverageArtifact:
    """Measure one 25-linked-entity-limited release slice for a sorted cohort prefix."""
    if not user_agent.strip() or "/" not in user_agent or "(" not in user_agent:
        raise MusicBrainzRecordingCoverageError(
            "MusicBrainz user_agent must include an app version and contact"
        )
    resolved = settings or RecordingLookupSettings()
    selected = cohort.recording_ids[: resolved.maximum_recordings]
    next_request_at = 0.0
    receipts: list[RecordingReleaseLookupReceipt] = []
    for recording_id in selected:
        delay = next_request_at - clock()
        if delay > 0:
            await sleep(delay)
        next_request_at = clock() + MUSICBRAINZ_MIN_REQUEST_INTERVAL_SECONDS
        try:
            response = await _fetch_bounded_response(
                client,
                f"{MUSICBRAINZ_API_BASE}/recording/{recording_id}",
                user_agent,
                inclusion="releases+release-groups+artist-credits",
            )
        except httpx.HTTPError as error:
            raise MusicBrainzRecordingCoverageError(
                f"MusicBrainz release lookup failed for {recording_id}: {type(error).__name__}"
            ) from error
        response_object = _write_response_object(response_cache_directory, response.content)
        receipts.append(
            _release_receipt_from_response(
                recording_id,
                response,
                fetched_at_utc=datetime.now(UTC),
                response_object=response_object,
            )
        )
    coverage = _release_coverage(tuple(receipts), len(selected))
    return MusicBrainzRecordingReleaseCoverageArtifact(
        cohort_artifact_file_sha256=cohort_artifact_file_sha256,
        cohort_recording_id_set_sha256=cohort.recording_id_set_sha256,
        selected_recording_ids=selected,
        selected_recording_id_set_sha256=_uuid_set_sha256(selected),
        lookups=tuple(receipts),
        coverage=coverage,
    )


def _release_coverage(
    receipts: tuple[RecordingReleaseLookupReceipt, ...], requested_count: int
) -> RecordingReleaseCoverage:
    """Recompute every aggregate from safe per-lookup projections."""
    links = tuple(link for receipt in receipts for link in receipt.releases)
    grouped = {link.release_group_id for link in links if link.release_group_id is not None}
    type_counts: dict[str, int] = {}
    for link in links:
        if link.primary_type:
            type_counts[link.primary_type] = type_counts.get(link.primary_type, 0) + 1
    mismatches = tuple(
        (receipt, link)
        for receipt in receipts
        for link in receipt.releases
        if link.release_artist_credit_artist_ids != receipt.recording_artist_credit_artist_ids
    )
    return RecordingReleaseCoverage(
        requested_recording_count=requested_count,
        successful_exact_lookup_count=sum(item.outcome == "exact_match" for item in receipts),
        recordings_with_release_group_count=sum(
            any(link.release_group_id for link in item.releases) for item in receipts
        ),
        release_link_count=len(links),
        release_group_count=len(grouped),
        primary_type_counts=dict(sorted(type_counts.items())),
        compilation_release_group_count=len(
            {
                link.release_group_id
                for link in links
                if link.release_group_id and link.compilation_secondary_type
            }
        ),
        recordings_with_release_artist_credit_mismatch_count=len(
            {receipt.requested_recording_id for receipt, _ in mismatches}
        ),
        release_artist_credit_mismatch_count=len(mismatches),
    )


def replay_exact_recording_release_coverage(
    artifact: MusicBrainzRecordingReleaseCoverageArtifact, cache_directory: Path
) -> MusicBrainzRecordingReleaseCoverageArtifact:
    """Reparse the bounded raw custody objects and require exact receipt equality offline."""
    replayed: list[RecordingReleaseLookupReceipt] = []
    for receipt in artifact.lookups:
        content = _read_bounded_response_object(
            cache_directory / "sha256" / f"{receipt.response_object.sha256}.json"
        )
        if (
            len(content) != receipt.response_object.byte_size
            or hashlib.sha256(content).hexdigest() != receipt.response_object.sha256
        ):
            raise MusicBrainzRecordingCoverageError(
                "release response custody object does not match"
            )
        replayed.append(
            _release_receipt_from_response(
                receipt.requested_recording_id,
                httpx.Response(receipt.http_status_code, content=content),
                fetched_at_utc=receipt.fetched_at_utc,
                response_object=receipt.response_object,
            )
        )
    if tuple(replayed) != artifact.lookups:
        raise MusicBrainzRecordingCoverageError(
            "offline release response replay does not equal receipt"
        )
    if (
        _release_coverage(tuple(replayed), len(artifact.selected_recording_ids))
        != artifact.coverage
    ):
        raise MusicBrainzRecordingCoverageError(
            "offline release replay aggregate does not equal receipt"
        )
    return artifact
