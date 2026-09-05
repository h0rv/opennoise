"""Expand release and track metadata from CC0 artist-backed public evidence.

The certified catalog has public Wikidata release-group P136 observations and
direct Wikidata artist-to-genre observations, but intentionally no concrete
release or track rows.  This module joins those two retained public inputs only
after MusicBrainz returns a release group's artist credits.  It never reads
MusicBrainz genres or tags, and it stores only core release/track metadata.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import sqlite3
import time
from collections import defaultdict
from pathlib import Path  # noqa: TC003 -- Pydantic resolves this annotation at runtime.
from typing import Literal, TypeVar
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from musix.musicbrainz_release_hydration import (
    CatalogHydrationResult,
    HydratedMedium,
    HydratedRelease,
    HydratedTrack,
    HydrationEvidence,
    MusicBrainzMedium,
    MusicBrainzReleaseHydrationArtifact,
    MusicBrainzReleaseMetadata,
    materialize_hydration_catalog,
)
from musix.policy import require_metadata_file
from musix.storage import ObjectKey, ObjectStore, ObjectWrite

MUSICBRAINZ_API_BASE = "https://musicbrainz.org/ws/2"
MUSICBRAINZ_MIN_REQUEST_INTERVAL_SECONDS = 1.0
EXPANSION_REVISION = "artist-backed-release-expansion-v1"
MAX_ARTIFACT_BYTES = 16 * 1024 * 1024
TRANSIENT_STATUS_CODES = frozenset({429, 500, 502, 503, 504})
ModelT = TypeVar("ModelT", bound=BaseModel)


class ArtistBackedReleaseExpansionError(RuntimeError):
    """Report a rejected public-metadata-only expansion."""


class _StrictModel(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")


class _ApiModel(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True, extra="ignore")


class ExpansionSettings(_StrictModel):
    """Bound one sequential, replayable MusicBrainz core-metadata expansion."""

    max_genres: int = Field(default=48, gt=20, le=96)
    max_seeds_per_genre: int = Field(default=2, gt=0, le=2)
    max_releases_per_seed: int = Field(default=1, gt=0, le=2)
    max_attempts: int = Field(default=3, gt=0, le=5)
    cache_directory: Path
    offline: bool = False


class DirectArtistGenreAnchor(_StrictModel):
    """One exportable CC0 direct artist-to-genre observation from the source cache."""

    genre_ref: str = Field(pattern=r"^wikidata:genre:Q[1-9][0-9]*$")
    artist_mbid: UUID
    evidence_id: int = Field(gt=0)
    provenance_id: int = Field(gt=0)
    policy_id: int = Field(gt=0)
    source_key: str = Field(pattern=r"^wikidata_phase3_artists_[0-9]{2}$")


class ReleaseGroupSeed(_StrictModel):
    """One CC0 P136 release-group seed; it does not itself assert a representative."""

    genre_ref: str = Field(pattern=r"^wikidata:genre:Q[1-9][0-9]*$")
    release_group_mbid: UUID
    album_evidence_id: int = Field(gt=0)
    provenance_id: int = Field(gt=0)
    policy_id: int = Field(gt=0)
    source_key: str = Field(pattern=r"^wikidata_phase3_release_group_(discovery|details)_[0-9]{2}$")


class ArtistBackedReleaseExpansionPlan(_StrictModel):
    """A sealed public-input plan before any MusicBrainz core metadata is fetched."""

    revision: Literal["artist-backed-release-expansion-plan-v1"] = (
        "artist-backed-release-expansion-plan-v1"
    )
    source_database_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    settings: ExpansionSettings
    anchors: tuple[DirectArtistGenreAnchor, ...] = Field(min_length=1)
    seeds: tuple[ReleaseGroupSeed, ...] = Field(min_length=1)
    content_policy: Literal["cc0_wikidata_evidence_plus_musicbrainz_core_metadata_only"] = (
        "cc0_wikidata_evidence_plus_musicbrainz_core_metadata_only"
    )

    @model_validator(mode="after")
    def require_unique_connected_public_inputs(self) -> ArtistBackedReleaseExpansionPlan:
        """Prevent duplicate rows or a seed with no permitted direct-artist anchor."""
        anchor_keys = {(anchor.genre_ref, anchor.artist_mbid) for anchor in self.anchors}
        if len(anchor_keys) != len(self.anchors):
            raise ValueError(
                "direct artist anchors must be unique per genre and MusicBrainz artist"
            )
        seed_keys = {(seed.genre_ref, seed.release_group_mbid) for seed in self.seeds}
        if len(seed_keys) != len(self.seeds):
            raise ValueError("release group seeds must be unique per genre")
        anchor_genres = {anchor.genre_ref for anchor in self.anchors}
        if any(seed.genre_ref not in anchor_genres for seed in self.seeds):
            raise ValueError("every release-group seed requires retained direct artist evidence")
        return self


class _CachedResponse(_StrictModel):
    """A parsed core-metadata projection, never a raw HTTP response."""

    endpoint: str = Field(min_length=1)
    projection_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    payload: dict[str, object]


class _ReleaseReference(_ApiModel):
    id: UUID
    title: str = Field(min_length=1)
    date: str | None = None
    country: str | None = None


class _CreditArtist(_ApiModel):
    id: UUID
    name: str = Field(min_length=1)


class _ArtistCredit(_ApiModel):
    artist: _CreditArtist


class _ReleaseGroupMetadata(_ApiModel):
    id: UUID
    title: str = Field(min_length=1)
    releases: tuple[_ReleaseReference, ...] = Field(default=(), max_length=100)
    artist_credit: tuple[_ArtistCredit, ...] = Field(
        default=(), alias="artist-credit", max_length=64
    )


class ExpandedReleaseEvidence(_StrictModel):
    """Bind each retained release to both original CC0 evidence and API responses."""

    genre_ref: str = Field(pattern=r"^wikidata:genre:Q[1-9][0-9]*$")
    release_group_mbid: UUID
    album_evidence_id: int = Field(gt=0)
    direct_artist_evidence_id: int = Field(gt=0)
    matching_artist_mbid: UUID
    release_group_endpoint: str = Field(min_length=1)
    release_group_projection_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    release_endpoint: str = Field(min_length=1)
    release_projection_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class ExpandedRelease(_StrictModel):
    """One concrete MusicBrainz release and non-playable ordered track metadata."""

    release_id: UUID
    release_group_id: UUID
    title: str = Field(min_length=1)
    release_group_title: str = Field(min_length=1)
    status: str | None = None
    packaging: str | None = None
    country: str | None = None
    date: str | None = None
    media: tuple[HydratedMedium, ...]
    evidence: ExpandedReleaseEvidence


type SeedAbstentionReason = Literal[
    "no_matching_direct_artist_credit",
    "no_concrete_release",
    "musicbrainz_metadata_unavailable",
]


class ExpansionSeedResult(_StrictModel):
    """One explicit outcome for every planned public release-group seed."""

    seed: ReleaseGroupSeed
    releases: tuple[ExpandedRelease, ...] = Field(default=(), max_length=2)
    abstention_reason: SeedAbstentionReason | None = None
    abstention_message: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def require_releases_or_abstention(self) -> ExpansionSeedResult:
        """Do not hide unavailable metadata as an empty successful result."""
        if bool(self.releases) == (self.abstention_reason is not None):
            raise ValueError("each expansion seed needs releases or one explicit abstention")
        if self.abstention_reason is None and self.abstention_message is not None:
            raise ValueError("successful expansion seeds cannot carry an abstention message")
        if self.abstention_reason is not None and not self.abstention_message:
            raise ValueError("abstentions require a non-empty explanation")
        return self


class ExpansionCoverage(_StrictModel):
    """Bounded coverage and abstentions without a quality or popularity claim."""

    selected_genre_count: int = Field(ge=0)
    selected_seed_count: int = Field(ge=0)
    hydrated_seed_count: int = Field(ge=0)
    abstained_seed_count: int = Field(ge=0)
    unique_release_count: int = Field(ge=0)
    medium_count: int = Field(ge=0)
    track_count: int = Field(ge=0)
    no_matching_direct_artist_credit_count: int = Field(ge=0)
    no_concrete_release_count: int = Field(ge=0)
    metadata_unavailable_count: int = Field(ge=0)

    @model_validator(mode="after")
    def require_complete_seed_partition(self) -> ExpansionCoverage:
        """Make coverage denominators and all abstentions auditable."""
        if self.selected_seed_count != self.hydrated_seed_count + self.abstained_seed_count:
            raise ValueError("expanded and abstained seeds must partition selected seeds")
        if self.abstained_seed_count != (
            self.no_matching_direct_artist_credit_count
            + self.no_concrete_release_count
            + self.metadata_unavailable_count
        ):
            raise ValueError("abstention reasons must partition abstained seeds")
        return self


class ArtistBackedReleaseExpansionArtifact(_StrictModel):
    """Portable public core-metadata release and track expansion."""

    revision: Literal["artist-backed-release-expansion-v1"] = EXPANSION_REVISION
    plan_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    results: tuple[ExpansionSeedResult, ...]
    coverage: ExpansionCoverage
    content_policy: Literal[
        "musicbrainz_core_metadata_only_no_audio_preview_artwork_urls_or_tags"
    ] = "musicbrainz_core_metadata_only_no_audio_preview_artwork_urls_or_tags"
    track_semantics: Literal["track_metadata_not_playable_media"] = (
        "track_metadata_not_playable_media"
    )


class ArtistBackedReleaseExpansionPublication(_StrictModel):
    """Object-store custody receipt for one exact expansion artifact."""

    artifact: ObjectWrite
    coverage: ExpansionCoverage


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_bytes(value: BaseModel) -> bytes:
    return value.model_dump_json(exclude_none=True, by_alias=True).encode("utf-8")


def _semantic_plan_sha256(plan: ArtistBackedReleaseExpansionPlan) -> str:
    """Hash source and acquisition bounds, excluding local cache/replay controls."""
    payload = plan.model_dump(mode="json", by_alias=True, exclude_none=True)
    settings = payload["settings"]
    if not isinstance(settings, dict):
        raise TypeError("expansion plan settings did not serialize as an object")
    for operational_field in ("cache_directory", "offline", "max_attempts"):
        settings.pop(operational_field, None)
    return _sha256_bytes(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8"))


def _endpoint_cache_name(endpoint: str) -> str:
    return f"{_sha256_bytes(endpoint.encode())}.json"


def build_expansion_plan(
    database: Path,
    settings: ExpansionSettings,
) -> ArtistBackedReleaseExpansionPlan:
    """Select CC0 Wikidata release groups and direct artist anchors from one sealed DB."""
    absolute = database.resolve(strict=True)
    source_hash = _sha256_path(absolute)
    uri = f"file:{absolute.as_posix()}?mode=ro"
    with sqlite3.connect(uri, uri=True) as connection:
        group_rows = connection.execute(
            """
            SELECT 'wikidata:genre:' || genre_identifier.normalized_value,
                   group_identifier.normalized_value, album.id, album.provenance_id,
                   album.policy_id, source.source_key
            FROM album_genre_membership_observations AS album
            JOIN entity_identifiers AS genre_identifier
              ON genre_identifier.entity_id = album.genre_id
            JOIN identifier_types AS genre_identifier_type
              ON genre_identifier_type.id = genre_identifier.identifier_type_id
             AND genre_identifier_type.type_key = 'wikidata_genre_qid'
            JOIN entity_identifiers AS group_identifier
              ON group_identifier.entity_id = album.release_group_id
            JOIN identifier_types AS group_identifier_type
              ON group_identifier_type.id = group_identifier.identifier_type_id
             AND group_identifier_type.type_key = 'musicbrainz_release_group_id'
            JOIN provenance_records AS provenance ON provenance.id = album.provenance_id
            JOIN data_sources AS source ON source.id = provenance.source_id
            JOIN rights_policies AS policy ON policy.id = album.policy_id
            JOIN rights_policy_permissions AS permission
              ON permission.policy_id = policy.id
             AND permission.use_kind = 'export' AND permission.decision = 'allow'
            WHERE album.evidence_kind = 'wikidata_p136'
              AND album.source_family = 'wikidata'
              AND source.source_key GLOB 'wikidata_phase3_release_group_*'
              AND policy.classification = 'public_domain' AND policy.local_only = 0
            ORDER BY 1, 2, album.id
            """
        ).fetchall()
        anchor_rows = connection.execute(
            """
            SELECT 'wikidata:genre:' || genre_identifier.normalized_value,
                   artist_identifier.normalized_value, evidence.id, evidence.provenance_id,
                   evidence.policy_id, source.source_key
            FROM artist_genre_evidence AS evidence
            JOIN entity_identifiers AS genre_identifier
              ON genre_identifier.entity_id = evidence.genre_id
            JOIN identifier_types AS genre_identifier_type
              ON genre_identifier_type.id = genre_identifier.identifier_type_id
             AND genre_identifier_type.type_key = 'wikidata_genre_qid'
            JOIN entity_identifiers AS artist_identifier
              ON artist_identifier.entity_id = evidence.artist_id
            JOIN identifier_types AS artist_identifier_type
              ON artist_identifier_type.id = artist_identifier.identifier_type_id
             AND artist_identifier_type.type_key = 'musicbrainz_artist_id'
            JOIN provenance_records AS provenance ON provenance.id = evidence.provenance_id
            JOIN data_sources AS source ON source.id = provenance.source_id
            JOIN rights_policies AS policy ON policy.id = evidence.policy_id
            JOIN rights_policy_permissions AS permission
              ON permission.policy_id = policy.id
             AND permission.use_kind = 'export' AND permission.decision = 'allow'
            WHERE evidence.evidence_kind = 'direct_source_claim'
              AND source.source_key GLOB 'wikidata_phase3_artists_[0-9][0-9]'
              AND policy.classification = 'public_domain' AND policy.local_only = 0
            ORDER BY 1, 2, evidence.id
            """
        ).fetchall()
    anchors_by_genre: dict[str, list[DirectArtistGenreAnchor]] = defaultdict(list)
    seen_anchors: set[tuple[str, UUID]] = set()
    for row in anchor_rows:
        anchor = DirectArtistGenreAnchor(
            genre_ref=str(row[0]),
            artist_mbid=UUID(str(row[1])),
            evidence_id=int(row[2]),
            provenance_id=int(row[3]),
            policy_id=int(row[4]),
            source_key=str(row[5]),
        )
        key = (anchor.genre_ref, anchor.artist_mbid)
        if key not in seen_anchors:
            anchors_by_genre[anchor.genre_ref].append(anchor)
            seen_anchors.add(key)
    groups_by_genre: dict[str, list[ReleaseGroupSeed]] = defaultdict(list)
    seen_groups: set[tuple[str, UUID]] = set()
    for row in group_rows:
        seed = ReleaseGroupSeed(
            genre_ref=str(row[0]),
            release_group_mbid=UUID(str(row[1])),
            album_evidence_id=int(row[2]),
            provenance_id=int(row[3]),
            policy_id=int(row[4]),
            source_key=str(row[5]),
        )
        key = (seed.genre_ref, seed.release_group_mbid)
        if key not in seen_groups:
            groups_by_genre[seed.genre_ref].append(seed)
            seen_groups.add(key)
    eligible_genres = sorted(
        (genre for genre in groups_by_genre if anchors_by_genre.get(genre)),
        key=lambda genre: (-len(groups_by_genre[genre]), genre),
    )[: settings.max_genres]
    seeds = tuple(
        seed
        for genre in eligible_genres
        for seed in groups_by_genre[genre][: settings.max_seeds_per_genre]
    )
    anchors = tuple(anchor for genre in eligible_genres for anchor in anchors_by_genre[genre])
    if not seeds:
        raise ArtistBackedReleaseExpansionError("no exportable artist-backed release-group seeds")
    return ArtistBackedReleaseExpansionPlan(
        source_database_sha256=source_hash,
        settings=settings,
        anchors=anchors,
        seeds=seeds,
    )


class ArtistBackedReleaseExpansionAdapter:
    """Fetch cached/rate-limited MusicBrainz core metadata for one sealed plan."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        settings: ExpansionSettings,
        *,
        user_agent: str,
    ) -> None:
        """Keep one caller-owned async client and an explicit cache/rate boundary."""
        if not user_agent.strip() or "/" not in user_agent or "(" not in user_agent:
            raise ValueError("MusicBrainz user_agent must include an app version and contact")
        self._client = client
        self._settings = settings
        self._user_agent = user_agent
        self._next_request_at = 0.0
        self._rate_lock = asyncio.Lock()
        self._upstream_request_count = 0

    @property
    def upstream_request_count(self) -> int:
        """Return requests that reached MusicBrainz instead of this adapter's safe cache."""
        return self._upstream_request_count

    async def _wait_for_rate_limit(self) -> None:
        async with self._rate_lock:
            now = time.monotonic()
            delay = self._next_request_at - now
            if delay > 0:
                await asyncio.sleep(delay)
            self._next_request_at = time.monotonic() + MUSICBRAINZ_MIN_REQUEST_INTERVAL_SECONDS

    def _cache_path(self, endpoint: str) -> Path:
        return self._settings.cache_directory / _endpoint_cache_name(endpoint)

    async def _fetch(  # noqa: C901
        self, endpoint: str, model: type[ModelT], inclusion: str
    ) -> tuple[ModelT, str]:
        path = self._cache_path(endpoint)
        if path.is_file():
            try:
                cached = _CachedResponse.model_validate_json(path.read_bytes())
            except (OSError, ValidationError, ValueError) as error:
                raise ArtistBackedReleaseExpansionError(
                    f"invalid expansion cache entry: {path}"
                ) from error
            if cached.endpoint != endpoint:
                raise ArtistBackedReleaseExpansionError("expansion cache endpoint mismatch")
            parsed = model.model_validate_json(json.dumps(cached.payload, separators=(",", ":")))
            if cached.projection_sha256 != _sha256_bytes(_canonical_bytes(parsed)):
                raise ArtistBackedReleaseExpansionError(
                    "expansion cache projection hash does not match its parsed payload"
                )
            return parsed, cached.projection_sha256
        if self._settings.offline:
            raise ArtistBackedReleaseExpansionError(f"offline replay cache miss: {endpoint}")
        for attempt in range(self._settings.max_attempts):
            await self._wait_for_rate_limit()
            self._upstream_request_count += 1
            try:
                response = await self._client.get(
                    f"{MUSICBRAINZ_API_BASE}/{endpoint}",
                    params={"fmt": "json", "inc": inclusion},
                    headers={"User-Agent": self._user_agent, "Accept": "application/json"},
                )
            except httpx.HTTPError as error:
                if attempt + 1 == self._settings.max_attempts:
                    raise ArtistBackedReleaseExpansionError(
                        f"MusicBrainz request failed: {endpoint}"
                    ) from error
                await asyncio.sleep(float(2**attempt))
                continue
            if (
                response.status_code in TRANSIENT_STATUS_CODES
                and attempt + 1 < self._settings.max_attempts
            ):
                await asyncio.sleep(float(2**attempt))
                continue
            try:
                response.raise_for_status()
                parsed = model.model_validate_json(response.content)
            except (httpx.HTTPStatusError, ValidationError, ValueError) as error:
                raise ArtistBackedReleaseExpansionError(
                    f"invalid MusicBrainz metadata response: {endpoint}"
                ) from error
            self._settings.cache_directory.mkdir(parents=True, exist_ok=True)
            cached = _CachedResponse(
                endpoint=endpoint,
                projection_sha256=_sha256_bytes(_canonical_bytes(parsed)),
                payload=parsed.model_dump(mode="json", by_alias=True, exclude_none=True),
            )
            temporary = path.with_suffix(".tmp")
            temporary.write_bytes(_canonical_bytes(cached))
            temporary.replace(path)
            return parsed, cached.projection_sha256
        raise AssertionError("bounded retry loop exhausted")

    async def hydrate(
        self, plan: ArtistBackedReleaseExpansionPlan
    ) -> ArtistBackedReleaseExpansionArtifact:
        """Hydrate every seed and keep a direct-artist join or explicit abstention."""
        allowed: dict[str, dict[UUID, DirectArtistGenreAnchor]] = defaultdict(dict)
        for anchor in plan.anchors:
            allowed[anchor.genre_ref][anchor.artist_mbid] = anchor
        results: list[ExpansionSeedResult] = []
        for seed in plan.seeds:
            group_endpoint = f"release-group/{seed.release_group_mbid}"
            try:
                group, group_hash = await self._fetch(
                    group_endpoint, _ReleaseGroupMetadata, "releases+artist-credits"
                )
            except ArtistBackedReleaseExpansionError as error:
                results.append(
                    ExpansionSeedResult(
                        seed=seed,
                        abstention_reason="musicbrainz_metadata_unavailable",
                        abstention_message=str(error),
                    )
                )
                continue
            matching = tuple(
                credit.artist.id
                for credit in group.artist_credit
                if credit.artist.id in allowed[seed.genre_ref]
            )
            if not matching:
                results.append(
                    ExpansionSeedResult(
                        seed=seed,
                        abstention_reason="no_matching_direct_artist_credit",
                        abstention_message=(
                            "MusicBrainz release-group artist credits do not match retained direct "
                            "CC0 artist-to-genre evidence."
                        ),
                    )
                )
                continue
            references = sorted(
                group.releases,
                key=lambda release: (
                    release.date or "9999-99-99",
                    release.country or "",
                    str(release.id),
                ),
            )[: plan.settings.max_releases_per_seed]
            if not references:
                results.append(
                    ExpansionSeedResult(
                        seed=seed,
                        abstention_reason="no_concrete_release",
                        abstention_message=(
                            "MusicBrainz release group has no concrete release metadata."
                        ),
                    )
                )
                continue
            expanded: list[ExpandedRelease] = []
            metadata_error: str | None = None
            for reference in references:
                release_endpoint = f"release/{reference.id}"
                try:
                    release, release_projection_hash = await self._fetch(
                        release_endpoint, MusicBrainzReleaseMetadata, "release-groups+recordings"
                    )
                except ArtistBackedReleaseExpansionError as error:
                    metadata_error = str(error)
                    expanded = []
                    break
                matching_artist = matching[0]
                anchor = allowed[seed.genre_ref][matching_artist]
                expanded.append(
                    ExpandedRelease(
                        release_id=release.id,
                        release_group_id=release.release_group.id,
                        title=release.title,
                        release_group_title=release.release_group.title,
                        status=release.status,
                        packaging=release.packaging,
                        country=release.country,
                        date=release.date,
                        media=tuple(
                            _medium(medium)
                            for medium in sorted(release.media, key=lambda item: item.position)
                        ),
                        evidence=ExpandedReleaseEvidence(
                            genre_ref=seed.genre_ref,
                            release_group_mbid=seed.release_group_mbid,
                            album_evidence_id=seed.album_evidence_id,
                            direct_artist_evidence_id=anchor.evidence_id,
                            matching_artist_mbid=matching_artist,
                            release_group_endpoint=group_endpoint,
                            release_group_projection_sha256=group_hash,
                            release_endpoint=release_endpoint,
                            release_projection_sha256=release_projection_hash,
                        ),
                    )
                )
            if metadata_error is not None:
                results.append(
                    ExpansionSeedResult(
                        seed=seed,
                        abstention_reason="musicbrainz_metadata_unavailable",
                        abstention_message=metadata_error,
                    )
                )
            elif expanded:
                results.append(ExpansionSeedResult(seed=seed, releases=tuple(expanded)))
        ordered = tuple(
            sorted(
                results, key=lambda item: (item.seed.genre_ref, str(item.seed.release_group_mbid))
            )
        )
        hydrated = tuple(item for item in ordered if item.releases)
        all_releases = tuple(release for item in hydrated for release in item.releases)
        abstentions = tuple(item for item in ordered if item.abstention_reason is not None)
        coverage = ExpansionCoverage(
            selected_genre_count=len({seed.genre_ref for seed in plan.seeds}),
            selected_seed_count=len(plan.seeds),
            hydrated_seed_count=len(hydrated),
            abstained_seed_count=len(abstentions),
            unique_release_count=len({release.release_id for release in all_releases}),
            medium_count=sum(len(release.media) for release in all_releases),
            track_count=sum(
                len(medium.tracks) for release in all_releases for medium in release.media
            ),
            no_matching_direct_artist_credit_count=sum(
                item.abstention_reason == "no_matching_direct_artist_credit" for item in abstentions
            ),
            no_concrete_release_count=sum(
                item.abstention_reason == "no_concrete_release" for item in abstentions
            ),
            metadata_unavailable_count=sum(
                item.abstention_reason == "musicbrainz_metadata_unavailable" for item in abstentions
            ),
        )
        return ArtistBackedReleaseExpansionArtifact(
            plan_sha256=_semantic_plan_sha256(plan), results=ordered, coverage=coverage
        )


