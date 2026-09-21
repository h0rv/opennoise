"""Read exact MusicBrainz artist credits only from retained hydration cache entries."""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from pathlib import Path  # noqa: TC003 -- Pydantic resolves Path field annotations.
from typing import TYPE_CHECKING, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from opennoise.ingest.musicbrainz.release_hydration import (
    MUSICBRAINZ_API_BASE,
    MUSICBRAINZ_MIN_REQUEST_INTERVAL_SECONDS,
    CachedFailure,
    CachedResponse,
    MusicBrainzHydrationError,
    MusicBrainzReleaseHydrationArtifact,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

import httpx

ARTIST_CREDIT_ENRICHMENT_REVISION = "musicbrainz-cached-artist-credit-enrichment-v2"
ARTIST_CREDIT_REFRESH_REVISION = "musicbrainz-artist-credit-refresh-candidate-v2"


class _FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")


class _ApiModel(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True, extra="ignore")


class CachedCreditArtist(_ApiModel):
    """Exact artist identity retained by a MusicBrainz artist-credit field."""

    id: UUID
    name: str = Field(min_length=1)


class CachedArtistCreditMember(_ApiModel):
    """One ordered, source-spelled credit component."""

    artist: CachedCreditArtist
    name: str = Field(min_length=1)
    joinphrase: str = Field(default="", max_length=100)


class _CachedRecording(_ApiModel):
    id: UUID
    artist_credit: tuple[CachedArtistCreditMember, ...] | None = Field(
        default=None, alias="artist-credit", max_length=100
    )


class _CachedTrack(_ApiModel):
    recording: _CachedRecording


class _CachedMedium(_ApiModel):
    tracks: tuple[_CachedTrack, ...] = Field(default=(), max_length=2_000)


class _CachedRelease(_ApiModel):
    id: UUID
    artist_credit: tuple[CachedArtistCreditMember, ...] | None = Field(
        default=None, alias="artist-credit", max_length=100
    )
    media: tuple[_CachedMedium, ...] = Field(default=(), max_length=100)


class ArtistCreditMember(_FrozenModel):
    """Exact credit component suitable for future candidate materialization."""

    position: int = Field(ge=0)
    artist_id: UUID
    artist_name: str = Field(min_length=1)
    credited_name: str = Field(min_length=1)
    join_phrase: str = Field(max_length=100)


class CachedArtistCreditRelation(_FrozenModel):
    """One exact source-bound credit for a release or recording."""

    entity_kind: Literal["release", "recording"]
    entity_id: UUID
    source_endpoint: str = Field(min_length=1)
    observed_response_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    projection_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    members: tuple[ArtistCreditMember, ...]


class ArtistCreditAbstention(_FrozenModel):
    """A transparent reason no artist relation was materialized."""

    entity_kind: Literal["release", "recording"]
    entity_id: UUID
    reason: Literal["cache_response_missing", "artist_credit_field_not_retained"]


class CachedArtistCreditEnrichmentArtifact(_FrozenModel):
    """Versioned cache-only artist-credit candidate, never an inferred identity bridge."""

    revision: Literal["musicbrainz-cached-artist-credit-enrichment-v2"] = (
        ARTIST_CREDIT_ENRICHMENT_REVISION
    )
    source_hydration_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    credits: tuple[CachedArtistCreditRelation, ...]
    abstentions: tuple[ArtistCreditAbstention, ...]
    cache_mode: Literal["offline_cache_only"] = "offline_cache_only"
    required_upstream_request: str = (
        "GET /ws/2/release/{release_mbid}?inc=release-groups+recordings+artist-credits"
    )
    no_name_inference: Literal[True] = True


class ArtistCreditRefreshSettings(_FrozenModel):
    """Bound a refresh to the normalized releases in one hydration artifact."""

    cache_directory: Path
    offline: bool = False
    max_attempts: int = Field(default=3, gt=0, le=5)
    max_consecutive_transport_failures: int = Field(default=2, gt=0, le=3)


class ArtistCreditRefreshFailure(_FrozenModel):
    """A source endpoint failure, retained without an upstream response body."""

    release_id: UUID
    endpoint: str = Field(min_length=1)
    failure_kind: Literal[
        "request_failed", "invalid_metadata_response", "not_attempted_after_transport_failures"
    ]
    message: str = Field(min_length=1, max_length=500)


class ArtistCreditRefreshCandidateArtifact(_FrozenModel):
    """Non-serving, exact-ID artist-credit candidate from a bounded MB refresh."""

    revision: Literal["musicbrainz-artist-credit-refresh-candidate-v2"] = (
        ARTIST_CREDIT_REFRESH_REVISION
    )
    source_hydration_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    requested_release_ids: tuple[UUID, ...]
    credits: tuple[CachedArtistCreditRelation, ...]
    abstentions: tuple[ArtistCreditAbstention, ...]
    failures: tuple[ArtistCreditRefreshFailure, ...]
    cache_mode: Literal["refresh_then_cache", "offline_cache_only"]
    required_upstream_request: str = (
        "GET /ws/2/release/{release_mbid}?inc=release-groups+recordings+artist-credits"
    )
    minimum_request_interval_seconds: float = MUSICBRAINZ_MIN_REQUEST_INTERVAL_SECONDS
    no_name_inference: Literal[True] = True


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _projection_sha256(*, endpoint: str, payload: dict[str, object]) -> str:
    """Hash the replayable safe projection, never an unavailable raw response body."""
    encoded = json.dumps(
        {"endpoint": endpoint, "payload": payload},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return _sha256(encoded)


def _verified_projection(cached: CachedResponse) -> str:
    """Require v2 projection provenance before it may support an artist relation."""
    if cached.projection_sha256 is None:
        raise MusicBrainzHydrationError("unverified v1 artist-credit cache projection")
    computed = _projection_sha256(endpoint=cached.endpoint, payload=cached.payload)
    if computed != cached.projection_sha256:
        raise MusicBrainzHydrationError("artist-credit cache projection SHA-256 mismatch")
    return computed


def _members(items: tuple[CachedArtistCreditMember, ...]) -> tuple[ArtistCreditMember, ...]:
    return tuple(
        ArtistCreditMember(
            position=position,
            artist_id=item.artist.id,
            artist_name=item.artist.name,
            credited_name=item.name,
            join_phrase=item.joinphrase,
        )
        for position, item in enumerate(items)
    )


def _parse_cached_release(cached: CachedResponse) -> _CachedRelease:
    """Reparse JSON cache values through the strict API boundary model."""
    try:
        return _CachedRelease.model_validate_json(json.dumps(cached.payload, separators=(",", ":")))
    except ValueError as error:
        raise MusicBrainzHydrationError(
            f"invalid cached release payload: {cached.endpoint}"
        ) from error


def _cache_releases(cache_directory: Path) -> dict[UUID, CachedResponse]:
    """Index retained release responses; malformed cache entries are not silently trusted."""
    releases: dict[UUID, CachedResponse] = {}
    for path in sorted(cache_directory.glob("*.json")):
        try:
            raw = json.loads(path.read_bytes())
        except ValueError as error:
            raise MusicBrainzHydrationError(
                f"invalid hydration cache entry: {path.name}"
            ) from error
        if raw.get("record_kind") == "failure":
            CachedFailure.model_validate(raw)
            continue
        try:
            cached = CachedResponse.model_validate(raw)
        except ValueError as error:
            raise MusicBrainzHydrationError(
                f"invalid hydration cache success entry: {path.name}"
            ) from error
        if not cached.endpoint.startswith("release/"):
            continue
        release = _parse_cached_release(cached)
        if cached.endpoint != f"release/{release.id}":
            raise MusicBrainzHydrationError(
                f"cached release endpoint does not match payload: {cached.endpoint}"
            )
        previous = releases.setdefault(release.id, cached)
        if previous.response_sha256 != cached.response_sha256:
            raise MusicBrainzHydrationError(f"conflicting cached release responses: {release.id}")
    return releases


def build_cached_artist_credit_enrichment(  # noqa: C901 - explicit release/recording abstention ledger.
    *, source_hydration_artifact_path: Path, cache_directory: Path
) -> CachedArtistCreditEnrichmentArtifact:
    """Build an offline-only enrichment or abstain when the safe cache lacks credits."""
    payload = source_hydration_artifact_path.read_bytes()
    source_hydration_sha256 = _sha256(payload)
    artifact = MusicBrainzReleaseHydrationArtifact.model_validate_json(payload)
    cache = _cache_releases(cache_directory)
    release_ids = {release.release_id for release in artifact.releases}
    recording_ids = {
        track.recording_id
        for release in artifact.releases
        for medium in release.media
        for track in medium.tracks
    }
    relations: list[CachedArtistCreditRelation] = []
    abstentions: list[ArtistCreditAbstention] = []
    recordings: dict[UUID, tuple[tuple[CachedArtistCreditMember, ...] | None, CachedResponse]] = {}
    for release_id in sorted(release_ids, key=str):
        cached = cache.get(release_id)
        if cached is None:
            abstentions.append(
                ArtistCreditAbstention(
                    entity_kind="release", entity_id=release_id, reason="cache_response_missing"
                )
            )
            continue
        parsed = _parse_cached_release(cached)
        if parsed.artist_credit is None:
            abstentions.append(
                ArtistCreditAbstention(
                    entity_kind="release",
                    entity_id=release_id,
                    reason="artist_credit_field_not_retained",
                )
            )
        else:
            relations.append(
                CachedArtistCreditRelation(
                    entity_kind="release",
                    entity_id=release_id,
                    source_endpoint=cached.endpoint,
                    observed_response_sha256=cached.response_sha256,
                    projection_sha256=_verified_projection(cached),
                    members=_members(parsed.artist_credit),
                )
            )
        for medium in parsed.media:
            for track in medium.tracks:
                if track.recording.id not in recording_ids:
                    continue
                previous = recordings.setdefault(
                    track.recording.id, (track.recording.artist_credit, cached)
                )
                if previous[0] != track.recording.artist_credit:
                    raise MusicBrainzHydrationError(
                        f"conflicting cached recording artist credits: {track.recording.id}"
                    )
    for recording_id in sorted(recording_ids, key=str):
        cached_recording = recordings.get(recording_id)
        if cached_recording is None:
            abstentions.append(
                ArtistCreditAbstention(
                    entity_kind="recording", entity_id=recording_id, reason="cache_response_missing"
                )
            )
            continue
        artist_credit, cached = cached_recording
        if artist_credit is None:
            abstentions.append(
                ArtistCreditAbstention(
                    entity_kind="recording",
                    entity_id=recording_id,
                    reason="artist_credit_field_not_retained",
                )
            )
            continue
        relations.append(
            CachedArtistCreditRelation(
                entity_kind="recording",
                entity_id=recording_id,
                source_endpoint=cached.endpoint,
                observed_response_sha256=cached.response_sha256,
                projection_sha256=_verified_projection(cached),
                members=_members(artist_credit),
            )
        )
    return CachedArtistCreditEnrichmentArtifact(
        source_hydration_sha256=source_hydration_sha256,
        credits=tuple(sorted(relations, key=lambda item: (item.entity_kind, str(item.entity_id)))),
        abstentions=tuple(
            sorted(abstentions, key=lambda item: (item.entity_kind, str(item.entity_id)))
        ),
    )


def load_hydration_artifact(path: Path) -> tuple[MusicBrainzReleaseHydrationArtifact, str]:
    """Load the exact input bytes used to bind enrichment provenance."""
    payload = path.read_bytes()
    return MusicBrainzReleaseHydrationArtifact.model_validate_json(payload), _sha256(payload)


def write_cached_artist_credit_enrichment(
    artifact: CachedArtistCreditEnrichmentArtifact, *, output: Path
) -> str:
    """Write a deterministic local candidate artifact and return its content hash."""
    payload = artifact.model_dump_json(exclude_none=True) + "\n"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(payload, encoding="utf-8")
    return _sha256(payload.encode("utf-8"))


class MusicBrainzArtistCreditRefreshAdapter:
    """Sequential official-API refresher that only retains exact artist-credit fields.

    Its cache directory is intentionally distinct from core hydration: identical
    release paths can have different MusicBrainz ``inc`` projections.
    """

    def __init__(
        self,
        client: httpx.AsyncClient,
        settings: ArtistCreditRefreshSettings,
        *,
        user_agent: str,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        """Configure a caller-owned client and separate artist-credit cache."""
        if not user_agent.strip() or "/" not in user_agent or "(" not in user_agent:
            raise ValueError("MusicBrainz user_agent must include an app version and contact")
        self._client = client
        self._settings = settings
        self._user_agent = user_agent
        self._clock = clock
        self._sleep = sleep
        self._next_request_at = 0.0
        self._upstream_request_count = 0

    @property
    def upstream_request_count(self) -> int:
        """Return cache misses that reached the official MusicBrainz endpoint."""
        return self._upstream_request_count

    def _cache_path(self, endpoint: str) -> Path:
        return self._settings.cache_directory / f"{_sha256(endpoint.encode())}.json"

    async def _wait_for_rate_limit(self) -> None:
        now = self._clock()
        delay = self._next_request_at - now
        if delay > 0:
            await self._sleep(delay)
            now = self._clock()
        self._next_request_at = now + MUSICBRAINZ_MIN_REQUEST_INTERVAL_SECONDS

    def _cached(self, endpoint: str) -> _CachedRelease | ArtistCreditRefreshFailure | None:
        path = self._cache_path(endpoint)
        if not path.is_file():
            return None
        try:
            raw = path.read_bytes()
            try:
                cached = CachedResponse.model_validate_json(raw)
            except ValueError:
                failed = CachedFailure.model_validate_json(raw)
                if failed.endpoint != endpoint:
                    raise MusicBrainzHydrationError(
                        "artist-credit cache endpoint mismatch"
                    ) from None
                if not self._settings.offline:
                    return None
                return ArtistCreditRefreshFailure(
                    release_id=UUID(endpoint.removeprefix("release/")),
                    endpoint=endpoint,
                    failure_kind=failed.failure_kind,
                    message=failed.message,
                )
            if cached.endpoint != endpoint:
                raise MusicBrainzHydrationError("artist-credit cache endpoint mismatch")
            _verified_projection(cached)
            return _parse_cached_release(cached)
        except (OSError, ValueError) as error:
            raise MusicBrainzHydrationError(f"invalid artist-credit cache entry: {path}") from error

    def _write_cache(self, entry: CachedResponse | CachedFailure) -> None:
        self._settings.cache_directory.mkdir(parents=True, exist_ok=True)
        path = self._cache_path(entry.endpoint)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(entry.model_dump_json(exclude_none=True), encoding="utf-8")
        temporary.replace(path)

    async def _fetch(self, release_id: UUID) -> _CachedRelease | ArtistCreditRefreshFailure:
        endpoint = f"release/{release_id}"
        cached = self._cached(endpoint)
        if cached is not None:
            return cached
        if self._settings.offline:
            return ArtistCreditRefreshFailure(
                release_id=release_id,
                endpoint=endpoint,
                failure_kind="request_failed",
                message="offline replay cache miss",
            )
        for attempt in range(self._settings.max_attempts):
            await self._wait_for_rate_limit()
            try:
                self._upstream_request_count += 1
                response = await self._client.get(
                    f"{MUSICBRAINZ_API_BASE}/{endpoint}",
                    params={"fmt": "json", "inc": "release-groups+recordings+artist-credits"},
                    headers={"User-Agent": self._user_agent, "Accept": "application/json"},
                )
                response.raise_for_status()
                parsed = _CachedRelease.model_validate_json(response.content)
            except (httpx.HTTPError, ValueError) as error:
                if attempt + 1 < self._settings.max_attempts:
                    await self._sleep(float(2**attempt))
                    continue
                failure_kind: Literal["request_failed", "invalid_metadata_response"]
                failure_kind = (
                    "request_failed"
                    if isinstance(error, httpx.HTTPError)
                    else "invalid_metadata_response"
                )
                message = f"MusicBrainz artist-credit refresh failed: {endpoint}"
                failure = CachedFailure(
                    endpoint=endpoint, failure_kind=failure_kind, message=message
                )
                self._write_cache(failure)
                return ArtistCreditRefreshFailure(
                    release_id=release_id,
                    endpoint=endpoint,
                    failure_kind=failure_kind,
                    message=message,
                )
            safe = CachedResponse(
                endpoint=endpoint,
                response_sha256=_sha256(response.content),
                projection_sha256=_projection_sha256(
                    endpoint=endpoint,
                    payload=parsed.model_dump(mode="json", by_alias=True, exclude_none=True),
                ),
                payload=parsed.model_dump(mode="json", by_alias=True, exclude_none=True),
            )
            self._write_cache(safe)
            return parsed
        raise AssertionError("bounded retry loop exhausted without returning")

    async def refresh(  # noqa: C901, PLR0912
        self, *, source_hydration_artifact_path: Path
    ) -> ArtistCreditRefreshCandidateArtifact:
        """Refresh exactly normalized release IDs, with no database or name lookup."""
        artifact, source_hydration_sha256 = load_hydration_artifact(source_hydration_artifact_path)
        release_ids = tuple(sorted({release.release_id for release in artifact.releases}, key=str))
        recording_ids = {
            track.recording_id
            for release in artifact.releases
            for medium in release.media
            for track in medium.tracks
        }
        relations: list[CachedArtistCreditRelation] = []
        abstentions: list[ArtistCreditAbstention] = []
        failures: list[ArtistCreditRefreshFailure] = []
        recordings: dict[UUID, tuple[tuple[CachedArtistCreditMember, ...] | None, UUID, str]] = {}
        consecutive_transport_failures = 0
        for _position, release_id in enumerate(release_ids):
            result = await self._fetch(release_id)
            endpoint = f"release/{release_id}"
            if isinstance(result, ArtistCreditRefreshFailure):
                failures.append(result)
                abstentions.append(
                    ArtistCreditAbstention(
                        entity_kind="release", entity_id=release_id, reason="cache_response_missing"
                    )
                )
                if result.failure_kind == "request_failed":
                    consecutive_transport_failures += 1
                else:
                    consecutive_transport_failures = 0
                if (
                    not self._settings.offline
                    and consecutive_transport_failures
                    >= self._settings.max_consecutive_transport_failures
                ):
                    for skipped_id in release_ids[_position + 1 :]:
                        skipped_endpoint = f"release/{skipped_id}"
                        failures.append(
                            ArtistCreditRefreshFailure(
                                release_id=skipped_id,
                                endpoint=skipped_endpoint,
                                failure_kind="not_attempted_after_transport_failures",
                                message=(
                                    "not attempted after repeated MusicBrainz transport failures"
                                ),
                            )
                        )
                        abstentions.append(
                            ArtistCreditAbstention(
                                entity_kind="release",
                                entity_id=skipped_id,
                                reason="cache_response_missing",
                            )
                        )
                    break
                continue
            cached = self._cached(endpoint)
            if not isinstance(cached, _CachedRelease):
                raise MusicBrainzHydrationError("artist-credit success cache was not retained")
            raw = CachedResponse.model_validate_json(self._cache_path(endpoint).read_bytes())
            projection_sha256 = _verified_projection(raw)
            if result.artist_credit is None:
                abstentions.append(
                    ArtistCreditAbstention(
                        entity_kind="release",
                        entity_id=release_id,
                        reason="artist_credit_field_not_retained",
                    )
                )
            else:
                relations.append(
                    CachedArtistCreditRelation(
                        entity_kind="release",
                        entity_id=release_id,
                        source_endpoint=endpoint,
                        observed_response_sha256=raw.response_sha256,
                        projection_sha256=projection_sha256,
                        members=_members(result.artist_credit),
                    )
                )
            for medium in result.media:
                for track in medium.tracks:
                    if track.recording.id in recording_ids:
                        previous = recordings.setdefault(
                            track.recording.id,
                            (track.recording.artist_credit, release_id, projection_sha256),
                        )
                        if previous[0] != track.recording.artist_credit:
                            raise MusicBrainzHydrationError(
                                "conflicting refreshed recording artist credits: "
                                f"{track.recording.id}"
                            )
        for recording_id in sorted(recording_ids, key=str):
            found = recordings.get(recording_id)
            if found is None:
                abstentions.append(
                    ArtistCreditAbstention(
                        entity_kind="recording",
                        entity_id=recording_id,
                        reason="cache_response_missing",
                    )
                )
                continue
            members, release_id, projection_sha256 = found
            if members is None:
                abstentions.append(
                    ArtistCreditAbstention(
                        entity_kind="recording",
                        entity_id=recording_id,
                        reason="artist_credit_field_not_retained",
                    )
                )
            else:
                relations.append(
                    CachedArtistCreditRelation(
                        entity_kind="recording",
                        entity_id=recording_id,
                        source_endpoint=f"release/{release_id}",
                        observed_response_sha256=CachedResponse.model_validate_json(
                            self._cache_path(f"release/{release_id}").read_bytes()
                        ).response_sha256,
                        projection_sha256=projection_sha256,
                        members=_members(members),
                    )
                )
        return ArtistCreditRefreshCandidateArtifact(
            source_hydration_sha256=source_hydration_sha256,
            requested_release_ids=release_ids,
            credits=tuple(
                sorted(relations, key=lambda item: (item.entity_kind, str(item.entity_id)))
            ),
            abstentions=tuple(
                sorted(abstentions, key=lambda item: (item.entity_kind, str(item.entity_id)))
            ),
            failures=tuple(sorted(failures, key=lambda item: str(item.release_id))),
            cache_mode="offline_cache_only" if self._settings.offline else "refresh_then_cache",
        )


def write_artist_credit_refresh_candidate(
    artifact: ArtistCreditRefreshCandidateArtifact, *, output: Path
) -> str:
    """Write a deterministic local artifact; this never materializes a database."""
    payload = artifact.model_dump_json(exclude_none=True) + "\n"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(payload, encoding="utf-8")
    return _sha256(payload.encode("utf-8"))
