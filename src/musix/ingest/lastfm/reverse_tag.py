"""Review-only, MBID-bound reverse tag evidence from a source adapter.

The Last.fm implementation is deliberately isolated behind the small
``ReverseTagAdapter`` protocol.  It resolves no catalog identity and produces
only source-qualified review evidence: a requested seed label, a MusicBrainz
artist ID returned by the source, and a matching tag returned for that same
artist ID.  A source artist name without an MBID is retained as review data,
never upgraded through a name join.
"""

from __future__ import annotations

import asyncio
import hashlib
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Literal, Protocol
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field, model_validator

from musix.common import sha256_file, sha256_json, write_durable_bytes
from musix.models import FrozenModel
from musix.storage import ObjectKey, ObjectStore, ObjectWrite
from musix.taxonomy.seeds.reconciliation import (
    SeedReconciliationArtifact,
    verify_seed_reconciliation,
)
from musix.taxonomy.seeds.universe import normalize_label

if TYPE_CHECKING:
    from pathlib import Path

_SHA256: Final = r"^[0-9a-f]{64}$"
_REVIEW_DISPOSITIONS: Final = frozenset({"review_only", "ambiguous", "unresolved"})
_TRANSIENT_HTTP: Final = frozenset({429, 500, 502, 503, 504})
_TRANSIENT_API_ERRORS: Final = frozenset({11, 16, 29})
_HTTP_BAD_REQUEST: Final = 400

type LastFmMethod = Literal["tag.getTopArtists", "artist.getTopTags"]
type ReverseTagAbstentionReason = Literal[
    "no_top_artists",
    "no_mbid_linked_top_artist",
    "no_exact_corroborating_artist_tag",
]
type NameOnlyReviewReason = Literal["missing_or_invalid_artist_mbid"]


class LastFmReverseTagError(RuntimeError):
    """Report a bounded Last.fm transport, cache, or source-shape failure."""


class LastFmTransientError(LastFmReverseTagError):
    """Mark one retryable upstream response."""