def _medium(medium: MusicBrainzMedium) -> HydratedMedium:
    """Convert one parsed API medium into safe non-playable ordered track metadata."""
    return HydratedMedium(
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
            for track in sorted(medium.tracks, key=lambda item: item.position)
        ),
    )


def write_expansion_artifact(
    artifact: ArtistBackedReleaseExpansionArtifact, *, output: Path, store: ObjectStore
) -> ArtistBackedReleaseExpansionPublication:
    """Write canonical bytes then prove immutable ObjectStore custody."""
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = _canonical_bytes(artifact) + b"\n"
    if len(payload) > MAX_ARTIFACT_BYTES:
        raise ArtistBackedReleaseExpansionError("artist-backed expansion exceeds 16 MiB")
    output.write_bytes(payload)
    require_metadata_file(output)
    digest = _sha256_bytes(payload)
    stored = store.push(
        output, ObjectKey(value=f"artist-backed-release-expansions/sha256/{digest}.json")
    )
    if (stored.sha256, stored.byte_size) != (digest, len(payload)):
        raise ArtistBackedReleaseExpansionError(
            "object store changed artist-backed expansion bytes"
        )
    return ArtistBackedReleaseExpansionPublication(artifact=stored, coverage=artifact.coverage)


def materialize_expansion_catalog(
    artifact: ArtistBackedReleaseExpansionArtifact,
    *,
    database_path: Path,
    artifact_sha256: str,
) -> CatalogHydrationResult:
    """Materialize into a copied serving DB while preserving source-evidence joins.

    The certified source database is never opened for writing.  Before reusing
    the existing hydration materializer, every retained release is checked
    against its original album and direct-artist observation IDs in the copied
    database.  This makes a missing or mismatched source link fail closed.
    """
    database = database_path.resolve(strict=True)
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        for result in artifact.results:
            for release in result.releases:
                evidence = release.evidence
                album_match = connection.execute(
                    """
                    SELECT 1
                    FROM album_genre_membership_observations AS album
                    JOIN entity_identifiers AS genre_identifier
                      ON genre_identifier.entity_id = album.genre_id
                    JOIN identifier_types AS genre_identifier_type
                      ON genre_identifier_type.id = genre_identifier.identifier_type_id
                     AND genre_identifier_type.type_key = 'wikidata_genre_qid'
                    JOIN entity_identifiers AS group_identifier
                      ON group_identifier.entity_id = album.release_group_id
                    JOIN identifier_types AS group_identifier_type
                      ON group_identifier_type.id = group_identifier.identifier_type_id
                     AND group_identifier_type.type_key = 'musicbrainz_release_group_id'
                    WHERE album.id = ?
                      AND album.evidence_kind = 'wikidata_p136'
                      AND genre_identifier.normalized_value = ?
                      AND group_identifier.normalized_value = ?
                    """,
                    (
                        evidence.album_evidence_id,
                        evidence.genre_ref.removeprefix("wikidata:genre:"),
                        str(release.release_group_id),
                    ),
                ).fetchone()
                if album_match is None:
                    raise ArtistBackedReleaseExpansionError(
                        "expanded release is not linked to its retained album evidence"
                    )
                artist_match = connection.execute(
                    """
                    SELECT 1
                    FROM artist_genre_evidence AS direct
                    JOIN entity_identifiers AS genre_identifier
                      ON genre_identifier.entity_id = direct.genre_id
                    JOIN identifier_types AS genre_identifier_type
                      ON genre_identifier_type.id = genre_identifier.identifier_type_id
                     AND genre_identifier_type.type_key = 'wikidata_genre_qid'
                    JOIN entity_identifiers AS artist_identifier
                      ON artist_identifier.entity_id = direct.artist_id
                    JOIN identifier_types AS artist_identifier_type
                      ON artist_identifier_type.id = artist_identifier.identifier_type_id
                     AND artist_identifier_type.type_key = 'musicbrainz_artist_id'
                    WHERE direct.id = ?
                      AND direct.evidence_kind = 'direct_source_claim'
                      AND genre_identifier.normalized_value = ?
                      AND artist_identifier.normalized_value = ?
                    """,
                    (
                        evidence.direct_artist_evidence_id,
                        evidence.genre_ref.removeprefix("wikidata:genre:"),
                        str(evidence.matching_artist_mbid),
                    ),
                ).fetchone()
                if artist_match is None:
                    raise ArtistBackedReleaseExpansionError(
                        "expanded release is not linked to its retained artist evidence"
                    )
    releases = tuple(
        HydratedRelease(
            release_id=release.release_id,
            release_group_id=release.release_group_id,
            title=release.title,
            release_group_title=release.release_group_title,
            status=release.status,
            packaging=release.packaging,
            country=release.country,
            date=release.date,
            media=release.media,
            evidence=(
                HydrationEvidence(
                    representative_kind="release_group",
                    representative_id=(
                        f"musicbrainz:release-group:{release.evidence.release_group_mbid}"
                    ),
                    representative_rank=1,
                    endpoint=release.evidence.release_endpoint,
                    response_sha256=release.evidence.release_projection_sha256,
                ),
            ),
        )
        for result in artifact.results
        for release in result.releases
    )
    hydration_artifact = MusicBrainzReleaseHydrationArtifact(
        selection_sha256=artifact.plan_sha256,
        source_representative_artifact_sha256=artifact.plan_sha256,
        releases=releases,
    )
    return materialize_hydration_catalog(
        hydration_artifact, database_path=database, artifact_sha256=artifact_sha256
    )
