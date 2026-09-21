"""Read exact MusicBrainz artist credits only from retained hydration cache entries."""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, Literal
from uuid import UUID  # noqa: TC003 -- Pydantic resolves UUID field annotations.

from pydantic import BaseModel, ConfigDict, Field

from opennoise.ingest.musicbrainz.release_hydration import (
    CachedFailure,
    CachedResponse,
    MusicBrainzHydrationError,
    MusicBrainzReleaseHydrationArtifact,
)

if TYPE_CHECKING:
    from pathlib import Path

ARTIST_CREDIT_ENRICHMENT_REVISION = "musicbrainz-cached-artist-credit-enrichment-v1"


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
    response_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    members: tuple[ArtistCreditMember, ...]


class ArtistCreditAbstention(_FrozenModel):
    """A transparent reason no artist relation was materialized."""

    entity_kind: Literal["release", "recording"]
    entity_id: UUID
    reason: Literal["cache_response_missing", "artist_credit_field_not_retained"]


class CachedArtistCreditEnrichmentArtifact(_FrozenModel):
    """Versioned cache-only artist-credit candidate, never an inferred identity bridge."""

    revision: Literal["musicbrainz-cached-artist-credit-enrichment-v1"] = (
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


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


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
                    response_sha256=cached.response_sha256,
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
                response_sha256=cached.response_sha256,
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
