# ruff: noqa: E501
"""Hydrate a small representative MusicBrainz release and track metadata slice.

This module intentionally has no audio, preview, URL, artwork, genre, or tag
fields.  It reads a deterministic subset of the existing representative export,
fetches only MusicBrainz core release metadata, and retains a replayable JSON
artifact through the normal object-store boundary.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import sqlite3  # noqa: TC003 -- SQLite annotations and connections both resolve at runtime.
import time
from pathlib import Path  # noqa: TC003 -- Pydantic resolves this annotation at runtime.
from typing import TYPE_CHECKING, Literal
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from musix.db import Database
from musix.serving.metadata.metadata_representatives import (
    MetadataRepresentativeArtifact,
    MetadataRepresentativeItem,
)
from musix.policy import require_metadata_file
from musix.storage import ObjectKey, ObjectStore, ObjectWrite

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

MUSICBRAINZ_API_BASE = "https://musicbrainz.org/ws/2"
MUSICBRAINZ_MIN_REQUEST_INTERVAL_SECONDS = 1.0
HYDRATION_REVISION = "musicbrainz-release-track-hydration-v1"
MAX_ARTIFACT_BYTES = 16 * 1024 * 1024
TRANSIENT_STATUS_CODES = frozenset({429, 500, 502, 503, 504})
_REPRESENTATIVE_ID_PART_COUNT = 3


class MusicBrainzHydrationError(RuntimeError):
    """Report a bounded MusicBrainz metadata hydration failure."""


class _FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")


class _ApiModel(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True, extra="ignore")


class HydrationSettings(_FrozenModel):
    """Bound one deterministic, sequential public API hydration run."""

    max_genres: int = Field(default=20, gt=0, le=100)
    max_releases_per_seed: int = Field(default=1, gt=0, le=3)
    max_attempts: int = Field(default=3, gt=0, le=5)
    cache_directory: Path
    offline: bool = False


class MusicBrainzReleaseReference(_ApiModel):
    """Parse a concrete release reference returned from a seed lookup."""

    id: UUID
    title: str = Field(min_length=1)
    date: str | None = None
    country: str | None = None


class MusicBrainzReleaseGroupSeed(_ApiModel):
    """Parse only the release references needed from one release-group lookup."""

    id: UUID
    releases: tuple[MusicBrainzReleaseReference, ...] = Field(default=(), max_length=100)


class MusicBrainzRecordingSeed(_ApiModel):
    """Parse only the release references needed from one recording lookup."""

    id: UUID
    releases: tuple[MusicBrainzReleaseReference, ...] = Field(default=(), max_length=100)


class MusicBrainzReleaseGroupReference(_ApiModel):
    """Identify the exact parent release group in a concrete release response."""

    id: UUID
    title: str = Field(min_length=1)


class MusicBrainzTrackRecording(_ApiModel):
    """Parse a referenced recording, never an audio location or preview."""

    id: UUID
    title: str = Field(min_length=1)
    length: int | None = Field(default=None, ge=0)


class MusicBrainzTrack(_ApiModel):
    """Parse one ordered release track from the official core metadata response."""

    id: UUID
    position: int = Field(gt=0)
    number: str = Field(min_length=1)
    title: str = Field(min_length=1)
    length: int | None = Field(default=None, ge=0)
    recording: MusicBrainzTrackRecording


class MusicBrainzMedium(_ApiModel):
    """Parse one ordered release medium and its ordered metadata tracks."""

    position: int = Field(gt=0)
    format: str | None = None
    track_count: int | None = Field(default=None, alias="track-count", ge=0)
    tracks: tuple[MusicBrainzTrack, ...] = Field(default=(), max_length=2_000)

    @model_validator(mode="after")
    def positions_are_unique(self) -> MusicBrainzMedium:
        """Reject an upstream medium that cannot preserve exact ordering."""
        if len({track.position for track in self.tracks}) != len(self.tracks):
            raise ValueError("MusicBrainz medium repeats a track position")
        return self


class MusicBrainzReleaseMetadata(_ApiModel):
    """Parse core release metadata plus its physical/logical media structure."""

    id: UUID
    title: str = Field(min_length=1)
    release_group: MusicBrainzReleaseGroupReference = Field(alias="release-group")
    status: str | None = None
    packaging: str | None = None
    country: str | None = None
    date: str | None = None
    media: tuple[MusicBrainzMedium, ...] = Field(default=(), max_length=100)

    @model_validator(mode="after")
    def media_positions_are_unique(self) -> MusicBrainzReleaseMetadata:
        """Reject an upstream release that cannot preserve exact medium ordering."""
        if len({medium.position for medium in self.media}) != len(self.media):
            raise ValueError("MusicBrainz release repeats a medium position")
        return self


class CachedResponse(_FrozenModel):
    """Store a parsed safe projection instead of retaining an arbitrary API body."""

    endpoint: str = Field(min_length=1)
    response_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    payload: dict[str, object]


class HydrationEvidence(_FrozenModel):
    """Bind a retained release to a selected representative and exact API response."""

    representative_kind: Literal["release_group", "recording"]
    representative_id: str = Field(min_length=1)
    representative_rank: int = Field(gt=0)
    endpoint: str = Field(min_length=1)
    response_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class HydratedTrack(_FrozenModel):
    """A track listing is metadata only and is never a playable media item."""

    track_id: UUID
    recording_id: UUID
    title: str = Field(min_length=1)
    position: int = Field(gt=0)
    number: str = Field(min_length=1)
    duration_ms: int | None = Field(default=None, ge=0)
    recording_duration_ms: int | None = Field(default=None, ge=0)
    semantics: Literal["track_metadata_not_playable_media"] = "track_metadata_not_playable_media"


class HydratedMedium(_FrozenModel):
    """An ordered release medium that carries no file, image, or stream location."""

    position: int = Field(gt=0)
    format: str | None = None
    track_count: int | None = Field(default=None, ge=0)
    tracks: tuple[HydratedTrack, ...]


class HydratedRelease(_FrozenModel):
    """One concrete release with exact upstream IDs and ordered track metadata."""

    release_id: UUID
    release_group_id: UUID
    title: str = Field(min_length=1)
    release_group_title: str = Field(min_length=1)
    status: str | None = None
    packaging: str | None = None
    country: str | None = None
    date: str | None = None
    media: tuple[HydratedMedium, ...]
    evidence: tuple[HydrationEvidence, ...] = Field(min_length=1)


class MusicBrainzReleaseHydrationArtifact(_FrozenModel):
    """Replayable small metadata-only release/medium/track catalog slice."""

    revision: Literal["musicbrainz-release-track-hydration-v1"] = HYDRATION_REVISION
    selection_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_representative_artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    releases: tuple[HydratedRelease, ...]
    content_policy: Literal["core_metadata_only_no_audio_preview_artwork_or_genres"] = (
        "core_metadata_only_no_audio_preview_artwork_or_genres"
    )
    track_semantics: Literal["track_metadata_not_playable_media"] = (
        "track_metadata_not_playable_media"
    )


class HydrationPublication(_FrozenModel):
    """Receipt for the immutable replay artifact and its exact catalog counts."""

    artifact: ObjectWrite
    release_count: int = Field(ge=0)
    medium_count: int = Field(ge=0)
    track_count: int = Field(ge=0)
    missing_seed_count: int = Field(ge=0)


class CatalogHydrationResult(_FrozenModel):
    """Count idempotently materialized release catalog rows."""

    releases: int = Field(ge=0)
    media: int = Field(ge=0)
    tracks: int = Field(ge=0)
    recordings: int = Field(ge=0)


class HydrationFailure(_FrozenModel):
    """One deterministic, non-fatal representative hydration abstention."""

    representative_kind: Literal["release_group", "recording"]
    representative_id: str = Field(min_length=1)
    representative_rank: int = Field(gt=0)
    error_type: str = Field(min_length=1)
    message: str = Field(min_length=1)


class HydrationBatchResult(_FrozenModel):
    """Keep the successfully hydrated subset and typed abstentions together."""

    artifact: MusicBrainzReleaseHydrationArtifact
    selected_seed_count: int = Field(ge=0)
    failures: tuple[HydrationFailure, ...]


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _canonical_bytes(value: BaseModel) -> bytes:
    return value.model_dump_json(exclude_none=True, by_alias=True).encode("utf-8")


def _endpoint_key(endpoint: str) -> str:
    return hashlib.sha256(endpoint.encode("utf-8")).hexdigest()


def _representative_id(item: MetadataRepresentativeItem) -> UUID:
    prefix = f"musicbrainz:{item.entity_kind.replace('_', '-')}"
    parts = item.entity_id.split(":")
    if len(parts) != _REPRESENTATIVE_ID_PART_COUNT or ":".join(parts[:2]) != prefix:
        raise MusicBrainzHydrationError(
            f"representative has no exact MusicBrainz {item.entity_kind} ID: {item.entity_id}"
        )
    try:
        return UUID(parts[2])
    except ValueError as error:
        raise MusicBrainzHydrationError("representative ID is not a UUID") from error


def select_representative_seeds(
    artifact: MetadataRepresentativeArtifact, *, max_genres: int
) -> tuple[MetadataRepresentativeItem, ...]:
    """Choose one stable release-group-or-recording seed for each first N genres."""
    ordered = sorted(
        artifact.items,
        key=lambda item: (
            item.genre_id,
            item.rank,
            0 if item.entity_kind == "release_group" else 1,
            item.entity_id,
        ),
    )
    selected: list[MetadataRepresentativeItem] = []
    seen_genres: set[str] = set()
    for item in ordered:
        if item.genre_id in seen_genres:
            continue
        _representative_id(item)
        seen_genres.add(item.genre_id)
        selected.append(item)
        if len(selected) == max_genres:
            break
    return tuple(selected)


class MusicBrainzReleaseTrackHydrationAdapter:
    """A sequential, cached, rate-limited adapter for core release metadata only."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        settings: HydrationSettings,
        *,
        user_agent: str,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        """Keep the caller-owned client and bounded replay/rate-limit configuration."""
        if not user_agent.strip() or "/" not in user_agent or "(" not in user_agent:
            raise ValueError("MusicBrainz user_agent must include an app version and contact")
        self._client = client
        self._settings = settings
        self._user_agent = user_agent
        self._clock = clock
        self._sleep = sleep
        self._next_request_at = 0.0
        self._rate_lock = asyncio.Lock()
        self._upstream_request_count = 0

    @property
    def upstream_request_count(self) -> int:
        """Return requests that reached MusicBrainz rather than a local replay cache."""
        return self._upstream_request_count

    async def _wait_for_rate_limit(self) -> None:
        async with self._rate_lock:
            now = self._clock()
            delay = self._next_request_at - now
            if delay > 0:
                await self._sleep(delay)
                now = self._clock()
            self._next_request_at = now + MUSICBRAINZ_MIN_REQUEST_INTERVAL_SECONDS

    def _cache_path(self, endpoint: str) -> Path:
        return self._settings.cache_directory / f"{_endpoint_key(endpoint)}.json"

    def _cached(self, endpoint: str, model: type[_ApiModel]) -> _ApiModel | None:
        path = self._cache_path(endpoint)
        if not path.is_file():
            return None
        try:
            cached = CachedResponse.model_validate_json(path.read_bytes())
        except (OSError, ValidationError, ValueError) as error:
            raise MusicBrainzHydrationError(f"invalid hydration cache entry: {path}") from error
        if cached.endpoint != endpoint:
            raise MusicBrainzHydrationError("hydration cache endpoint mismatch")
        return model.model_validate_json(json.dumps(cached.payload, separators=(",", ":")))

    def _cache(self, endpoint: str, response: bytes, model: _ApiModel) -> str:
        self._settings.cache_directory.mkdir(parents=True, exist_ok=True)
        safe = CachedResponse(
            endpoint=endpoint,
            response_sha256=_sha256(response),
            payload=model.model_dump(mode="json", by_alias=True, exclude_none=True),
        )
        path = self._cache_path(endpoint)
        temporary = path.with_suffix(".tmp")
        temporary.write_bytes(_canonical_bytes(safe))
        temporary.replace(path)
        return safe.response_sha256

    async def _fetch(self, endpoint: str, model: type[_ApiModel]) -> tuple[_ApiModel, str]:
        cached = self._cached(endpoint, model)
        if cached is not None:
            cache = CachedResponse.model_validate_json(self._cache_path(endpoint).read_bytes())
            return cached, cache.response_sha256
        if self._settings.offline:
            raise MusicBrainzHydrationError(f"offline replay cache miss: {endpoint}")
        for attempt in range(self._settings.max_attempts):
            await self._wait_for_rate_limit()
            try:
                inclusion = (
                    "release-groups+recordings" if endpoint.startswith("release/") else "releases"
                )
                self._upstream_request_count += 1
                response = await self._client.get(
                    f"{MUSICBRAINZ_API_BASE}/{endpoint}",
                    params={"fmt": "json", "inc": inclusion},
                    headers={"User-Agent": self._user_agent, "Accept": "application/json"},
                )
            except httpx.HTTPError as error:
                if attempt + 1 == self._settings.max_attempts:
                    message = f"MusicBrainz request failed: {endpoint}"
                    raise MusicBrainzHydrationError(message) from error
                await self._sleep(float(2**attempt))
                continue
            should_retry = (
                response.status_code in TRANSIENT_STATUS_CODES
                and attempt + 1 < self._settings.max_attempts
            )
            if should_retry:
                retry_after = response.headers.get("Retry-After")
                delay = (
                    float(retry_after)
                    if retry_after and retry_after.isdigit()
                    else float(2**attempt)
                )
                await self._sleep(min(delay, 30.0))
                continue
            try:
                response.raise_for_status()
                parsed = model.model_validate_json(response.content)
            except (httpx.HTTPStatusError, ValidationError, ValueError) as error:
                message = f"invalid MusicBrainz metadata response: {endpoint}"
                raise MusicBrainzHydrationError(message) from error
            return parsed, self._cache(endpoint, response.content, parsed)
        raise AssertionError("bounded retry loop exhausted without returning")

    async def hydrate(
        self, representative_artifact: MetadataRepresentativeArtifact, *, source_sha256: str
    ) -> MusicBrainzReleaseHydrationArtifact:
        """Fetch a deterministic, de-duplicated set of releases and their track listings."""
        seeds = select_representative_seeds(
            representative_artifact, max_genres=self._settings.max_genres
        )
        selected_json = json.dumps(
            [item.model_dump(mode="json") for item in seeds],
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        evidence_by_release: dict[UUID, list[HydrationEvidence]] = {}
        for seed in seeds:
            seed_id = _representative_id(seed)
            endpoint = f"release-group/{seed_id}"
            if seed.entity_kind != "release_group":
                endpoint = f"recording/{seed_id}"
            model: type[_ApiModel] = (
                MusicBrainzReleaseGroupSeed
                if seed.entity_kind == "release_group"
                else MusicBrainzRecordingSeed
            )
            response, response_sha = await self._fetch(endpoint, model)
            if not isinstance(response, (MusicBrainzReleaseGroupSeed, MusicBrainzRecordingSeed)):
                raise TypeError("seed model cannot contain another response type")
            chosen = sorted(
                response.releases,
                key=lambda release: (
                    release.date or "9999-99-99",
                    release.country or "",
                    str(release.id),
                ),
            )[: self._settings.max_releases_per_seed]
            for release in chosen:
                evidence_by_release.setdefault(release.id, []).append(
                    HydrationEvidence(
                        representative_kind=seed.entity_kind,
                        representative_id=seed.entity_id,
                        representative_rank=seed.rank,
                        endpoint=endpoint,
                        response_sha256=response_sha,
                    )
                )
        hydrated: list[HydratedRelease] = []
        for release_id in sorted(evidence_by_release, key=str):
            endpoint = f"release/{release_id}"
            response, response_sha = await self._fetch(endpoint, MusicBrainzReleaseMetadata)
            if not isinstance(response, MusicBrainzReleaseMetadata):
                raise TypeError("release endpoint returned the wrong parsed model")
            evidence = (
                *evidence_by_release[release_id],
                HydrationEvidence(
                    representative_kind=evidence_by_release[release_id][0].representative_kind,
                    representative_id=evidence_by_release[release_id][0].representative_id,
                    representative_rank=evidence_by_release[release_id][0].representative_rank,
                    endpoint=endpoint,
                    response_sha256=response_sha,
                ),
            )
            media = tuple(
                HydratedMedium(
                    position=medium.position,
                    format=medium.format,
                    track_count=medium.track_count,
                    tracks=tuple(
                        HydratedTrack(
                            track_id=track.id,
                            recording_id=track.recording.id,
                            title=track.title,
                            position=track.position,
                            number=track.number,
                            duration_ms=track.length,
                            recording_duration_ms=track.recording.length,
                        )
                        for track in sorted(medium.tracks, key=lambda track: track.position)
                    ),
                )
                for medium in sorted(response.media, key=lambda medium: medium.position)
            )
            hydrated.append(
                HydratedRelease(
                    release_id=response.id,
                    release_group_id=response.release_group.id,
                    title=response.title,
                    release_group_title=response.release_group.title,
                    status=response.status,
                    packaging=response.packaging,
                    country=response.country,
                    date=response.date,
                    media=media,
                    evidence=evidence,
                )
            )
        return MusicBrainzReleaseHydrationArtifact(
            selection_sha256=_sha256(selected_json),
            source_representative_artifact_sha256=source_sha256,
            releases=tuple(hydrated),
        )

    async def hydrate_batch(
        self, representative_artifact: MetadataRepresentativeArtifact, *, source_sha256: str
    ) -> HydrationBatchResult:
        """Continue through the bounded deterministic seed list after individual failures."""
        seeds = select_representative_seeds(
            representative_artifact, max_genres=self._settings.max_genres
        )
        releases: list[HydratedRelease] = []
        failures: list[HydrationFailure] = []
        for seed in seeds:
            single = representative_artifact.model_copy(update={"items": (seed,)})
            try:
                result = await self.hydrate(single, source_sha256=source_sha256)
            except MusicBrainzHydrationError as error:
                failures.append(
                    HydrationFailure(
                        representative_kind=seed.entity_kind,
                        representative_id=seed.entity_id,
                        representative_rank=seed.rank,
                        error_type=type(error).__name__,
                        message=str(error),
                    )
                )
                continue
            releases.extend(result.releases)
        selection = json.dumps(
            [item.model_dump(mode="json") for item in seeds],
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return HydrationBatchResult(
            artifact=MusicBrainzReleaseHydrationArtifact(
                selection_sha256=_sha256(selection),
                source_representative_artifact_sha256=source_sha256,
                releases=tuple(sorted(releases, key=lambda release: str(release.release_id))),
            ),
            selected_seed_count=len(seeds),
            failures=tuple(failures),
        )


def load_representative_artifact(path: Path) -> tuple[MetadataRepresentativeArtifact, str]:
    """Read the existing representative selection as the exact hydration input."""
    require_metadata_file(path.resolve(strict=True))
    payload = path.read_bytes()
    return MetadataRepresentativeArtifact.model_validate_json(payload), _sha256(payload)


def write_hydration_artifact(
    artifact: MusicBrainzReleaseHydrationArtifact,
    *,
    output: Path,
    store: ObjectStore,
) -> HydrationPublication:
    """Write and immutably retain a metadata-only hydration artifact for offline replay."""
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = _canonical_bytes(artifact) + b"\n"
    if len(payload) > MAX_ARTIFACT_BYTES:
        raise MusicBrainzHydrationError("hydration artifact exceeds the 16 MiB bound")
    output.write_bytes(payload)
    sha256 = _sha256(payload)
    key = ObjectKey(value=f"musicbrainz-release-hydrations/sha256/{sha256}.json")
    stored = store.push(output, key)
    if (stored.sha256, stored.byte_size) != (sha256, len(payload)):
        raise MusicBrainzHydrationError("object store changed hydration artifact")
    media = tuple(medium for release in artifact.releases for medium in release.media)
    return HydrationPublication(
        artifact=stored,
        release_count=len(artifact.releases),
        medium_count=len(media),
        track_count=sum(len(medium.tracks) for medium in media),
        missing_seed_count=0,
    )


def artifact_counts(artifact: MusicBrainzReleaseHydrationArtifact) -> tuple[int, int, int]:
    """Return release, medium, and track counts without treating tracks as media files."""
    media = tuple(medium for release in artifact.releases for medium in release.media)
    return len(artifact.releases), len(media), sum(len(medium.tracks) for medium in media)


def _one_id(connection: sqlite3.Connection, query: str, values: tuple[object, ...]) -> int:
    row = connection.execute(query, values).fetchone()
    if row is None:
        raise MusicBrainzHydrationError("expected catalog row was not created")
    return int(row[0])


def _id_type(connection: sqlite3.Connection, key: str) -> int:
    connection.execute(
        "INSERT OR IGNORE INTO identifier_types (type_key, name) VALUES (?, ?)",
        (key, key.replace("_", " ").title()),
    )
    return _one_id(connection, "SELECT id FROM identifier_types WHERE type_key = ?", (key,))


def _entity(
    connection: sqlite3.Connection,
    *,
    kind: str,
    id_key: str,
    id_value: str,
    provenance_id: int,
) -> tuple[int, bool]:
    type_id = _id_type(connection, id_key)
    row = connection.execute(
        """SELECT entity_id FROM entity_identifiers
           WHERE identifier_type_id = ? AND namespace = 'musicbrainz' AND normalized_value = ?""",
        (type_id, id_value),
    ).fetchone()
    created = row is None
    if row is None:
        cursor = connection.execute(
            "INSERT INTO catalog_entities (entity_kind) VALUES (?)", (kind,)
        )
        if cursor.lastrowid is None:
            raise MusicBrainzHydrationError("catalog entity has no generated ID")
        entity_id = cursor.lastrowid
    else:
        entity_id = int(row[0])
    connection.execute(
        """INSERT OR IGNORE INTO entity_identifiers
           (entity_id, identifier_type_id, namespace, value, normalized_value, provenance_id)
           VALUES (?, ?, 'musicbrainz', ?, ?, ?)""",
        (entity_id, type_id, id_value, id_value, provenance_id),
    )
    connection.execute(
        """INSERT OR IGNORE INTO entity_provenance
           (entity_id, provenance_id, field_set_json, is_primary)
           VALUES (?, ?, '["core_metadata"]', 0)""",
        (entity_id, provenance_id),
    )
    return entity_id, created


def _name(connection: sqlite3.Connection, entity_id: int, value: str, provenance_id: int) -> None:
    fingerprint = _sha256(f"{entity_id}\0primary\0{value}".encode())
    connection.execute(
        """INSERT OR IGNORE INTO entity_names
           (entity_id, name_kind, name, language_tag, is_preferred, provenance_id, fingerprint)
           VALUES (?, 'primary', ?, 'und', 1, ?, ?)""",
        (entity_id, value, provenance_id, fingerprint),
    )


def _provenance(connection: sqlite3.Connection, artifact_sha256: str) -> int:
    now = "1970-01-01T00:00:00.000Z"
    key = "musicbrainz-core-metadata-hydration"
    connection.execute(
        """INSERT OR IGNORE INTO rights_policies
           (policy_key, policy_version, classification, local_only, basis, reviewed_at)
           VALUES (?, 1, 'public_domain', 0, 'MusicBrainz core metadata CC0; no tags or media', ?)""",
        (key, now),
    )
    policy_id = _one_id(
        connection,
        "SELECT id FROM rights_policies WHERE policy_key = ? AND policy_version = 1",
        (key,),
    )
    sealed = connection.execute(
        "SELECT 1 FROM rights_policy_seals WHERE policy_id = ?", (policy_id,)
    ).fetchone()
    if sealed is None:
        for use in ("normalize", "local_search", "display", "embed", "train", "export"):
            connection.execute(
                "INSERT INTO rights_policy_permissions (policy_id, use_kind, decision, reason) VALUES (?, ?, 'allow', 'core metadata only')",
                (policy_id, use),
            )
        connection.execute(
            "INSERT INTO rights_policy_seals (policy_id, sealed_at) VALUES (?, ?)", (policy_id, now)
        )
    source_key = "musicbrainz_public_core_release_hydration"
    connection.execute(
        """INSERT OR IGNORE INTO data_sources
           (source_key, name, homepage_url, license_name, license_url, acquisition_kind, default_policy_id)
           VALUES (?, 'MusicBrainz core release hydration', 'https://musicbrainz.org/', 'CC0',
                   'https://musicbrainz.org/doc/About/Data_License', 'public_api', ?)""",
        (source_key, policy_id),
    )
    source_id = _one_id(
        connection, "SELECT id FROM data_sources WHERE source_key = ?", (source_key,)
    )
    fingerprint = _sha256(f"{HYDRATION_REVISION}\0{artifact_sha256}".encode())
    snapshot = f"hydration:{artifact_sha256}"
    connection.execute(
        """INSERT OR IGNORE INTO provenance_records
           (source_id, policy_id, snapshot_ref, artifact_sha256, record_fingerprint,
            parser_release_ref, ingest_attempt_ref, observed_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            source_id,
            policy_id,
            snapshot,
            artifact_sha256,
            fingerprint,
            HYDRATION_REVISION,
            snapshot,
            now,
        ),
    )
    return _one_id(
        connection,
        "SELECT id FROM provenance_records WHERE source_id = ? AND snapshot_ref = ? AND record_fingerprint = ? AND parser_release_ref = ?",
        (source_id, snapshot, fingerprint, HYDRATION_REVISION),
    )


def materialize_hydration_catalog(
    artifact: MusicBrainzReleaseHydrationArtifact, *, database_path: Path, artifact_sha256: str
) -> CatalogHydrationResult:
    """Transactionally write releases, media, tracks, and recordings to the existing SQLite schema."""
    database = Database(database_path)
    database.initialize()
    counts = [0, 0, 0, 0]
    with database.connect() as connection:
        provenance_id = _provenance(connection, artifact_sha256)
        for release in artifact.releases:
            group_id, _ = _entity(
                connection,
                kind="release_group",
                id_key="musicbrainz_release_group_id",
                id_value=str(release.release_group_id),
                provenance_id=provenance_id,
            )
            connection.execute("INSERT OR IGNORE INTO release_groups (id) VALUES (?)", (group_id,))
            _name(connection, group_id, release.release_group_title, provenance_id)
            release_id, created = _entity(
                connection,
                kind="release",
                id_key="musicbrainz_release_id",
                id_value=str(release.release_id),
                provenance_id=provenance_id,
            )
            connection.execute(
                "INSERT OR IGNORE INTO releases (id, release_group_id, status, packaging) VALUES (?, ?, ?, ?)",
                (release_id, group_id, release.status, release.packaging),
            )
            _name(connection, release_id, release.title, provenance_id)
            counts[0] += int(created)
            for medium in release.media:
                medium_id, created = _entity(
                    connection,
                    kind="medium",
                    id_key="musicbrainz_release_medium_position",
                    id_value=f"{release.release_id}:{medium.position}",
                    provenance_id=provenance_id,
                )
                connection.execute(
                    "INSERT OR IGNORE INTO media (id, release_id, position, format, track_count) VALUES (?, ?, ?, ?, ?)",
                    (medium_id, release_id, medium.position, medium.format, medium.track_count),
                )
                counts[1] += int(created)
                for track in medium.tracks:
                    recording_id, created = _entity(
                        connection,
                        kind="recording",
                        id_key="musicbrainz_recording_id",
                        id_value=str(track.recording_id),
                        provenance_id=provenance_id,
                    )
                    connection.execute(
                        "INSERT OR IGNORE INTO recordings (id, duration_ms) VALUES (?, ?)",
                        (recording_id, track.recording_duration_ms),
                    )
                    _name(connection, recording_id, track.title, provenance_id)
                    counts[3] += int(created)
                    track_id, created = _entity(
                        connection,
                        kind="track",
                        id_key="musicbrainz_track_id",
                        id_value=str(track.track_id),
                        provenance_id=provenance_id,
                    )
                    connection.execute(
                        "INSERT OR IGNORE INTO tracks (id, medium_id, recording_id, position, number_text, duration_ms) VALUES (?, ?, ?, ?, ?, ?)",
                        (
                            track_id,
                            medium_id,
                            recording_id,
                            track.position,
                            track.number,
                            track.duration_ms,
                        ),
                    )
                    _name(connection, track_id, track.title, provenance_id)
                    counts[2] += int(created)
        connection.commit()
    return CatalogHydrationResult(
        releases=counts[0], media=counts[1], tracks=counts[2], recordings=counts[3]
    )
