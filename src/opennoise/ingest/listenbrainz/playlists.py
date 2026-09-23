"""Bounded, local-only parsing of public ListenBrainz JSPF playlists.

This is a research boundary, not a source of factual genre claims or static
discovery data.  It retains exact MusicBrainz recording identifiers, receipt
data, and deliberately normalized within-playlist pairs.  It does not fetch
the network, infer a curator from a name, or use playlist titles as labels.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections.abc import (
    Iterable,  # noqa: TC003  # Public function annotations resolve at runtime.
)
from datetime import UTC, datetime
from itertools import combinations
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse
from uuid import UUID

import httpx
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    FiniteFloat,
    HttpUrl,
    ValidationError,
    model_validator,
)

from opennoise.types import (
    Sha256,  # noqa: TC001  # Pydantic resolves this model annotation at runtime.
)

_REVISION = "listenbrainz-public-playlist-probe-v1"
_MUSICBRAINZ_RECORDING_PATH = "/recording/"
_MAXIMUM_RAW_TRACKS = 10_000
_MINIMUM_EXACT_RECORDINGS = 2
_EXPECTED_MUSICBRAINZ_PATH_SEPARATORS = 2
_LISTENBRAINZ_API_ORIGIN = "https://api.listenbrainz.org"
_LISTENBRAINZ_PLAYLIST_PATH_PREFIX = "/1/playlist/"
_RESPONSE_CHUNK_BYTES = 64 * 1024
_EXPECTED_LISTENBRAINZ_PATH_SEPARATORS = 3

type CuratorKind = Literal["reviewed_human", "known_automated", "unknown"]
type PlaylistSelectionMethod = Literal["direct_playlist_id", "title_search_candidate"]


class ListenBrainzPlaylistProbeError(ValueError):
    """Report an unsafe, malformed, or out-of-scope public playlist payload."""


class _BoundaryModel(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")


class _JspfTrack(BaseModel):
    """Accept only the track identifier field needed for an exact identity join."""

    model_config = ConfigDict(frozen=True, strict=True, extra="ignore")

    identifier: str = Field(min_length=1, max_length=1_000)


class _JspfPlaylist(BaseModel):
    """Parse the small public JSPF subset without retaining arbitrary response fields."""

    model_config = ConfigDict(frozen=True, strict=True, extra="ignore")

    identifier: str = Field(min_length=1, max_length=1_000)
    title: str | None = Field(default=None, max_length=500)
    creator: str | None = Field(default=None, max_length=500)
    # JSON arrays arrive as mutable lists. This boundary model is discarded as
    # soon as exact IDs are projected into immutable PlaylistRecording values.
    track: list[_JspfTrack] = Field(default_factory=list, max_length=_MAXIMUM_RAW_TRACKS)


class _JspfEnvelope(BaseModel):
    """Parse the exact root shape returned by the ListenBrainz playlist endpoint."""

    model_config = ConfigDict(frozen=True, strict=True, extra="ignore")

    playlist: _JspfPlaylist


class PlaylistSourceReceipt(_BoundaryModel):
    """Bind a local playlist snapshot to its exact public endpoint response bytes."""

    revision: Literal["listenbrainz-public-playlist-receipt-v1"] = (
        "listenbrainz-public-playlist-receipt-v1"
    )
    source_url: HttpUrl
    fetched_at: datetime
    payload_sha256: Sha256
    payload_bytes: int = Field(ge=1)
    selection_method: PlaylistSelectionMethod
    local_only: Literal[True] = True
    export_allowed: Literal[False] = False
    serving_allowed: Literal[False] = False

    @model_validator(mode="after")
    def require_official_playlist_endpoint(self) -> PlaylistSourceReceipt:
        """Keep a receipt bound to exactly one official public playlist endpoint."""
        playlist_mbid = _listenbrainz_playlist_id_from_url(self.source_url)
        if playlist_mbid is None:
            raise ValueError("playlist receipt source_url is not an official playlist endpoint")
        return self


class PublicPlaylistFetchSettings(_BoundaryModel):
    """Bound explicit-ID public API retrieval before response bytes enter a snapshot."""

    revision: Literal["listenbrainz-public-playlist-fetch-settings-v1"] = (
        "listenbrainz-public-playlist-fetch-settings-v1"
    )
    timeout_seconds: FiniteFloat = Field(default=10.0, gt=0.0, le=30.0)
    maximum_response_bytes: int = Field(default=2 * 1024 * 1024, ge=1, le=8 * 1024 * 1024)
    user_agent: str = Field(
        default="opennoise/0.1 (local playlist research)", min_length=1, max_length=200
    )


class PlaylistProbeSettings(_BoundaryModel):
    """Bound one small playlist experiment before parsing or pair expansion."""

    revision: Literal["listenbrainz-public-playlist-probe-settings-v1"] = (
        "listenbrainz-public-playlist-probe-settings-v1"
    )
    maximum_playlists: int = Field(default=50, ge=1, le=50)
    maximum_unique_recordings_per_playlist: int = Field(default=200, ge=2, le=500)
    pair_weighting: Literal["one_total_vote_per_playlist"] = "one_total_vote_per_playlist"
    title_search_is_independent_genre_evidence: Literal[False] = False


class PlaylistRecording(_BoundaryModel):
    """One exact MusicBrainz recording identity in the original playlist order."""

    recording_mbid: UUID
    ordinal: int = Field(ge=0)


class PublicPlaylistSnapshot(_BoundaryModel):
    """Local projection of one public JSPF playlist, without genre interpretation."""

    revision: Literal["listenbrainz-public-playlist-snapshot-v1"] = (
        "listenbrainz-public-playlist-snapshot-v1"
    )
    receipt: PlaylistSourceReceipt
    playlist_mbid: UUID
    title: str | None = None
    creator: str | None = None
    curator_kind: CuratorKind = "unknown"
    recordings: tuple[PlaylistRecording, ...] = Field(min_length=2)
    raw_track_count: int = Field(ge=0)
    unsupported_track_identifier_count: int = Field(ge=0)
    duplicate_recording_count: int = Field(ge=0)
    content_policy: Literal["metadata_only_no_audio_or_genre_claims"] = (
        "metadata_only_no_audio_or_genre_claims"
    )

    @model_validator(mode="after")
    def require_receipt_matches_playlist(self) -> PublicPlaylistSnapshot:
        """Prevent receipt substitution across two otherwise valid playlist responses."""
        receipt_playlist_mbid = _listenbrainz_playlist_id_from_url(self.receipt.source_url)
        if receipt_playlist_mbid != self.playlist_mbid:
            raise ValueError("playlist receipt endpoint does not match playlist MBID")
        return self


class PlaylistRecordingPair(_BoundaryModel):
    """One normalized unordered recording pair contributed by one playlist."""

    playlist_mbid: UUID
    left_recording_mbid: UUID
    right_recording_mbid: UUID
    weight: FiniteFloat = Field(gt=0.0, le=1.0)


class PlaylistJoinReadiness(_BoundaryModel):
    """Measure exact recording-ID coverage without attempting a fuzzy catalog join."""

    playlist_mbid: UUID
    source_recording_count: int = Field(ge=0)
    exact_catalog_recording_count: int = Field(ge=0)
    unmatched_recording_count: int = Field(ge=0)
    exact_catalog_join_rate: FiniteFloat = Field(ge=0.0, le=1.0)


class ListenBrainzPlaylistProbeArtifact(_BoundaryModel):
    """Aggregate-only report for a local playlist experiment, never a serving asset."""

    revision: Literal["listenbrainz-public-playlist-probe-v1"] = _REVISION
    settings: PlaylistProbeSettings
    source_snapshot_bundle_logical_sha256: Sha256
    source_receipt_payload_sha256s: tuple[Sha256, ...] = Field(min_length=1, max_length=50)
    catalog_recording_id_set_sha256: Sha256
    catalog_recording_id_set_count: int = Field(ge=0)
    export_allowed: Literal[False] = False
    serving_allowed: Literal[False] = False
    independent_genre_evaluation_eligible: Literal[False] = False
    playlist_count: int = Field(ge=0)
    reviewed_human_playlist_count: int = Field(ge=0)
    known_automated_playlist_count: int = Field(ge=0)
    unknown_curator_playlist_count: int = Field(ge=0)
    title_search_candidate_count: int = Field(ge=0)
    unique_recording_count: int = Field(ge=0)
    exact_catalog_recording_count: int = Field(ge=0)
    exact_catalog_join_rate: FiniteFloat = Field(ge=0.0, le=1.0)
    normalized_pair_count: int = Field(ge=0)
    normalized_pair_weight_total: FiniteFloat = Field(ge=0.0)
    join_readiness: tuple[PlaylistJoinReadiness, ...]


class PublicPlaylistSnapshotBundle(_BoundaryModel):
    """One immutable local-only snapshot file written from explicit playlist IDs."""

    revision: Literal["listenbrainz-public-playlist-snapshot-bundle-v1"] = (
        "listenbrainz-public-playlist-snapshot-bundle-v1"
    )
    fetch_settings: PublicPlaylistFetchSettings
    snapshots: tuple[PublicPlaylistSnapshot, ...] = Field(min_length=1, max_length=50)
    raw_object_layout: Literal["raw/sha256/<payload_sha256>"] = "raw/sha256/<payload_sha256>"
    local_only: Literal[True] = True
    export_allowed: Literal[False] = False
    serving_allowed: Literal[False] = False


def parse_public_playlist_snapshot(
    payload: bytes,
    receipt: PlaylistSourceReceipt,
    *,
    curator_kind: CuratorKind = "unknown",
    settings: PlaylistProbeSettings | None = None,
) -> PublicPlaylistSnapshot:
    """Parse one receipt-verified JSPF response into exact, bounded recording IDs."""
    _verify_receipt(payload, receipt)
    try:
        raw_payload: object = json.loads(payload)
    except json.JSONDecodeError as error:
        raise ListenBrainzPlaylistProbeError("playlist payload is not valid JSON") from error
    try:
        envelope = _JspfEnvelope.model_validate(raw_payload)
    except ValidationError as error:
        raise ListenBrainzPlaylistProbeError("playlist payload is not valid public JSPF") from error

    playlist_mbid = _musicbrainz_id(envelope.playlist.identifier, expected_kind="playlist")
    resolved_settings = settings or PlaylistProbeSettings()
    recordings: list[PlaylistRecording] = []
    seen: set[UUID] = set()
    unsupported = 0
    duplicates = 0
    for ordinal, track in enumerate(envelope.playlist.track):
        recording_mbid = _try_musicbrainz_recording_id(track.identifier)
        if recording_mbid is None:
            unsupported += 1
            continue
        if recording_mbid in seen:
            duplicates += 1
            continue
        seen.add(recording_mbid)
        recordings.append(PlaylistRecording(recording_mbid=recording_mbid, ordinal=ordinal))
    if len(recordings) < _MINIMUM_EXACT_RECORDINGS:
        raise ListenBrainzPlaylistProbeError("playlist has fewer than two exact recording IDs")
    if len(recordings) > resolved_settings.maximum_unique_recordings_per_playlist:
        raise ListenBrainzPlaylistProbeError(
            "playlist exceeds maximum_unique_recordings_per_playlist"
        )
    return PublicPlaylistSnapshot(
        receipt=receipt,
        playlist_mbid=playlist_mbid,
        title=envelope.playlist.title,
        creator=envelope.playlist.creator,
        curator_kind=curator_kind,
        recordings=tuple(recordings),
        raw_track_count=len(envelope.playlist.track),
        unsupported_track_identifier_count=unsupported,
        duplicate_recording_count=duplicates,
    )


async def fetch_public_playlist_snapshot(  # noqa: PLR0913  # Explicit source-bound retrieval dimensions.
    playlist_mbid: UUID,
    *,
    selection_method: PlaylistSelectionMethod = "direct_playlist_id",
    curator_kind: CuratorKind = "unknown",
    settings: PublicPlaylistFetchSettings | None = None,
    probe_settings: PlaylistProbeSettings | None = None,
    client: httpx.AsyncClient | None = None,
    raw_object_directory: Path | None = None,
) -> PublicPlaylistSnapshot:
    """Fetch one explicit public playlist through a fixed host and bounded response stream."""
    resolved_settings = settings or PublicPlaylistFetchSettings()
    source_url = _playlist_api_url(playlist_mbid)
    owns_client = client is None
    http_client = client or httpx.AsyncClient(
        follow_redirects=False,
        timeout=httpx.Timeout(resolved_settings.timeout_seconds),
        headers={"User-Agent": resolved_settings.user_agent, "Accept": "application/json"},
    )
    try:
        payload = await _fetch_bounded_json(http_client, source_url, resolved_settings)
    finally:
        if owns_client:
            await http_client.aclose()
    if raw_object_directory is not None:
        _write_raw_playlist_object(payload, raw_object_directory)
    receipt = PlaylistSourceReceipt(
        source_url=HttpUrl(source_url),
        fetched_at=datetime.now(UTC),
        payload_sha256=hashlib.sha256(payload).hexdigest(),
        payload_bytes=len(payload),
        selection_method=selection_method,
    )
    snapshot = parse_public_playlist_snapshot(
        payload,
        receipt,
        curator_kind=curator_kind,
        settings=probe_settings,
    )
    if snapshot.playlist_mbid != playlist_mbid:
        raise ListenBrainzPlaylistProbeError(
            "playlist response identity does not match requested MBID"
        )
    return snapshot


async def fetch_public_playlist_snapshots(
    playlist_mbids: Iterable[UUID],
    *,
    settings: PlaylistProbeSettings | None = None,
    fetch_settings: PublicPlaylistFetchSettings | None = None,
    client: httpx.AsyncClient | None = None,
    raw_object_directory: Path | None = None,
) -> tuple[PublicPlaylistSnapshot, ...]:
    """Fetch a small explicit playlist set sequentially, without a global public crawl."""
    resolved_settings = settings or PlaylistProbeSettings()
    identifiers = tuple(playlist_mbids)
    if len(identifiers) > resolved_settings.maximum_playlists:
        raise ListenBrainzPlaylistProbeError("playlist probe exceeds maximum_playlists")
    if not identifiers:
        raise ListenBrainzPlaylistProbeError(
            "playlist probe needs at least one explicit playlist MBID"
        )
    if len(set(identifiers)) != len(identifiers):
        raise ListenBrainzPlaylistProbeError("playlist probe repeats a playlist MBID")
    snapshots = [
        await fetch_public_playlist_snapshot(
            playlist_mbid,
            settings=fetch_settings,
            probe_settings=resolved_settings,
            client=client,
            raw_object_directory=raw_object_directory,
        )
        for playlist_mbid in identifiers
    ]
    return tuple(snapshots)


def write_public_playlist_snapshot_bundle(
    snapshots: Iterable[PublicPlaylistSnapshot],
    destination: Path,
    *,
    fetch_settings: PublicPlaylistFetchSettings | None = None,
    raw_object_directory: Path,
) -> PublicPlaylistSnapshotBundle:
    """Write a new bundle only when every receipt has its replayable raw object."""
    resolved_snapshots = tuple(snapshots)
    for snapshot in resolved_snapshots:
        _verify_raw_playlist_object(snapshot.receipt, raw_object_directory)
    bundle = PublicPlaylistSnapshotBundle(
        fetch_settings=fetch_settings or PublicPlaylistFetchSettings(),
        snapshots=resolved_snapshots,
    )
    if destination.exists() or destination.is_symlink():
        raise ListenBrainzPlaylistProbeError("playlist snapshot destination already exists")
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, staging_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".staging", dir=destination.parent
    )
    staging = Path(staging_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(bundle.model_dump_json(indent=2).encode())
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(staging, destination)
        except FileExistsError as error:
            raise ListenBrainzPlaylistProbeError(
                "playlist snapshot destination already exists"
            ) from error
    finally:
        staging.unlink(missing_ok=True)
    return bundle


def normalized_recording_pairs(
    snapshot: PublicPlaylistSnapshot,
) -> tuple[PlaylistRecordingPair, ...]:
    """Give every playlist one total vote, regardless of its length.

    Pair expansion intentionally happens only after the bounded snapshot parse.
    Duplicate recordings have already been removed and cannot inflate support.
    """
    recording_ids = tuple(item.recording_mbid for item in snapshot.recordings)
    pair_count = len(recording_ids) * (len(recording_ids) - 1) // 2
    weight = 1.0 / pair_count
    return tuple(
        PlaylistRecordingPair(
            playlist_mbid=snapshot.playlist_mbid,
            left_recording_mbid=left,
            right_recording_mbid=right,
            weight=weight,
        )
        for left, right in combinations(recording_ids, 2)
    )


def assess_exact_catalog_join(
    snapshot: PublicPlaylistSnapshot, catalog_recording_mbids: Iterable[UUID]
) -> PlaylistJoinReadiness:
    """Measure exact UUID joins; do not substitute title or artist-name matching."""
    catalog_ids = frozenset(catalog_recording_mbids)
    source_ids = frozenset(item.recording_mbid for item in snapshot.recordings)
    matched_count = len(source_ids & catalog_ids)
    return PlaylistJoinReadiness(
        playlist_mbid=snapshot.playlist_mbid,
        source_recording_count=len(source_ids),
        exact_catalog_recording_count=matched_count,
        unmatched_recording_count=len(source_ids) - matched_count,
        exact_catalog_join_rate=matched_count / len(source_ids),
    )


def evaluate_public_playlist_probe(
    source_bundle: PublicPlaylistSnapshotBundle,
    catalog_recording_mbids: Iterable[UUID],
    *,
    settings: PlaylistProbeSettings | None = None,
) -> ListenBrainzPlaylistProbeArtifact:
    """Report bounded local evidence readiness without producing genre labels or ranks."""
    resolved_settings = settings or PlaylistProbeSettings()
    resolved_snapshots = source_bundle.snapshots
    if len(resolved_snapshots) > resolved_settings.maximum_playlists:
        raise ListenBrainzPlaylistProbeError("playlist probe exceeds maximum_playlists")
    playlist_ids = tuple(item.playlist_mbid for item in resolved_snapshots)
    if len(set(playlist_ids)) != len(playlist_ids):
        raise ListenBrainzPlaylistProbeError("playlist probe repeats a playlist MBID")
    for snapshot in resolved_snapshots:
        _require_snapshot_within_settings(snapshot, resolved_settings)

    catalog_ids = frozenset(catalog_recording_mbids)
    readiness = tuple(
        assess_exact_catalog_join(snapshot, catalog_ids) for snapshot in resolved_snapshots
    )
    pair_count = sum(_pair_count(snapshot) for snapshot in resolved_snapshots)
    total_weight = float(len(resolved_snapshots))
    unique_recordings = frozenset(
        recording.recording_mbid
        for snapshot in resolved_snapshots
        for recording in snapshot.recordings
    )
    exact_catalog_count = len(unique_recordings & catalog_ids)
    curator_counts = {
        curator_kind: sum(item.curator_kind == curator_kind for item in resolved_snapshots)
        for curator_kind in ("reviewed_human", "known_automated", "unknown")
    }
    return ListenBrainzPlaylistProbeArtifact(
        settings=resolved_settings,
        source_snapshot_bundle_logical_sha256=_canonical_sha256(
            source_bundle.model_dump(mode="json")
        ),
        source_receipt_payload_sha256s=tuple(
            snapshot.receipt.payload_sha256 for snapshot in resolved_snapshots
        ),
        catalog_recording_id_set_sha256=_catalog_recording_id_set_sha256(catalog_ids),
        catalog_recording_id_set_count=len(catalog_ids),
        playlist_count=len(resolved_snapshots),
        reviewed_human_playlist_count=curator_counts["reviewed_human"],
        known_automated_playlist_count=curator_counts["known_automated"],
        unknown_curator_playlist_count=curator_counts["unknown"],
        title_search_candidate_count=sum(
            item.receipt.selection_method == "title_search_candidate" for item in resolved_snapshots
        ),
        unique_recording_count=len(unique_recordings),
        exact_catalog_recording_count=exact_catalog_count,
        exact_catalog_join_rate=(exact_catalog_count / len(unique_recordings))
        if unique_recordings
        else 0.0,
        normalized_pair_count=pair_count,
        normalized_pair_weight_total=total_weight,
        join_readiness=readiness,
    )


def _require_snapshot_within_settings(
    snapshot: PublicPlaylistSnapshot, settings: PlaylistProbeSettings
) -> None:
    """Reject caller-constructed snapshots that exceed the same parse boundary."""
    recording_ids = tuple(recording.recording_mbid for recording in snapshot.recordings)
    if len(recording_ids) > settings.maximum_unique_recordings_per_playlist:
        raise ListenBrainzPlaylistProbeError(
            "playlist snapshot exceeds maximum_unique_recordings_per_playlist"
        )
    if len(set(recording_ids)) != len(recording_ids):
        raise ListenBrainzPlaylistProbeError("playlist snapshot repeats an exact recording MBID")


def _pair_count(snapshot: PublicPlaylistSnapshot) -> int:
    """Count bounded pairs without allocating a model object for each pair."""
    recording_count = len(snapshot.recordings)
    return recording_count * (recording_count - 1) // 2


def _canonical_sha256(value: object) -> str:
    """Hash a canonical local boundary object instead of caller process state."""
    encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()
    return hashlib.sha256(encoded).hexdigest()


def _catalog_recording_id_set_sha256(recording_mbids: frozenset[UUID]) -> str:
    """Bind a result to the exact immutable catalog identity set used for its joins."""
    return hashlib.sha256("\n".join(map(str, sorted(recording_mbids))).encode()).hexdigest()


def _verify_receipt(payload: bytes, receipt: PlaylistSourceReceipt) -> None:
    if len(payload) != receipt.payload_bytes:
        raise ListenBrainzPlaylistProbeError("playlist payload size does not match receipt")
    if hashlib.sha256(payload).hexdigest() != receipt.payload_sha256:
        raise ListenBrainzPlaylistProbeError("playlist payload SHA-256 does not match receipt")


def _write_raw_playlist_object(payload: bytes, raw_object_directory: Path) -> Path:
    """Publish one local raw JSPF object by hash without replacing a prior object."""
    digest = hashlib.sha256(payload).hexdigest()
    destination = raw_object_directory / digest
    raw_object_directory.mkdir(parents=True, exist_ok=True)
    if destination.exists() or destination.is_symlink():
        _verify_raw_playlist_object_bytes(destination, payload, digest)
        return destination
    descriptor, staging_name = tempfile.mkstemp(
        prefix=f".{digest}.", suffix=".staging", dir=raw_object_directory
    )
    staging = Path(staging_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(staging, destination)
        except FileExistsError:
            _verify_raw_playlist_object_bytes(destination, payload, digest)
    finally:
        staging.unlink(missing_ok=True)
    return destination


def _verify_raw_playlist_object(receipt: PlaylistSourceReceipt, raw_object_directory: Path) -> None:
    """Require the exact receipt-bound raw object before a bundle becomes reusable evidence."""
    path = raw_object_directory / receipt.payload_sha256
    if path.is_symlink() or not path.is_file():
        raise ListenBrainzPlaylistProbeError("playlist raw object is missing from local custody")
    payload = path.read_bytes()
    if (
        len(payload) != receipt.payload_bytes
        or hashlib.sha256(payload).hexdigest() != receipt.payload_sha256
    ):
        raise ListenBrainzPlaylistProbeError("playlist raw object does not match its receipt")


def _verify_raw_playlist_object_bytes(path: Path, payload: bytes, digest: str) -> None:
    """Reject a collision instead of silently accepting another file at the content address."""
    if path.is_symlink() or not path.is_file() or path.read_bytes() != payload:
        raise ListenBrainzPlaylistProbeError(
            "existing playlist raw object differs from content hash"
        )
    if hashlib.sha256(payload).hexdigest() != digest:
        raise AssertionError("playlist raw object writer received an inconsistent digest")


def _try_musicbrainz_recording_id(identifier: str) -> UUID | None:
    try:
        return _musicbrainz_id(identifier, expected_kind="recording")
    except ListenBrainzPlaylistProbeError:
        return None


def _musicbrainz_id(identifier: str, *, expected_kind: Literal["playlist", "recording"]) -> UUID:
    parsed = urlparse(identifier)
    if (
        parsed.scheme != "https"
        or parsed.netloc != "musicbrainz.org"
        or parsed.query
        or parsed.fragment
        or parsed.params
    ):
        raise ListenBrainzPlaylistProbeError("playlist identifier is not an exact MusicBrainz URL")
    expected_path = f"/{expected_kind}/"
    if (
        not parsed.path.startswith(expected_path)
        or parsed.path.count("/") != _EXPECTED_MUSICBRAINZ_PATH_SEPARATORS
    ):
        raise ListenBrainzPlaylistProbeError(
            "playlist identifier is not the expected MusicBrainz kind"
        )
    try:
        return UUID(parsed.path.removeprefix(expected_path))
    except ValueError as error:
        raise ListenBrainzPlaylistProbeError(
            "playlist identifier has an invalid MusicBrainz UUID"
        ) from error


async def _fetch_bounded_json(
    client: httpx.AsyncClient, source_url: str, settings: PublicPlaylistFetchSettings
) -> bytes:
    """Read a successful non-redirected JSON response without accepting unbounded bytes."""
    async with client.stream("GET", source_url) as response:
        if str(response.url) != source_url:
            raise ListenBrainzPlaylistProbeError("playlist request was redirected")
        response.raise_for_status()
        content_type = response.headers.get("content-type", "").partition(";")[0].strip()
        if content_type != "application/json":
            raise ListenBrainzPlaylistProbeError("playlist response is not application/json")
        content_length = response.headers.get("content-length")
        if content_length is not None:
            try:
                declared_size = int(content_length)
            except ValueError as error:
                raise ListenBrainzPlaylistProbeError(
                    "playlist response has invalid content-length"
                ) from error
            if declared_size < 0 or declared_size > settings.maximum_response_bytes:
                raise ListenBrainzPlaylistProbeError(
                    "playlist response exceeds maximum_response_bytes"
                )
        chunks: list[bytes] = []
        byte_count = 0
        async for chunk in response.aiter_bytes(_RESPONSE_CHUNK_BYTES):
            byte_count += len(chunk)
            if byte_count > settings.maximum_response_bytes:
                raise ListenBrainzPlaylistProbeError(
                    "playlist response exceeds maximum_response_bytes"
                )
            chunks.append(chunk)
    if not chunks:
        raise ListenBrainzPlaylistProbeError("playlist response is empty")
    return b"".join(chunks)


def _playlist_api_url(playlist_mbid: UUID) -> str:
    """Build the one allowed public endpoint from an exact requested identifier."""
    return f"{_LISTENBRAINZ_API_ORIGIN}{_LISTENBRAINZ_PLAYLIST_PATH_PREFIX}{playlist_mbid}"


def _listenbrainz_playlist_id_from_url(url: HttpUrl) -> UUID | None:
    """Accept only the canonical public endpoint; reject query, fragment, and redirects."""
    parsed = urlparse(str(url))
    if (
        parsed.scheme != "https"
        or parsed.netloc != "api.listenbrainz.org"
        or parsed.query
        or parsed.fragment
        or parsed.params
        or not parsed.path.startswith(_LISTENBRAINZ_PLAYLIST_PATH_PREFIX)
        or parsed.path.count("/") != _EXPECTED_LISTENBRAINZ_PATH_SEPARATORS
    ):
        return None
    try:
        return UUID(parsed.path.removeprefix(_LISTENBRAINZ_PLAYLIST_PATH_PREFIX))
    except ValueError:
        return None
