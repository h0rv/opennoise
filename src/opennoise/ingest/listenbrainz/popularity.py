"""Bounded local-only ListenBrainz popularity rankings.

The API counts describe ListenBrainz listeners. This module retains exact
MusicBrainz IDs and count/rank fields only; it never interprets titles or tags.
"""

from __future__ import annotations

import base64
import hashlib
import json
from collections.abc import Iterable  # noqa: TC003
from datetime import UTC, datetime
from io import BytesIO
from typing import Literal, overload
from uuid import UUID

import httpx
import ijson
from pydantic import (
    Base64Bytes,
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    TypeAdapter,
    ValidationError,
)

from opennoise.evidence.musicbrainz_album_review import (
    MusicBrainzAlbumReviewPacket,
    review_source_sha256,
)
from opennoise.types import Sha256  # noqa: TC001

_ORIGIN = "https://api.listenbrainz.org"
_MAX_ARTISTS = 20
_MAX_RESULTS = 10
_CHUNK_SIZE = 64 * 1024


class ListenBrainzPopularityError(ValueError):
    """An unsafe, malformed, or out-of-scope popularity response was rejected."""


class _Boundary(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")


class PopularityFetchSettings(_Boundary):
    """Bound request size and identify this research client to ListenBrainz."""

    timeout_seconds: float = Field(default=10.0, gt=0.0, le=30.0)
    maximum_response_bytes: int = Field(default=2 * 1024 * 1024, ge=1, le=8 * 1024 * 1024)
    user_agent: str = Field(
        default="opennoise/0.1 (https://github.com/h0rv/opennoise)",
        min_length=1,
        max_length=200,
    )


class PopularityReceipt(_Boundary):
    """Bind response bytes to the exact artist ranking endpoint and retrieval time."""

    source_url: HttpUrl
    fetched_at: datetime
    payload_sha256: Sha256
    payload_bytes: int = Field(ge=1)
    ranking_kind: Literal["recording", "release_group"]
    artist_mbid: UUID
    local_only: Literal[True] = True
    export_allowed: Literal[False] = False
    serving_allowed: Literal[False] = False

    def matches_request(self) -> bool:
        """Check the canonical artist ranking endpoint."""
        path_kind = "recordings" if self.ranking_kind == "recording" else "release-groups"
        return str(self.source_url) == (
            f"{_ORIGIN}/1/popularity/top-{path_kind}-for-artist/{self.artist_mbid}"
        )


class RecordingPopularity(_Boundary):
    """Exact recording ID and its ListenBrainz listener popularity counts."""

    model_config = ConfigDict(frozen=True, strict=True, extra="ignore")

    recording_mbid: UUID
    total_listen_count: int = Field(ge=0)
    total_user_count: int = Field(ge=0)


class ReleaseGroupPopularity(_Boundary):
    """Exact release-group ID and its ListenBrainz listener popularity counts."""

    model_config = ConfigDict(frozen=True, strict=True, extra="ignore")

    release_group_mbid: UUID
    total_listen_count: int = Field(ge=0)
    total_user_count: int = Field(ge=0)


class RecordingRanking(_Boundary):
    """One artist's separate recording ranking with replayable response bytes."""

    receipt: PopularityReceipt
    artist_mbid: UUID
    results: tuple[RecordingPopularity, ...] = Field(max_length=_MAX_RESULTS)
    raw_payload: Base64Bytes


class ReleaseGroupRanking(_Boundary):
    """One artist's separate album ranking with replayable response bytes."""

    receipt: PopularityReceipt
    artist_mbid: UUID
    results: tuple[ReleaseGroupPopularity, ...] = Field(max_length=_MAX_RESULTS)
    raw_payload: Base64Bytes


class ArtistPopularity(_Boundary):
    """The two separate popularity ranking kinds for one artist MBID."""

    artist_mbid: UUID
    recording_ranking: RecordingRanking
    release_group_ranking: ReleaseGroupRanking


class PopularityProbeBundle(_Boundary):
    """Small local-only set of artist rankings with explicit non-serving flags."""

    revision: Literal["listenbrainz-popularity-probe-v1"] = "listenbrainz-popularity-probe-v1"
    artists: tuple[ArtistPopularity, ...] = Field(min_length=1, max_length=_MAX_ARTISTS)
    local_only: Literal[True] = True
    export_allowed: Literal[False] = False
    serving_allowed: Literal[False] = False
    genre_evidence_eligible: Literal[False] = False


class RankingCoverage(_Boundary):
    """Exact catalog overlap counts and positions for one ranking kind."""

    artist_mbid: UUID
    ranking_kind: Literal["recording", "release_group"]
    result_count: int = Field(ge=0, le=_MAX_RESULTS)
    exact_catalog_match_count: int = Field(ge=0, le=_MAX_RESULTS)
    unmatched_result_count: int = Field(ge=0, le=_MAX_RESULTS)
    matched_candidate_ranks: tuple[int, ...] = Field(max_length=_MAX_RESULTS)


class AlbumCandidateSeedOverlap(_Boundary):
    """Exact per-seed candidate overlap; this is not a genre judgment."""

    seed_name: str = Field(min_length=1)
    artist_mbid: UUID
    packet_candidate_count: int = Field(ge=0)
    matched_candidate_count: int = Field(ge=0)
    abstained_candidate_count: int = Field(ge=0)
    matched_candidate_ranks: tuple[int, ...] = Field(max_length=_MAX_RESULTS)


class PopularityProbeReport(_Boundary):
    """Local probe output and optional exact overlap against an album packet."""

    revision: Literal["listenbrainz-popularity-probe-report-v1"] = (
        "listenbrainz-popularity-probe-report-v1"
    )
    bundle: PopularityProbeBundle
    album_packet_sha256: Sha256 | None = None
    album_candidate_overlap: tuple[AlbumCandidateSeedOverlap, ...] = ()
    local_only: Literal[True] = True
    export_allowed: Literal[False] = False
    serving_allowed: Literal[False] = False
    model_input_allowed: Literal[False] = False
    genre_evidence_eligible: Literal[False] = False


@overload
def parse_ranking(
    payload: bytes,
    *,
    artist_mbid: UUID,
    ranking_kind: Literal["recording"],
    receipt: PopularityReceipt,
) -> RecordingRanking: ...


@overload
def parse_ranking(
    payload: bytes,
    *,
    artist_mbid: UUID,
    ranking_kind: Literal["release_group"],
    receipt: PopularityReceipt,
) -> ReleaseGroupRanking: ...


def parse_ranking(
    payload: bytes,
    *,
    artist_mbid: UUID,
    ranking_kind: Literal["recording", "release_group"],
    receipt: PopularityReceipt,
) -> RecordingRanking | ReleaseGroupRanking:
    """Parse a bounded API array and project only exact IDs and popularity counts."""
    if len(payload) != receipt.payload_bytes:
        raise ListenBrainzPopularityError("popularity response size does not match receipt")
    if hashlib.sha256(payload).hexdigest() != receipt.payload_sha256:
        raise ListenBrainzPopularityError("popularity response SHA-256 does not match receipt")
    if (
        receipt.artist_mbid != artist_mbid
        or receipt.ranking_kind != ranking_kind
        or not receipt.matches_request()
    ):
        raise ListenBrainzPopularityError(
            "popularity receipt does not match the requested endpoint"
        )
    try:
        if ranking_kind == "recording":
            rows = _first_ten_rows(payload, RecordingPopularity)
            return RecordingRanking(
                receipt=receipt,
                artist_mbid=artist_mbid,
                results=rows,
                raw_payload=base64.b64encode(payload),
            )
        rows = _first_ten_rows(payload, ReleaseGroupPopularity)
        return ReleaseGroupRanking(
            receipt=receipt,
            artist_mbid=artist_mbid,
            results=rows,
            raw_payload=base64.b64encode(payload),
        )
    except ValidationError as error:
        raise ListenBrainzPopularityError("popularity response failed its strict schema") from error


async def fetch_artist_popularity(
    artist_mbid: UUID,
    *,
    settings: PopularityFetchSettings | None = None,
    client: httpx.AsyncClient | None = None,
) -> ArtistPopularity:
    """Fetch the two documented top-ten routes sequentially for one exact artist ID."""
    resolved = settings or PopularityFetchSettings()
    owns_client = client is None
    http_client = client or httpx.AsyncClient(
        follow_redirects=False,
        timeout=httpx.Timeout(resolved.timeout_seconds),
        headers={"User-Agent": resolved.user_agent, "Accept": "application/json"},
    )
    try:
        recording = await _fetch_ranking(http_client, artist_mbid, "recording", resolved)
        release_group = await _fetch_ranking(http_client, artist_mbid, "release_group", resolved)
    finally:
        if owns_client:
            await http_client.aclose()
    return ArtistPopularity(
        artist_mbid=artist_mbid,
        recording_ranking=recording,
        release_group_ranking=release_group,
    )


async def fetch_popularity_probe(
    artist_mbids: Iterable[UUID],
    *,
    settings: PopularityFetchSettings | None = None,
    client: httpx.AsyncClient | None = None,
) -> PopularityProbeBundle:
    """Fetch at most 20 unique supplied artist IDs, one artist and endpoint at a time."""
    identifiers = tuple(artist_mbids)
    if (
        not identifiers
        or len(identifiers) > _MAX_ARTISTS
        or len(set(identifiers)) != len(identifiers)
    ):
        raise ListenBrainzPopularityError("probe requires 1 to 20 distinct artist MBIDs")
    artists: list[ArtistPopularity] = []
    owns_client = client is None
    resolved = settings or PopularityFetchSettings()
    http_client = client or httpx.AsyncClient(
        follow_redirects=False,
        timeout=httpx.Timeout(resolved.timeout_seconds),
        headers={"User-Agent": resolved.user_agent, "Accept": "application/json"},
    )
    try:
        for artist_mbid in identifiers:
            artists.append(  # noqa: PERF401  # Sequential awaits bound and order network requests.
                await fetch_artist_popularity(artist_mbid, settings=resolved, client=http_client)
            )
    finally:
        if owns_client:
            await http_client.aclose()
    return PopularityProbeBundle(artists=tuple(artists))


def measure_exact_catalog_coverage(
    bundle: PopularityProbeBundle,
    *,
    recording_mbids: Iterable[UUID],
    release_group_mbids: Iterable[UUID],
) -> tuple[RankingCoverage, ...]:
    """Count exact ID intersections separately for sparse recording and album catalogs."""
    recordings = frozenset(recording_mbids)
    release_groups = frozenset(release_group_mbids)
    coverage: list[RankingCoverage] = []
    for artist in bundle.artists:
        rows = artist.recording_ranking.results
        recording_ranks = tuple(
            rank for rank, row in enumerate(rows, start=1) if row.recording_mbid in recordings
        )
        coverage.append(
            RankingCoverage(
                artist_mbid=artist.artist_mbid,
                ranking_kind="recording",
                result_count=len(rows),
                exact_catalog_match_count=len(recording_ranks),
                unmatched_result_count=len(rows) - len(recording_ranks),
                matched_candidate_ranks=recording_ranks,
            )
        )
        groups = artist.release_group_ranking.results
        group_ranks = tuple(
            rank
            for rank, row in enumerate(groups, start=1)
            if row.release_group_mbid in release_groups
        )
        coverage.append(
            RankingCoverage(
                artist_mbid=artist.artist_mbid,
                ranking_kind="release_group",
                result_count=len(groups),
                exact_catalog_match_count=len(group_ranks),
                unmatched_result_count=len(groups) - len(group_ranks),
                matched_candidate_ranks=group_ranks,
            )
        )
    return tuple(coverage)


def compare_album_candidate_packet(
    bundle: PopularityProbeBundle,
    packet: MusicBrainzAlbumReviewPacket,
) -> tuple[AlbumCandidateSeedOverlap, ...]:
    """Join only exact artist and release-group IDs from the retained album packet."""
    if review_source_sha256(packet) != packet.output_sha256:
        raise ListenBrainzPopularityError("album review packet output hash does not replay")
    rankings = {artist.artist_mbid: artist.release_group_ranking for artist in bundle.artists}
    overlaps: list[AlbumCandidateSeedOverlap] = []
    for seed in packet.seed_reviews:
        candidate_artists = {
            UUID(artist_mbid)
            for candidate in seed.candidates
            for artist_mbid in candidate.credited_artist_mbids
            if UUID(artist_mbid) in rankings
        }
        for artist_mbid in sorted(candidate_artists, key=str):
            candidate_ids = {
                UUID(candidate.release_group_mbid)
                for candidate in seed.candidates
                if str(artist_mbid) in candidate.credited_artist_mbids
            }
            ranked_ids = {
                row.release_group_mbid: rank
                for rank, row in enumerate(rankings[artist_mbid].results, start=1)
            }
            ranks = tuple(
                sorted(ranked_ids[group_id] for group_id in candidate_ids & ranked_ids.keys())
            )
            overlaps.append(
                AlbumCandidateSeedOverlap(
                    seed_name=seed.normalized_seed_name,
                    artist_mbid=artist_mbid,
                    packet_candidate_count=len(candidate_ids),
                    matched_candidate_count=len(ranks),
                    abstained_candidate_count=len(candidate_ids) - len(ranks),
                    matched_candidate_ranks=ranks,
                )
            )
    return tuple(overlaps)


def verify_popularity_probe_bundle(bundle: PopularityProbeBundle) -> None:
    """Replay every raw response and verify receipt, exact IDs, counts, and rank order."""
    artist_ids = tuple(artist.artist_mbid for artist in bundle.artists)
    if len(set(artist_ids)) != len(artist_ids):
        raise ListenBrainzPopularityError("probe bundle repeats an artist MBID")
    for artist in bundle.artists:
        if (
            artist.recording_ranking.artist_mbid != artist.artist_mbid
            or artist.release_group_ranking.artist_mbid != artist.artist_mbid
        ):
            raise ListenBrainzPopularityError("ranking artist MBID differs from its bundle artist")
        recording = parse_ranking(
            artist.recording_ranking.raw_payload,
            artist_mbid=artist.artist_mbid,
            ranking_kind="recording",
            receipt=artist.recording_ranking.receipt,
        )
        groups = parse_ranking(
            artist.release_group_ranking.raw_payload,
            artist_mbid=artist.artist_mbid,
            ranking_kind="release_group",
            receipt=artist.release_group_ranking.receipt,
        )
        if recording.results != artist.recording_ranking.results:
            raise ListenBrainzPopularityError("recording ranking projection does not replay")
        if groups.results != artist.release_group_ranking.results:
            raise ListenBrainzPopularityError("release-group ranking projection does not replay")


@overload
async def _fetch_ranking(
    client: httpx.AsyncClient,
    artist_mbid: UUID,
    ranking_kind: Literal["recording"],
    settings: PopularityFetchSettings,
) -> RecordingRanking: ...


@overload
async def _fetch_ranking(
    client: httpx.AsyncClient,
    artist_mbid: UUID,
    ranking_kind: Literal["release_group"],
    settings: PopularityFetchSettings,
) -> ReleaseGroupRanking: ...


async def _fetch_ranking(
    client: httpx.AsyncClient,
    artist_mbid: UUID,
    ranking_kind: Literal["recording", "release_group"],
    settings: PopularityFetchSettings,
) -> RecordingRanking | ReleaseGroupRanking:
    route_kind = "recordings" if ranking_kind == "recording" else "release-groups"
    url = f"{_ORIGIN}/1/popularity/top-{route_kind}-for-artist/{artist_mbid}"
    payload = await _bounded_json(client, url, settings)
    receipt = PopularityReceipt(
        source_url=HttpUrl(url),
        fetched_at=datetime.now(UTC),
        payload_sha256=hashlib.sha256(payload).hexdigest(),
        payload_bytes=len(payload),
        ranking_kind=ranking_kind,
        artist_mbid=artist_mbid,
    )
    return parse_ranking(
        payload, artist_mbid=artist_mbid, ranking_kind=ranking_kind, receipt=receipt
    )


def _first_ten_rows[T: RecordingPopularity | ReleaseGroupPopularity](
    payload: bytes, row_type: type[T]
) -> tuple[T, ...]:
    """Validate complete array syntax while projecting only its first ten rows."""
    try:
        root_event = next(ijson.parse(BytesIO(payload)), None)
        if root_event is None or root_event[:2] != ("", "start_array"):
            raise ListenBrainzPopularityError("popularity response root is not an array")
        rows: list[T] = []
        for index, raw_row in enumerate(ijson.items(BytesIO(payload), "item")):
            if index < _MAX_RESULTS:
                row_bytes = json.dumps(raw_row, separators=(",", ":")).encode()
                rows.append(TypeAdapter(row_type).validate_json(row_bytes, strict=True))
        return tuple(rows)
    except (ijson.common.JSONError, ValidationError) as error:
        raise ListenBrainzPopularityError("popularity response failed its strict schema") from error


async def _bounded_json(
    client: httpx.AsyncClient, url: str, settings: PopularityFetchSettings
) -> bytes:
    async with client.stream("GET", url) as response:
        if str(response.url) != url:
            raise ListenBrainzPopularityError("popularity request was redirected")
        response.raise_for_status()
        if response.headers.get("content-type", "").partition(";")[0].strip() != "application/json":
            raise ListenBrainzPopularityError("popularity response is not application/json")
        length = response.headers.get("content-length")
        if length is not None and (
            not length.isdecimal() or int(length) > settings.maximum_response_bytes
        ):
            raise ListenBrainzPopularityError("popularity response exceeds maximum_response_bytes")
        chunks: list[bytes] = []
        size = 0
        async for chunk in response.aiter_bytes(_CHUNK_SIZE):
            size += len(chunk)
            if size > settings.maximum_response_bytes:
                raise ListenBrainzPopularityError(
                    "popularity response exceeds maximum_response_bytes"
                )
            chunks.append(chunk)
    if not chunks:
        raise ListenBrainzPopularityError("popularity response is empty")
    return b"".join(chunks)