class _StrictModel(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")


class _LastFmResponseModel(BaseModel):
    """Parse an upstream response while ignoring fields outside this adapter."""

    model_config = ConfigDict(frozen=True, strict=True, extra="ignore")


class LastFmReverseTagSettings(FrozenModel):
    """Explicit bounded transport and evidence policy for one adapter run."""

    revision: Literal["lastfm-reverse-tag-settings-v1"] = "lastfm-reverse-tag-settings-v1"
    maximum_seed_labels: int = Field(default=6_291, ge=1, le=6_291)
    top_artists_per_tag: int = Field(default=3, ge=1, le=50)
    maximum_tags_per_artist: int = Field(default=100, ge=1, le=500)
    maximum_response_bytes: int = Field(default=2 * 1024 * 1024, ge=1, le=16 * 1024 * 1024)
    maximum_concurrency: int = Field(default=4, ge=1, le=16)
    requests_per_second: float = Field(default=3.0, gt=0.0, le=10.0)
    timeout_seconds: float = Field(default=30.0, gt=0.0, le=180.0)
    retries: int = Field(default=3, ge=0, le=6)
    historical_inputs_read: Literal[False] = False
    audio_inputs_read: Literal[False] = False
    output_semantics: Literal["review_only_source_claims"] = "review_only_source_claims"


class LastFmReverseTagQuery(_StrictModel):
    """One reproducible request descriptor with no credential-bearing fields."""

    method: LastFmMethod
    tag: str | None = Field(default=None, min_length=1, max_length=500)
    artist_mbid: str | None = Field(default=None, pattern=r"^[0-9a-f-]{36}$")
    source_item_id: str | None = Field(default=None, min_length=1, max_length=200)
    seed_name: str | None = Field(default=None, min_length=1, max_length=500)
    request_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def _shape_and_hash(self) -> LastFmReverseTagQuery:
        if self.method == "tag.getTopArtists":
            if self.tag is None or self.artist_mbid is not None or self.source_item_id is None:
                raise ValueError("tag.getTopArtists query requires only a seed-bound tag")
            if self.seed_name is None:
                raise ValueError("tag.getTopArtists query requires the seed name")
        elif self.tag is not None or self.artist_mbid is None:
            raise ValueError("artist.getTopTags query requires only an artist MBID")
        if self.method == "artist.getTopTags" and (
            self.source_item_id is not None or self.seed_name is not None
        ):
            raise ValueError("artist.getTopTags query cannot claim one seed")
        expected = sha256_json(self.model_dump(mode="json", exclude={"request_sha256"}))
        if self.request_sha256 != expected:
            raise ValueError("Last.fm query hash does not match its descriptor")
        return self


def _tag_query(source_item_id: str, seed_name: str) -> LastFmReverseTagQuery:
    preliminary = LastFmReverseTagQuery.model_construct(
        method="tag.getTopArtists",
        tag=seed_name,
        artist_mbid=None,
        source_item_id=source_item_id,
        seed_name=seed_name,
        request_sha256="0" * 64,
    )
    return LastFmReverseTagQuery(
        **preliminary.model_dump(mode="python", exclude={"request_sha256"}),
        request_sha256=sha256_json(preliminary.model_dump(mode="json", exclude={"request_sha256"})),
    )


def _artist_query(artist_mbid: str) -> LastFmReverseTagQuery:
    preliminary = LastFmReverseTagQuery.model_construct(
        method="artist.getTopTags",
        tag=None,
        artist_mbid=artist_mbid,
        source_item_id=None,
        seed_name=None,
        request_sha256="0" * 64,
    )
    return LastFmReverseTagQuery(
        **preliminary.model_dump(mode="python", exclude={"request_sha256"}),
        request_sha256=sha256_json(preliminary.model_dump(mode="json", exclude={"request_sha256"})),
    )


class LastFmReverseTagQueryManifest(FrozenModel):
    """Stable initial request plan for every eligible reconciliation disposition."""

    revision: Literal["lastfm-reverse-tag-query-manifest-v1"] = (
        "lastfm-reverse-tag-query-manifest-v1"
    )
    adapter_key: Literal["lastfm_reverse_tag_v1"] = "lastfm_reverse_tag_v1"
    seed_reconciliation_output_sha256: str = Field(pattern=_SHA256)
    seed_identity_sha256: str = Field(pattern=_SHA256)
    settings: LastFmReverseTagSettings
    settings_sha256: str = Field(pattern=_SHA256)
    queries: tuple[LastFmReverseTagQuery, ...]
    output_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def _complete(self) -> LastFmReverseTagQueryManifest:
        if self.settings_sha256 != sha256_json(self.settings.model_dump(mode="json")):
            raise ValueError("Last.fm settings hash does not match settings")
        if len(self.queries) > self.settings.maximum_seed_labels:
            raise ValueError("Last.fm query manifest exceeds maximum_seed_labels")
        identities = tuple(query.source_item_id for query in self.queries)
        if any(item is None for item in identities) or len(set(identities)) != len(identities):
            raise ValueError("Last.fm tag queries must cover unique seed IDs")
        if any(query.method != "tag.getTopArtists" for query in self.queries):
            raise ValueError("initial Last.fm manifest may only contain tag queries")
        expected = sha256_json(self.model_dump(mode="json", exclude={"output_sha256"}))
        if self.output_sha256 != expected:
            raise ValueError("Last.fm query manifest hash does not match its content")
        return self


class _LastFmTopArtist(_LastFmResponseModel):
    name: str = Field(min_length=1)
    mbid: str = ""


class _LastFmTopArtists(_LastFmResponseModel):
    artist: tuple[_LastFmTopArtist, ...] = ()


class _LastFmTopArtistsResponse(_LastFmResponseModel):
    topartists: _LastFmTopArtists


class _LastFmTag(_LastFmResponseModel):
    name: str = Field(min_length=1)


class _LastFmTopTags(_LastFmResponseModel):
    tag: tuple[_LastFmTag, ...] = ()


class _LastFmTopTagsResponse(_LastFmResponseModel):
    toptags: _LastFmTopTags


class _LastFmApiError(_LastFmResponseModel):
    error: int
    message: str = Field(min_length=1)


@dataclass(frozen=True, slots=True)
class CachedLastFmResponse:
    """A cache-owned raw response; it is published to ObjectStore only after parsing."""

    query: LastFmReverseTagQuery
    path: Path
    sha256: str
    byte_size: int
    cache_hit: bool


class LastFmResponseCache:
    """Own deterministic cache paths separately from the immutable ObjectStore."""

    def __init__(self, root: Path) -> None:
        """Bind one caller-owned deterministic cache root."""
        self._root = root

    def _path(self, query: LastFmReverseTagQuery) -> Path:
        return self._root / "requests" / "sha256" / f"{query.request_sha256}.json"

    async def load(
        self, query: LastFmReverseTagQuery, *, maximum_response_bytes: int
    ) -> CachedLastFmResponse | None:
        """Return an existing non-empty raw response without making a network call."""
        path = self._path(query)
        if not path.is_file():
            return None
        digest, size = await asyncio.to_thread(_hash_and_size, path, maximum_response_bytes)
        if size == 0:
            raise LastFmReverseTagError("Last.fm response cache contains an empty object")
        return CachedLastFmResponse(
            query=query,
            path=path,
            sha256=digest,
            byte_size=size,
            cache_hit=True,
        )

    async def store(
        self, query: LastFmReverseTagQuery, payload: bytes, *, maximum_response_bytes: int
    ) -> CachedLastFmResponse:
        """Atomically cache raw bytes, rejecting a conflicting request replay."""
        if len(payload) > maximum_response_bytes:
            raise LastFmReverseTagError("Last.fm response exceeds configured bound")
        path = self._path(query)
        if path.is_file():
            existing = await self.load(query, maximum_response_bytes=maximum_response_bytes)
            if existing is None:
                raise AssertionError("existing Last.fm cache object disappeared")
            if existing.sha256 != hashlib.sha256(payload).hexdigest():
                raise LastFmReverseTagError("Last.fm cache query maps to different immutable bytes")
            return existing
        path.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(write_durable_bytes, path, payload)
        return CachedLastFmResponse(
            query=query,
            path=path,
            sha256=hashlib.sha256(payload).hexdigest(),
            byte_size=len(payload),
            cache_hit=False,
        )


def _hash_and_size(path: Path, maximum_response_bytes: int) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(1_048_576):
            digest.update(chunk)
            size += len(chunk)
            if size > maximum_response_bytes:
                raise LastFmReverseTagError("Last.fm response cache exceeds configured bound")
    return digest.hexdigest(), size


class _RateLimiter:
    """Serialize request starts while leaving response reads concurrent."""

    def __init__(self, requests_per_second: float) -> None:
        self._interval = 1.0 / requests_per_second
        self._next_start = 0.0
        self._lock = asyncio.Lock()

    async def wait(self) -> None:
        async with self._lock:
            now = time.monotonic()
            delay = max(0.0, self._next_start - now)
            self._next_start = max(now, self._next_start) + self._interval
        if delay:
            await asyncio.sleep(delay)


class ReverseTagFetcher(Protocol):
    """Fetch one key-free request descriptor into a verified local response cache."""

    async def fetch(self, query: LastFmReverseTagQuery) -> CachedLastFmResponse:
        """Return a response that exactly corresponds to ``query``."""
        ...


class LastFmHttpClient:
    """Bounded asynchronous Last.fm JSON client with cache-first semantics."""

    def __init__(
        self,
        *,
        api_key: str | None,
        cache: LastFmResponseCache,
        settings: LastFmReverseTagSettings,
        client: httpx.AsyncClient | None = None,
        offline: bool = False,
    ) -> None:
        """Bind credentialed transport state without serializing the API key anywhere."""
        self._api_key = api_key
        self._cache = cache
        self._settings = settings
        self._client = client
        self._offline = offline
        self._limiter = _RateLimiter(settings.requests_per_second)

    async def fetch(self, query: LastFmReverseTagQuery) -> CachedLastFmResponse:
        """Use a cached response or fetch, bound, parse-check, and cache one response."""
        cached = await self._cache.load(
            query, maximum_response_bytes=self._settings.maximum_response_bytes
        )
        if cached is not None:
            return cached
        if self._offline:
            raise FileNotFoundError(f"Last.fm response cache miss for {query.request_sha256}")
        if self._api_key is None:
            raise LastFmReverseTagError("Last.fm API key is unavailable")
        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(
            timeout=httpx.Timeout(self._settings.timeout_seconds), follow_redirects=True
        )
        try:
            payload = await self._fetch_with_retry(client, query)
        finally:
            if owns_client:
                await client.aclose()
        return await self._cache.store(
            query, payload, maximum_response_bytes=self._settings.maximum_response_bytes
        )

    async def _fetch_with_retry(
        self, client: httpx.AsyncClient, query: LastFmReverseTagQuery
    ) -> bytes:
        for attempt in range(self._settings.retries + 1):
            try:
                return await self._fetch_once(client, query)
            except (httpx.TransportError, LastFmTransientError):
                if attempt == self._settings.retries:
                    raise
                await asyncio.sleep(float(2**attempt))
        raise AssertionError("Last.fm retry loop must return or raise")

    async def _fetch_once(self, client: httpx.AsyncClient, query: LastFmReverseTagQuery) -> bytes:
        await self._limiter.wait()
        params: dict[str, str | int] = {
            "method": query.method,
            "api_key": self._api_key or "",
            "format": "json",
        }
        if query.method == "tag.getTopArtists":
            if query.tag is None:
                raise AssertionError("validated tag query has no tag")
            params.update({"tag": query.tag, "limit": self._settings.top_artists_per_tag})
        else:
            if query.artist_mbid is None:
                raise AssertionError("validated artist query has no MBID")
            params["mbid"] = query.artist_mbid
        async with client.stream(
            "GET", "https://ws.audioscrobbler.com/2.0/", params=params
        ) as response:
            if response.status_code in _TRANSIENT_HTTP:
                raise LastFmTransientError(f"Last.fm transient HTTP status {response.status_code}")
            if response.status_code >= _HTTP_BAD_REQUEST:
                raise LastFmReverseTagError(f"Last.fm HTTP status {response.status_code}")
            content_type = (
                response.headers.get("content-type", "").partition(";")[0].strip().casefold()
            )
            if "json" not in content_type:
                raise LastFmReverseTagError("Last.fm response is not JSON")
            payload = bytearray()
            async for chunk in response.aiter_bytes():
                payload.extend(chunk)
                if len(payload) > self._settings.maximum_response_bytes:
                    raise LastFmReverseTagError("Last.fm response exceeds configured bound")
        if not payload:
            raise LastFmReverseTagError("Last.fm returned an empty response")
        self._raise_api_error(bytes(payload))
        return bytes(payload)

    @staticmethod
    def _raise_api_error(payload: bytes) -> None:
        try:
            error = _LastFmApiError.model_validate_json(payload)
        except ValueError:
            return
        if error.error in _TRANSIENT_API_ERRORS:
            raise LastFmTransientError(f"Last.fm transient API error {error.error}")
        raise LastFmReverseTagError(f"Last.fm API error {error.error}")


class ReverseTagAdapter(Protocol):
    """Source-agnostic contract for an external tag-to-artist evidence adapter."""

    @property
    def key(self) -> str:
        """Return the stable adapter identifier."""
        ...

    def build_query_manifest(
        self,
        reconciliation: SeedReconciliationArtifact,
        settings: LastFmReverseTagSettings,
    ) -> LastFmReverseTagQueryManifest:
        """Build a credential-free deterministic seed query plan."""
        ...

    async def collect(
        self,
        manifest: LastFmReverseTagQueryManifest,
        fetcher: ReverseTagFetcher,
    ) -> LastFmReverseTagCollection:
        """Collect review-only evidence using a bounded asynchronous fetcher."""
        ...


class ReverseTagAdapterRegistry:
    """Resolve one explicit source adapter without reflection or silent fallback."""

    def __init__(self, adapters: tuple[ReverseTagAdapter, ...]) -> None:
        """Index a closed adapter set and reject duplicate stable keys."""
        indexed = {adapter.key: adapter for adapter in adapters}
        if len(indexed) != len(adapters):
            raise ValueError("reverse tag adapter keys must be unique")
        self._adapters = indexed

    def resolve(self, key: str) -> ReverseTagAdapter:
        """Resolve a requested adapter or fail closed."""
        try:
            return self._adapters[key]
        except KeyError as error:
            raise KeyError(f"no reverse tag adapter registered for {key!r}") from error


class LastFmNameOnlyReview(FrozenModel):
    """Retain a top-artist name that lacks a usable source MBID for human review."""

    source_item_id: str = Field(min_length=1)
    seed_name: str = Field(min_length=1)
    artist_name: str = Field(min_length=1)
    artist_rank: int = Field(ge=1)
    reason: NameOnlyReviewReason
    tag_query_sha256: str = Field(pattern=_SHA256)


class LastFmExactSourceClaim(FrozenModel):
    """One exact normalized tag corroborated through the same source-provided MBID."""

    source_item_id: str = Field(min_length=1)
    seed_name: str = Field(min_length=1)
    seed_normalized_name: str = Field(min_length=1)
    artist_mbid: str = Field(pattern=r"^[0-9a-f-]{36}$")
    artist_name: str = Field(min_length=1)
    top_artist_rank: int = Field(ge=1)
    corroborating_tag_name: str = Field(min_length=1)
    corroborating_tag_rank: int = Field(ge=1)
    tag_query_sha256: str = Field(pattern=_SHA256)
    artist_query_sha256: str = Field(pattern=_SHA256)
    claim_kind: Literal["mbid_linked_exact_normalized_source_claim"] = (
        "mbid_linked_exact_normalized_source_claim"
    )


class LastFmReverseTagAbstention(FrozenModel):
    """Explain why a selected seed did not receive an exact MBID-backed claim."""

    source_item_id: str = Field(min_length=1)
    seed_name: str = Field(min_length=1)
    reason: ReverseTagAbstentionReason
    top_artist_count: int = Field(ge=0)
    mbid_linked_artist_count: int = Field(ge=0)


class LastFmReverseTagCoverage(FrozenModel):
    """Account for every query target and every bounded request response."""

    target_seed_count: int = Field(ge=0)
    tag_query_count: int = Field(ge=0)
    artist_query_count: int = Field(ge=0)
    cache_hit_count: int = Field(ge=0)
    raw_response_count: int = Field(ge=0)
    exact_mbid_claim_count: int = Field(ge=0)
    name_only_review_count: int = Field(ge=0)
    abstention_count: int = Field(ge=0)


@dataclass(frozen=True, slots=True)
class LastFmReverseTagCollection:
    """Validated in-memory summary plus local raw files awaiting immutable custody."""

    manifest: LastFmReverseTagQueryManifest
    responses: tuple[CachedLastFmResponse, ...]
    exact_claims: tuple[LastFmExactSourceClaim, ...]
    name_only_reviews: tuple[LastFmNameOnlyReview, ...]
    abstentions: tuple[LastFmReverseTagAbstention, ...]
    coverage: LastFmReverseTagCoverage


def _canonical_mbid(value: str) -> str | None:
    try:
        return str(UUID(value))
    except ValueError:
        return None


async def _fetch_many(
    queries: tuple[LastFmReverseTagQuery, ...],
    fetcher: ReverseTagFetcher,
    maximum_concurrency: int,
) -> tuple[CachedLastFmResponse, ...]:
    semaphore = asyncio.Semaphore(maximum_concurrency)

    async def bounded(query: LastFmReverseTagQuery) -> CachedLastFmResponse:
        async with semaphore:
            return await fetcher.fetch(query)

    async with asyncio.TaskGroup() as group:
        tasks = tuple(group.create_task(bounded(query)) for query in queries)
    return tuple(task.result() for task in tasks)


def _bounded_response_bytes(path: Path, maximum_response_bytes: int) -> bytes:
    """Read one raw response only after reapplying the configured byte bound."""
    payload = bytearray()
    with path.open("rb") as stream:
        while chunk := stream.read(1_048_576):
            payload.extend(chunk)
            if len(payload) > maximum_response_bytes:
                raise LastFmReverseTagError("Last.fm response cache exceeds configured bound")
    if not payload:
        raise LastFmReverseTagError("Last.fm response cache contains an empty object")
    return bytes(payload)


def _top_artists(
    response: CachedLastFmResponse, maximum: int, maximum_response_bytes: int
) -> tuple[_LastFmTopArtist, ...]:
    parsed = _LastFmTopArtistsResponse.model_validate_json(
        _bounded_response_bytes(response.path, maximum_response_bytes)
    )
    if len(parsed.topartists.artist) > maximum:
        raise LastFmReverseTagError("Last.fm top artist response exceeds configured limit")
    return parsed.topartists.artist


def _top_tags(
    response: CachedLastFmResponse, maximum: int, maximum_response_bytes: int
) -> tuple[_LastFmTag, ...]:
    parsed = _LastFmTopTagsResponse.model_validate_json(
        _bounded_response_bytes(response.path, maximum_response_bytes)
    )
    if len(parsed.toptags.tag) > maximum:
        raise LastFmReverseTagError("Last.fm top tag response exceeds configured limit")
    return parsed.toptags.tag


@dataclass(frozen=True, slots=True)
class _MbidObservation:
    query: LastFmReverseTagQuery
    artist: _LastFmTopArtist
    artist_rank: int
    artist_mbid: str


@dataclass(frozen=True, slots=True)
class _TagResponseScan:
    observations: tuple[_MbidObservation, ...]
    name_only_reviews: tuple[LastFmNameOnlyReview, ...]
    top_counts: dict[str, int]
    mbid_counts: dict[str, int]


def _scan_tag_responses(
    manifest: LastFmReverseTagQueryManifest,
    tag_responses: tuple[CachedLastFmResponse, ...],
) -> _TagResponseScan:
    response_by_query = {response.query.request_sha256: response for response in tag_responses}
    if len(response_by_query) != len(tag_responses):
        raise LastFmReverseTagError("Last.fm response set repeats a tag query")
    observations: list[_MbidObservation] = []
    name_only: list[LastFmNameOnlyReview] = []
    top_counts: dict[str, int] = {}
    mbid_counts: dict[str, int] = {}
    for query in manifest.queries:
        response = response_by_query.get(query.request_sha256)
        if response is None:
            raise LastFmReverseTagError("Last.fm tag query lacks a response")
        artists = _top_artists(
            response,
            manifest.settings.top_artists_per_tag,
            manifest.settings.maximum_response_bytes,
        )
        if query.source_item_id is None or query.seed_name is None:
            raise AssertionError("validated tag manifest query lacks seed fields")
        top_counts[query.source_item_id] = len(artists)
        valid_count = 0
        for rank, artist in enumerate(artists, start=1):
            mbid = _canonical_mbid(artist.mbid)
            if mbid is None:
                name_only.append(
                    LastFmNameOnlyReview(
                        source_item_id=query.source_item_id,
                        seed_name=query.seed_name,
                        artist_name=artist.name,
                        artist_rank=rank,
                        reason="missing_or_invalid_artist_mbid",
                        tag_query_sha256=query.request_sha256,
                    )
                )
                continue
            valid_count += 1
            observations.append(_MbidObservation(query, artist, rank, mbid))
        mbid_counts[query.source_item_id] = valid_count
    return _TagResponseScan(tuple(observations), tuple(name_only), top_counts, mbid_counts)


def _exact_claims_from_observations(
    observations: tuple[_MbidObservation, ...],
    artist_by_mbid: dict[str, CachedLastFmResponse],
    maximum_tags_per_artist: int,
    maximum_response_bytes: int,
) -> tuple[LastFmExactSourceClaim, ...]:
    exact: list[LastFmExactSourceClaim] = []
    for observation in observations:
        artist_response = artist_by_mbid[observation.artist_mbid]
        tags = _top_tags(artist_response, maximum_tags_per_artist, maximum_response_bytes)
        query = observation.query
        if query.source_item_id is None or query.seed_name is None:
            raise AssertionError("validated tag manifest query lacks seed fields")
        normalized = normalize_label(query.seed_name)
        for tag_rank, tag in enumerate(tags, start=1):
            if normalize_label(tag.name) != normalized:
                continue
            exact.append(
                LastFmExactSourceClaim(
                    source_item_id=query.source_item_id,
                    seed_name=query.seed_name,
                    seed_normalized_name=normalized,
                    artist_mbid=observation.artist_mbid,
                    artist_name=observation.artist.name,
                    top_artist_rank=observation.artist_rank,
                    corroborating_tag_name=tag.name,
                    corroborating_tag_rank=tag_rank,
                    tag_query_sha256=query.request_sha256,
                    artist_query_sha256=artist_response.query.request_sha256,
                )
            )
            break
    return tuple(
        sorted(
            {(claim.source_item_id, claim.artist_mbid): claim for claim in exact}.values(),
            key=lambda claim: (claim.source_item_id, claim.top_artist_rank, claim.artist_mbid),
        )
    )


def _abstentions_from_scan(
    manifest: LastFmReverseTagQueryManifest,
    scan: _TagResponseScan,
    exact_claims: tuple[LastFmExactSourceClaim, ...],
) -> tuple[LastFmReverseTagAbstention, ...]:
    exact_ids = {claim.source_item_id for claim in exact_claims}
    abstentions: list[LastFmReverseTagAbstention] = []
    for query in manifest.queries:
        if query.source_item_id is None or query.seed_name is None:
            raise AssertionError("validated tag manifest query lacks seed fields")
        if query.source_item_id in exact_ids:
            continue
        top_count = scan.top_counts[query.source_item_id]
        mbid_count = scan.mbid_counts[query.source_item_id]
        reason: ReverseTagAbstentionReason
        if top_count == 0:
            reason = "no_top_artists"
        elif mbid_count == 0:
            reason = "no_mbid_linked_top_artist"
        else:
            reason = "no_exact_corroborating_artist_tag"
        abstentions.append(
            LastFmReverseTagAbstention(
                source_item_id=query.source_item_id,
                seed_name=query.seed_name,
                reason=reason,
                top_artist_count=top_count,
                mbid_linked_artist_count=mbid_count,
            )
        )
    return tuple(sorted(abstentions, key=lambda item: item.source_item_id))


class LastFmReverseTagAdapter:
    """Last.fm implementation of the generic reverse-tag adapter boundary."""

    key = "lastfm_reverse_tag_v1"

    def build_query_manifest(
        self,
        reconciliation: SeedReconciliationArtifact,
        settings: LastFmReverseTagSettings,
    ) -> LastFmReverseTagQueryManifest:
        """Plan one credential-free tag query for each selected review seed."""
        verify_seed_reconciliation(reconciliation)
        targets = tuple(
            row
            for row in sorted(reconciliation.dispositions, key=lambda item: item.source_item_id)
            if row.disposition in _REVIEW_DISPOSITIONS
        )[: settings.maximum_seed_labels]
        queries = tuple(_tag_query(row.source_item_id, row.seed_name) for row in targets)
        preliminary = LastFmReverseTagQueryManifest.model_construct(
            seed_reconciliation_output_sha256=reconciliation.output_sha256,
            seed_identity_sha256=reconciliation.seed_identity_sha256,
            settings=settings,
            settings_sha256=sha256_json(settings.model_dump(mode="json")),
            queries=queries,
            output_sha256="0" * 64,
        )
        return LastFmReverseTagQueryManifest(
            **preliminary.model_dump(mode="python", exclude={"output_sha256"}),
            output_sha256=sha256_json(
                preliminary.model_dump(mode="json", exclude={"output_sha256"})
            ),
        )

    async def collect(
        self,
        manifest: LastFmReverseTagQueryManifest,
        fetcher: ReverseTagFetcher,
    ) -> LastFmReverseTagCollection:
        """Fetch tag artists, then corroborate only their source-supplied MBIDs."""
        tag_responses = await _fetch_many(
            manifest.queries, fetcher, manifest.settings.maximum_concurrency
        )
        scan = _scan_tag_responses(manifest, tag_responses)
        artist_queries = tuple(
            _artist_query(mbid) for mbid in sorted({item.artist_mbid for item in scan.observations})
        )
        artist_responses = await _fetch_many(
            artist_queries, fetcher, manifest.settings.maximum_concurrency
        )
        artist_by_mbid = {
            response.query.artist_mbid: response
            for response in artist_responses
            if response.query.artist_mbid is not None
        }
        if len(artist_by_mbid) != len(artist_queries):
            raise LastFmReverseTagError("Last.fm artist tag responses do not cover unique MBIDs")
        unique_exact = _exact_claims_from_observations(
            scan.observations,
            artist_by_mbid,
            manifest.settings.maximum_tags_per_artist,
            manifest.settings.maximum_response_bytes,
        )
        abstentions = _abstentions_from_scan(manifest, scan, unique_exact)
        all_responses = tuple(
            sorted(
                (*tag_responses, *artist_responses),
                key=lambda response: response.query.request_sha256,
            )
        )
        coverage = LastFmReverseTagCoverage(
            target_seed_count=len(manifest.queries),
            tag_query_count=len(tag_responses),
            artist_query_count=len(artist_responses),
            cache_hit_count=sum(response.cache_hit for response in all_responses),
            raw_response_count=len(all_responses),
            exact_mbid_claim_count=len(unique_exact),
            name_only_review_count=len(scan.name_only_reviews),
            abstention_count=len(abstentions),
        )
        return LastFmReverseTagCollection(
            manifest=manifest,
            responses=all_responses,
            exact_claims=unique_exact,
            name_only_reviews=tuple(
                sorted(
                    scan.name_only_reviews,
                    key=lambda review: (
                        review.source_item_id,
                        review.artist_rank,
                        review.artist_name,
                    ),
                )
            ),
            abstentions=abstentions,
            coverage=coverage,
        )


class LastFmRawResponseObject(FrozenModel):
    """Bind one parsed query response to its immutable raw ObjectStore copy."""

    query: LastFmReverseTagQuery
    raw_object: ObjectWrite


class LastFmReverseTagArtifact(FrozenModel):
    """Published review layer; it never creates a reconciliation identity or membership."""

    revision: Literal["lastfm-reverse-tag-evidence-v1"] = "lastfm-reverse-tag-evidence-v1"
    query_manifest_output_sha256: str = Field(pattern=_SHA256)
    seed_reconciliation_output_sha256: str = Field(pattern=_SHA256)
    seed_identity_sha256: str = Field(pattern=_SHA256)
    settings: LastFmReverseTagSettings
    settings_sha256: str = Field(pattern=_SHA256)
    raw_responses: tuple[LastFmRawResponseObject, ...]
    exact_mbid_source_claims: tuple[LastFmExactSourceClaim, ...]
    name_only_reviews: tuple[LastFmNameOnlyReview, ...]
    abstentions: tuple[LastFmReverseTagAbstention, ...]
    coverage: LastFmReverseTagCoverage
    review_only_candidates: Literal[True] = True
    observed_identities_promoted: Literal[0] = 0
    memberships_promoted: Literal[0] = 0
    historical_inputs_read: Literal[False] = False
    audio_inputs_read: Literal[False] = False
    output_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def _complete(self) -> LastFmReverseTagArtifact:
        if self.settings_sha256 != sha256_json(self.settings.model_dump(mode="json")):
            raise ValueError("Last.fm artifact settings hash does not match settings")
        response_ids = tuple(item.query.request_sha256 for item in self.raw_responses)
        if len(response_ids) != len(set(response_ids)):
            raise ValueError("Last.fm artifact repeats a raw response query")
        if len(self.raw_responses) != self.coverage.raw_response_count:
            raise ValueError("Last.fm raw response count does not match coverage")
        target_ids = {item.source_item_id for item in self.abstentions}
        target_ids.update(item.source_item_id for item in self.exact_mbid_source_claims)
        if len(target_ids) != self.coverage.target_seed_count:
            raise ValueError("Last.fm evidence does not account for every target seed")
        if len(self.exact_mbid_source_claims) != self.coverage.exact_mbid_claim_count:
            raise ValueError("Last.fm exact claim count does not match coverage")
        if len(self.name_only_reviews) != self.coverage.name_only_review_count:
            raise ValueError("Last.fm name-only review count does not match coverage")
        if len(self.abstentions) != self.coverage.abstention_count:
            raise ValueError("Last.fm abstention count does not match coverage")
        expected = sha256_json(self.model_dump(mode="json", exclude={"output_sha256"}))
        if self.output_sha256 != expected:
            raise ValueError("Last.fm artifact hash does not match its content")
        return self


class LastFmReverseTagGate(FrozenModel):
    """Fail-closed review-only and custody gate for the released artifact."""

    artifact_output_sha256: str = Field(pattern=_SHA256)
    deterministic_replay: Literal[True] = True
    mbid_linked_exact_claims_only: Literal[True] = True
    name_only_matches_remain_review: Literal[True] = True
    raw_responses_immutable: Literal[True] = True
    no_historical_or_audio_inputs: Literal[True] = True
    no_identity_or_membership_promotion: Literal[True] = True


class LastFmReverseTagReceipt(FrozenModel):
    """Receipt for the sealed artifact, query plan, and all raw response objects."""

    artifact: ObjectWrite
    query_manifest: ObjectWrite
    raw_responses: tuple[ObjectWrite, ...]
    logical_output_sha256: str = Field(pattern=_SHA256)
    gate: LastFmReverseTagGate


def write_lastfm_query_manifest(manifest: LastFmReverseTagQueryManifest, path: Path) -> str:
    """Write the initial reproducible query plan before any credentialed request."""
    payload = (manifest.model_dump_json(indent=2) + "\n").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    write_durable_bytes(path, payload)
    return hashlib.sha256(payload).hexdigest()


def verify_lastfm_reverse_tag_artifact(artifact: LastFmReverseTagArtifact) -> LastFmReverseTagGate:
    """Replay all logical hashes before declaring publication complete."""
    LastFmReverseTagArtifact.model_validate_json(artifact.model_dump_json())
    return LastFmReverseTagGate(artifact_output_sha256=artifact.output_sha256)


def publish_lastfm_reverse_tag_evidence(
    collection: LastFmReverseTagCollection,
    *,
    query_manifest_path: Path,
    output_path: Path,
    store: ObjectStore,
) -> LastFmReverseTagReceipt:
    """Push raw responses first, then publish one review-only evidence artifact."""
    manifest_sha256 = sha256_file(query_manifest_path)[0]
    if (
        manifest_sha256
        != hashlib.sha256(
            (collection.manifest.model_dump_json(indent=2) + "\n").encode("utf-8")
        ).hexdigest()
    ):
        raise LastFmReverseTagError("written Last.fm query manifest does not match collection")
    manifest_write = store.push(
        query_manifest_path,
        ObjectKey(value=f"lastfm-reverse-tag/query-manifests/sha256/{manifest_sha256}.json"),
    )
    raw_rows: list[LastFmRawResponseObject] = []
    raw_writes: list[ObjectWrite] = []
    for response in collection.responses:
        if sha256_file(response.path)[0] != response.sha256:
            raise LastFmReverseTagError("Last.fm cached raw response changed before publication")
        write = store.push(
            response.path,
            ObjectKey(value=f"lastfm-reverse-tag/raw/sha256/{response.sha256}.json"),
        )
        if write.sha256 != response.sha256 or write.byte_size != response.byte_size:
            raise LastFmReverseTagError("Last.fm ObjectStore changed a raw response")
        raw_rows.append(LastFmRawResponseObject(query=response.query, raw_object=write))
        raw_writes.append(write)
    preliminary = LastFmReverseTagArtifact.model_construct(
        query_manifest_output_sha256=collection.manifest.output_sha256,
        seed_reconciliation_output_sha256=collection.manifest.seed_reconciliation_output_sha256,
        seed_identity_sha256=collection.manifest.seed_identity_sha256,
        settings=collection.manifest.settings,
        settings_sha256=collection.manifest.settings_sha256,
        raw_responses=tuple(raw_rows),
        exact_mbid_source_claims=collection.exact_claims,
        name_only_reviews=collection.name_only_reviews,
        abstentions=collection.abstentions,
        coverage=collection.coverage,
        output_sha256="0" * 64,
    )
    artifact = LastFmReverseTagArtifact(
        **preliminary.model_dump(mode="python", exclude={"output_sha256"}),
        output_sha256=sha256_json(preliminary.model_dump(mode="json", exclude={"output_sha256"})),
    )
    gate = verify_lastfm_reverse_tag_artifact(artifact)
    payload = (artifact.model_dump_json(indent=2) + "\n").encode("utf-8")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    write_durable_bytes(output_path, payload)
    artifact_sha256 = hashlib.sha256(payload).hexdigest()
    artifact_write = store.push(
        output_path,
        ObjectKey(
            value=(
                "lastfm-reverse-tag/artifacts/sha256/"
                f"{artifact.output_sha256}/{artifact_sha256}.json"
            )
        ),
    )
    if artifact_write.sha256 != artifact_sha256:
        raise LastFmReverseTagError("Last.fm ObjectStore changed the published artifact")
    return LastFmReverseTagReceipt(
        artifact=artifact_write,
        query_manifest=manifest_write,
        raw_responses=tuple(raw_writes),
        logical_output_sha256=artifact.output_sha256,
        gate=gate,
    )
