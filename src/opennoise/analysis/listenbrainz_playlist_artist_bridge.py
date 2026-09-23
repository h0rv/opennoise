"""Receipt-bound, local-only exact playlist recording-to-artist-credit bridge.

This deliberately bridges only exact MusicBrainz recording UUIDs retained in a
public ListenBrainz playlist bundle to exact MusicBrainz recording responses.
It preserves playlist and track order, does not retain display metadata, and
does not make genre, curation, ranking, catalog-completeness, or serving
claims.
"""

from __future__ import annotations

import asyncio
import hashlib
import stat
import time
from datetime import UTC, datetime
from itertools import combinations
from typing import TYPE_CHECKING, Literal
from uuid import UUID  # noqa: TC003  # Pydantic resolves this annotation at definition.

import httpx
from pydantic import Field, model_validator

from opennoise.analysis.musicbrainz_recording_coverage import (
    MUSICBRAINZ_API_BASE,
    MUSICBRAINZ_MIN_REQUEST_INTERVAL_SECONDS,
    RecordingLookupReceipt,
    _fetch_bounded_response,
    _read_bounded_response_object,
    _receipt_from_response,
    _write_response_object,
)
from opennoise.ingest.listenbrainz.playlists import PublicPlaylistSnapshotBundle
from opennoise.models import FrozenModel
from opennoise.types import (
    Sha256,  # noqa: TC001  # Pydantic resolves this annotation at definition.
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from pathlib import Path


_SELECTION_SIZE = 24
_MAXIMUM_PLAYLIST_BUNDLE_BYTES = 2 * 1024 * 1024


class ListenBrainzPlaylistArtistBridgeError(RuntimeError):
    """Report an unsafe source bundle or failed exact artist-credit bridge."""


class PlaylistSourcePin(FrozenModel):
    """Source-order playlist identity and declared curator state, without names."""

    playlist_mbid: UUID
    curator_kind: Literal["reviewed_human", "known_automated", "unknown"]
    payload_sha256: Sha256


class PlaylistSelectedRecordingOrder(FrozenModel):
    """The selected global IDs as they occur within one source-order playlist."""

    playlist_mbid: UUID
    selected_recording_ids: tuple[UUID, ...]

    @model_validator(mode="after")
    def require_unique_recording_ids(self) -> PlaylistSelectedRecordingOrder:
        """Reject repeated source IDs before they can inflate playlist co-occurrence."""
        if len(self.selected_recording_ids) != len(set(self.selected_recording_ids)):
            raise ValueError("playlist selection mapping repeats a recording MBID")
        return self


class PlaylistRecordingSelectionReceipt(FrozenModel):
    """Pin the immutable playlist bundle and its deterministic 24-recording prefix."""

    revision: Literal["listenbrainz-playlist-recording-selection-v1"] = (
        "listenbrainz-playlist-recording-selection-v1"
    )
    local_only: Literal[True] = True
    export_allowed: Literal[False] = False
    serving_allowed: Literal[False] = False
    source_playlist_bundle_file_sha256: Sha256
    source_raw_object_layout: Literal["raw/sha256/<payload_sha256>"]
    ordered_playlist_sources: tuple[PlaylistSourcePin, ...] = Field(min_length=1, max_length=50)
    selection_strategy: Literal["playlist_source_order_round_robin_unique_track_order"] = (
        "playlist_source_order_round_robin_unique_track_order"
    )
    selected_recording_ids: tuple[UUID, ...] = Field(
        min_length=_SELECTION_SIZE, max_length=_SELECTION_SIZE
    )
    selected_recording_order_by_playlist: tuple[PlaylistSelectedRecordingOrder, ...] = Field(
        min_length=1, max_length=50
    )

    @model_validator(mode="after")
    def require_unique_source_and_selected_ids(self) -> PlaylistRecordingSelectionReceipt:
        """Make the selection unambiguous even if a caller constructs this model."""
        playlist_ids = tuple(source.playlist_mbid for source in self.ordered_playlist_sources)
        if len(playlist_ids) != len(set(playlist_ids)):
            raise ValueError("playlist selection receipt repeats a playlist MBID")
        if len(self.selected_recording_ids) != len(set(self.selected_recording_ids)):
            raise ValueError("playlist selection receipt repeats a recording MBID")
        mapped_playlist_ids = tuple(
            item.playlist_mbid for item in self.selected_recording_order_by_playlist
        )
        if mapped_playlist_ids != playlist_ids:
            raise ValueError("playlist selection mapping does not preserve source playlist order")
        mapped_ids = frozenset(
            recording_id
            for item in self.selected_recording_order_by_playlist
            for recording_id in item.selected_recording_ids
        )
        if mapped_ids != frozenset(self.selected_recording_ids):
            raise ValueError("playlist selection mapping does not cover selected recording IDs")
        return self


class PlaylistArtistBridgeCoverage(FrozenModel):
    """Exact coverage and co-credit pair potential, never a similarity or genre result."""

    requested_recording_count: int = Field(ge=0, le=_SELECTION_SIZE)
    successful_exact_lookup_count: int = Field(ge=0, le=_SELECTION_SIZE)
    artist_credit_present_count: int = Field(ge=0, le=_SELECTION_SIZE)
    multiple_artist_credit_count: int = Field(ge=0, le=_SELECTION_SIZE)
    unique_artist_id_count: int = Field(ge=0)
    cross_recording_artist_pair_observation_count: int = Field(ge=0)
    unique_cross_recording_artist_pair_potential_count: int = Field(ge=0)


class ListenBrainzPlaylistArtistBridgeArtifact(FrozenModel):
    """A replayable exact-ID bridge with raw MusicBrainz bodies held in local custody."""

    revision: Literal["listenbrainz-playlist-musicbrainz-artist-bridge-v1"] = (
        "listenbrainz-playlist-musicbrainz-artist-bridge-v1"
    )
    local_only: Literal[True] = True
    export_allowed: Literal[False] = False
    serving_allowed: Literal[False] = False
    source_kind: Literal["listenbrainz_playlist_exact_recording_to_musicbrainz_artist_credit"] = (
        "listenbrainz_playlist_exact_recording_to_musicbrainz_artist_credit"
    )
    source_documentation_url: Literal["https://musicbrainz.org/doc/MusicBrainz_API"] = (
        "https://musicbrainz.org/doc/MusicBrainz_API"
    )
    selection_receipt: PlaylistRecordingSelectionReceipt
    lookups: tuple[RecordingLookupReceipt, ...]
    coverage: PlaylistArtistBridgeCoverage

    @model_validator(mode="after")
    def require_complete_source_order_measurement(self) -> ListenBrainzPlaylistArtistBridgeArtifact:
        """Prevent a partial, reordered, or mismatched response collection."""
        if (
            tuple(item.requested_recording_id for item in self.lookups)
            != self.selection_receipt.selected_recording_ids
        ):
            raise ValueError("lookups must exactly cover source-order selected recording IDs")
        if self.coverage.requested_recording_count != len(self.lookups):
            raise ValueError("requested recording count does not match lookups")
        return self


def make_playlist_selection_receipt(
    bundle_file: Path, *, raw_object_directory: Path
) -> PlaylistRecordingSelectionReceipt:
    """Verify a retained bundle and derive its first 24 source-order unique recording IDs."""
    bundle_bytes = _read_bounded_bundle(bundle_file)
    try:
        bundle = PublicPlaylistSnapshotBundle.model_validate_json(bundle_bytes)
    except ValueError as error:
        raise ListenBrainzPlaylistArtistBridgeError(
            "playlist bundle is not a valid snapshot bundle"
        ) from error
    sources: list[PlaylistSourcePin] = []
    seen: set[UUID] = set()
    for snapshot in bundle.snapshots:
        _verify_playlist_raw_object(
            snapshot.receipt.payload_sha256, snapshot.receipt.payload_bytes, raw_object_directory
        )
        sources.append(
            PlaylistSourcePin(
                playlist_mbid=snapshot.playlist_mbid,
                curator_kind=snapshot.curator_kind,
                payload_sha256=snapshot.receipt.payload_sha256,
            )
        )
    selected: list[UUID] = []
    cursors = [0] * len(bundle.snapshots)
    while len(selected) < _SELECTION_SIZE:
        selected_this_round = False
        for index, snapshot in enumerate(bundle.snapshots):
            while cursors[index] < len(snapshot.recordings):
                recording_id = snapshot.recordings[cursors[index]].recording_mbid
                cursors[index] += 1
                if recording_id not in seen:
                    seen.add(recording_id)
                    selected.append(recording_id)
                    selected_this_round = True
                    break
            if len(selected) == _SELECTION_SIZE:
                break
        if not selected_this_round:
            break
    if len(selected) < _SELECTION_SIZE:
        raise ListenBrainzPlaylistArtistBridgeError(
            "playlist bundle has fewer than 24 unique exact recording MBIDs"
        )
    return PlaylistRecordingSelectionReceipt(
        source_playlist_bundle_file_sha256=hashlib.sha256(bundle_bytes).hexdigest(),
        source_raw_object_layout=bundle.raw_object_layout,
        ordered_playlist_sources=tuple(sources),
        selected_recording_ids=tuple(selected[:_SELECTION_SIZE]),
        selected_recording_order_by_playlist=tuple(
            PlaylistSelectedRecordingOrder(
                playlist_mbid=snapshot.playlist_mbid,
                selected_recording_ids=tuple(
                    recording.recording_mbid
                    for recording in snapshot.recordings
                    if recording.recording_mbid in seen
                ),
            )
            for snapshot in bundle.snapshots
        ),
    )


async def measure_playlist_artist_bridge(  # noqa: PLR0913  # Explicit bounded I/O boundary.
    selection_receipt: PlaylistRecordingSelectionReceipt,
    client: httpx.AsyncClient,
    *,
    user_agent: str,
    response_cache_directory: Path,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> ListenBrainzPlaylistArtistBridgeArtifact:
    """Fetch the source-order fixed prefix sequentially at MusicBrainz's 1 Hz ceiling."""
    if not user_agent.strip() or "/" not in user_agent or "(" not in user_agent:
        raise ListenBrainzPlaylistArtistBridgeError(
            "MusicBrainz user_agent must include an app version and contact"
        )
    next_request_at = 0.0
    lookups: list[RecordingLookupReceipt] = []
    for recording_id in selection_receipt.selected_recording_ids:
        delay = next_request_at - clock()
        if delay > 0:
            await sleep(delay)
        next_request_at = clock() + MUSICBRAINZ_MIN_REQUEST_INTERVAL_SECONDS
        endpoint = f"{MUSICBRAINZ_API_BASE}/recording/{recording_id}"
        try:
            response = await _fetch_bounded_response(client, endpoint, user_agent)
        except httpx.HTTPError as error:
            raise ListenBrainzPlaylistArtistBridgeError(
                f"MusicBrainz exact lookup failed for {recording_id}: {type(error).__name__}"
            ) from error
        response_object = _write_response_object(response_cache_directory, response.content)
        lookups.append(
            _receipt_from_response(
                recording_id,
                response,
                fetched_at_utc=datetime.now(UTC),
                response_object=response_object,
            )
        )
    return ListenBrainzPlaylistArtistBridgeArtifact(
        selection_receipt=selection_receipt,
        lookups=tuple(lookups),
        coverage=_coverage(selection_receipt, tuple(lookups)),
    )


def replay_playlist_artist_bridge(
    artifact: ListenBrainzPlaylistArtistBridgeArtifact, cache_directory: Path
) -> ListenBrainzPlaylistArtistBridgeArtifact:
    """Recreate the safe exact-ID projection from every retained raw response offline."""
    replayed: list[RecordingLookupReceipt] = []
    for receipt in artifact.lookups:
        path = cache_directory / "sha256" / f"{receipt.response_object.sha256}.json"
        content = _read_bounded_response_object(path)
        if len(content) != receipt.response_object.byte_size:
            raise ListenBrainzPlaylistArtistBridgeError(
                "response custody object byte size does not match"
            )
        if hashlib.sha256(content).hexdigest() != receipt.response_object.sha256:
            raise ListenBrainzPlaylistArtistBridgeError(
                "response custody object hash does not match"
            )
        replayed.append(
            _receipt_from_response(
                receipt.requested_recording_id,
                httpx.Response(receipt.http_status_code, content=content),
                fetched_at_utc=receipt.fetched_at_utc,
                response_object=receipt.response_object,
            )
        )
    rebuilt = artifact.model_copy(
        update={
            "lookups": tuple(replayed),
            "coverage": _coverage(artifact.selection_receipt, tuple(replayed)),
        }
    )
    if rebuilt != artifact:
        raise ListenBrainzPlaylistArtistBridgeError(
            "offline response replay does not equal receipt"
        )
    return artifact


def _coverage(
    selection_receipt: PlaylistRecordingSelectionReceipt,
    lookups: tuple[RecordingLookupReceipt, ...],
) -> PlaylistArtistBridgeCoverage:
    artist_ids = frozenset(
        artist_id for receipt in lookups for artist_id in receipt.artist_credit_artist_ids
    )
    artists_by_recording = {
        receipt.requested_recording_id: receipt.artist_credit_artist_ids for receipt in lookups
    }
    cross_recording_pairs = tuple(
        tuple(sorted((left_artist, right_artist), key=str))
        for playlist in selection_receipt.selected_recording_order_by_playlist
        for left_recording, right_recording in combinations(playlist.selected_recording_ids, 2)
        for left_artist in artists_by_recording[left_recording]
        for right_artist in artists_by_recording[right_recording]
        if left_artist != right_artist
    )
    return PlaylistArtistBridgeCoverage(
        requested_recording_count=len(lookups),
        successful_exact_lookup_count=sum(receipt.outcome == "exact_match" for receipt in lookups),
        artist_credit_present_count=sum(
            receipt.outcome == "exact_match" and bool(receipt.artist_credit_artist_ids)
            for receipt in lookups
        ),
        multiple_artist_credit_count=sum(
            len(receipt.artist_credit_artist_ids) > 1 for receipt in lookups
        ),
        unique_artist_id_count=len(artist_ids),
        cross_recording_artist_pair_observation_count=len(cross_recording_pairs),
        unique_cross_recording_artist_pair_potential_count=len(frozenset(cross_recording_pairs)),
    )


def _read_bounded_bundle(path: Path) -> bytes:
    try:
        metadata = path.lstat()
    except OSError as error:
        raise ListenBrainzPlaylistArtistBridgeError("playlist bundle is missing") from error
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > _MAXIMUM_PLAYLIST_BUNDLE_BYTES:
        raise ListenBrainzPlaylistArtistBridgeError("playlist bundle exceeds custody boundary")
    try:
        content = path.read_bytes()
    except OSError as error:
        raise ListenBrainzPlaylistArtistBridgeError("playlist bundle cannot be read") from error
    if len(content) != metadata.st_size:
        raise ListenBrainzPlaylistArtistBridgeError("playlist bundle changed during read")
    return content


def _verify_playlist_raw_object(
    payload_sha256: Sha256, payload_bytes: int, directory: Path
) -> None:
    path = directory / payload_sha256
    try:
        metadata = path.lstat()
    except OSError as error:
        raise ListenBrainzPlaylistArtistBridgeError(
            "playlist raw custody object is missing"
        ) from error
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_size != payload_bytes:
        raise ListenBrainzPlaylistArtistBridgeError(
            "playlist raw custody object does not match receipt"
        )
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(64 * 1024), b""):
                digest.update(chunk)
    except OSError as error:
        raise ListenBrainzPlaylistArtistBridgeError(
            "playlist raw custody object cannot be read"
        ) from error
    if digest.hexdigest() != payload_sha256:
        raise ListenBrainzPlaylistArtistBridgeError(
            "playlist raw custody object hash does not match"
        )
