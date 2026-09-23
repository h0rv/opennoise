"""Local-only follow-up exact-ID audit for a receipt-bound playlist cohort."""

from __future__ import annotations

import asyncio
import hashlib
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal
from uuid import UUID  # noqa: TC003  # Pydantic resolves this annotation at definition.

import httpx
from pydantic import Field, model_validator

from opennoise.analysis.listenbrainz_playlist_artist_bridge import (
    ListenBrainzPlaylistArtistBridgeArtifact,
    PlaylistSelectedRecordingOrder,
    PlaylistSourcePin,
    _read_bounded_bundle,
    _verify_playlist_raw_object,
)
from opennoise.analysis.musicbrainz_recording_coverage import (
    MUSICBRAINZ_API_BASE,
    MUSICBRAINZ_MIN_REQUEST_INTERVAL_SECONDS,
    MusicBrainzRecordingCoverageError,
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


_SELECTION_SIZE = 50
_RETAINED_PRIOR_BRIDGE_FILE_SHA256 = (
    "5bcb50b190685ec6b4d9352ec1426f2f0eec1eb3edd5c45bc1ae675747f52bb7"
)


class ListenBrainzPlaylistArtistFollowupError(RuntimeError):
    """Report an unsafe follow-up selection or lookup audit."""


class PlaylistArtistFollowupSelection(FrozenModel):
    """A deterministic 50-ID selection that cannot repeat the first bridge."""

    revision: Literal["listenbrainz-playlist-artist-followup-selection-v1"] = (
        "listenbrainz-playlist-artist-followup-selection-v1"
    )
    local_only: Literal[True] = True
    export_allowed: Literal[False] = False
    serving_allowed: Literal[False] = False
    evaluation_eligible: Literal[False] = False
    source_playlist_bundle_file_sha256: Sha256
    source_raw_object_layout: Literal["raw/sha256/<payload_sha256>"]
    prior_bridge_file_sha256: Sha256
    prior_selected_recording_ids: tuple[UUID, ...] = Field(min_length=24, max_length=24)
    ordered_playlist_sources: tuple[PlaylistSourcePin, ...] = Field(min_length=1, max_length=50)
    selection_strategy: Literal[
        "playlist_source_order_round_robin_unique_track_order_excluding_prior_bridge"
    ] = "playlist_source_order_round_robin_unique_track_order_excluding_prior_bridge"
    selected_recording_ids: tuple[UUID, ...] = Field(
        min_length=_SELECTION_SIZE, max_length=_SELECTION_SIZE
    )
    selected_recording_order_by_playlist: tuple[PlaylistSelectedRecordingOrder, ...] = Field(
        min_length=1, max_length=50
    )

    @model_validator(mode="after")
    def require_complete_disjoint_selection(self) -> PlaylistArtistFollowupSelection:
        """Pin ordered source coverage and prohibit a prior-bridge repeat."""
        source_ids = tuple(source.playlist_mbid for source in self.ordered_playlist_sources)
        mapped_ids = tuple(item.playlist_mbid for item in self.selected_recording_order_by_playlist)
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("follow-up selection repeats a playlist MBID")
        if mapped_ids != source_ids:
            raise ValueError("follow-up selection does not preserve playlist source order")
        if len(self.prior_selected_recording_ids) != len(set(self.prior_selected_recording_ids)):
            raise ValueError("prior bridge selection repeats a recording MBID")
        if len(self.selected_recording_ids) != len(set(self.selected_recording_ids)):
            raise ValueError("follow-up selection repeats a recording MBID")
        if set(self.selected_recording_ids) & set(self.prior_selected_recording_ids):
            raise ValueError("follow-up selection repeats a prior bridge recording MBID")
        mapped_recordings = frozenset(
            recording_id
            for item in self.selected_recording_order_by_playlist
            for recording_id in item.selected_recording_ids
        )
        if mapped_recordings != frozenset(self.selected_recording_ids):
            raise ValueError("follow-up playlist mapping does not cover selected recording IDs")
        return self


class PlaylistArtistFollowupCoverage(FrozenModel):
    """Exact-ID lookup coverage only; it is not a similarity measurement."""

    requested_recording_count: int = Field(ge=0, le=_SELECTION_SIZE)
    successful_exact_lookup_count: int = Field(ge=0, le=_SELECTION_SIZE)
    artist_credit_present_count: int = Field(ge=0, le=_SELECTION_SIZE)
    multiple_artist_credit_count: int = Field(ge=0, le=_SELECTION_SIZE)
    unique_artist_id_count: int = Field(ge=0)


class ListenBrainzPlaylistArtistFollowupArtifact(FrozenModel):
    """Replayable, local exact recording-to-artist-credit audit result."""

    revision: Literal["listenbrainz-playlist-musicbrainz-artist-followup-v1"] = (
        "listenbrainz-playlist-musicbrainz-artist-followup-v1"
    )
    local_only: Literal[True] = True
    export_allowed: Literal[False] = False
    serving_allowed: Literal[False] = False
    evaluation_eligible: Literal[False] = False
    source_kind: Literal["listenbrainz_playlist_exact_recording_to_musicbrainz_artist_credit"] = (
        "listenbrainz_playlist_exact_recording_to_musicbrainz_artist_credit"
    )
    selection: PlaylistArtistFollowupSelection
    lookups: tuple[RecordingLookupReceipt, ...]
    coverage: PlaylistArtistFollowupCoverage

    @model_validator(mode="after")
    def require_complete_source_order_measurement(
        self,
    ) -> ListenBrainzPlaylistArtistFollowupArtifact:
        """Require completed output to cover every predeclared ID exactly once."""
        if (
            tuple(item.requested_recording_id for item in self.lookups)
            != self.selection.selected_recording_ids
        ):
            raise ValueError("follow-up lookups do not exactly cover the selected recording IDs")
        if self.coverage.requested_recording_count != len(self.lookups):
            raise ValueError("follow-up requested count does not match lookups")
        return self


def make_followup_selection(
    bundle_file: Path,
    *,
    raw_object_directory: Path,
    prior_bridge_file: Path,
    expected_prior_bridge_file_sha256: Sha256 = _RETAINED_PRIOR_BRIDGE_FILE_SHA256,
) -> PlaylistArtistFollowupSelection:
    """Verify both receipts and select 50 new IDs by source-order round robin."""
    bundle_bytes = _read_bounded_bundle(bundle_file)
    try:
        bundle = PublicPlaylistSnapshotBundle.model_validate_json(bundle_bytes)
        bridge_bytes = _read_bounded_bundle(prior_bridge_file)
        prior_bridge = ListenBrainzPlaylistArtistBridgeArtifact.model_validate_json(bridge_bytes)
    except ValueError as error:
        raise ListenBrainzPlaylistArtistFollowupError(
            "follow-up source receipt is invalid"
        ) from error
    prior_bridge_hash = hashlib.sha256(bridge_bytes).hexdigest()
    if prior_bridge_hash != expected_prior_bridge_file_sha256:
        raise ListenBrainzPlaylistArtistFollowupError(
            "prior bridge file SHA-256 does not match the required receipt"
        )
    bundle_hash = hashlib.sha256(bundle_bytes).hexdigest()
    if prior_bridge.selection_receipt.source_playlist_bundle_file_sha256 != bundle_hash:
        raise ListenBrainzPlaylistArtistFollowupError(
            "prior bridge does not bind this playlist bundle"
        )
    for snapshot in bundle.snapshots:
        _verify_playlist_raw_object(
            snapshot.receipt.payload_sha256, snapshot.receipt.payload_bytes, raw_object_directory
        )
    sources = tuple(
        PlaylistSourcePin(
            playlist_mbid=snapshot.playlist_mbid,
            curator_kind=snapshot.curator_kind,
            payload_sha256=snapshot.receipt.payload_sha256,
        )
        for snapshot in bundle.snapshots
    )
    if prior_bridge.selection_receipt.ordered_playlist_sources != sources:
        raise ListenBrainzPlaylistArtistFollowupError(
            "prior bridge playlist source pins do not match this playlist bundle"
        )
    prior_ids = prior_bridge.selection_receipt.selected_recording_ids
    selected = _select_new_recording_ids(bundle, excluded=frozenset(prior_ids))
    selected_set = frozenset(selected)
    return PlaylistArtistFollowupSelection(
        source_playlist_bundle_file_sha256=bundle_hash,
        source_raw_object_layout=bundle.raw_object_layout,
        prior_bridge_file_sha256=prior_bridge_hash,
        prior_selected_recording_ids=prior_ids,
        ordered_playlist_sources=sources,
        selected_recording_ids=selected,
        selected_recording_order_by_playlist=tuple(
            PlaylistSelectedRecordingOrder(
                playlist_mbid=snapshot.playlist_mbid,
                selected_recording_ids=tuple(
                    recording.recording_mbid
                    for recording in snapshot.recordings
                    if recording.recording_mbid in selected_set
                ),
            )
            for snapshot in bundle.snapshots
        ),
    )


def _select_new_recording_ids(
    bundle: PublicPlaylistSnapshotBundle, *, excluded: frozenset[UUID]
) -> tuple[UUID, ...]:
    selected: list[UUID] = []
    seen = set(excluded)
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
    if len(selected) != _SELECTION_SIZE:
        raise ListenBrainzPlaylistArtistFollowupError(
            "playlist bundle has fewer than 50 new exact recording MBIDs "
            "after excluding prior bridge"
        )
    return tuple(selected)


async def measure_followup_artist_credits(  # noqa: PLR0913  # Explicit bounded I/O boundary.
    selection: PlaylistArtistFollowupSelection,
    client: httpx.AsyncClient,
    *,
    user_agent: str,
    response_cache_directory: Path,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> ListenBrainzPlaylistArtistFollowupArtifact:
    """Request the fixed IDs sequentially at the MusicBrainz 1 Hz ceiling."""
    if not user_agent.strip() or "/" not in user_agent or "(" not in user_agent:
        raise ListenBrainzPlaylistArtistFollowupError(
            "MusicBrainz user_agent must include an app version and contact"
        )
    next_request_at = 0.0
    lookups: list[RecordingLookupReceipt] = []
    for recording_id in selection.selected_recording_ids:
        delay = next_request_at - clock()
        if delay > 0:
            await sleep(delay)
        next_request_at = clock() + MUSICBRAINZ_MIN_REQUEST_INTERVAL_SECONDS
        try:
            response = await _fetch_bounded_response(
                client, f"{MUSICBRAINZ_API_BASE}/recording/{recording_id}", user_agent
            )
            response_object = _write_response_object(response_cache_directory, response.content)
        except (httpx.HTTPError, MusicBrainzRecordingCoverageError) as error:
            raise ListenBrainzPlaylistArtistFollowupError(
                f"MusicBrainz exact lookup failed for {recording_id}: {error}"
            ) from error
        lookups.append(
            _receipt_from_response(
                recording_id,
                response,
                fetched_at_utc=datetime.now(UTC),
                response_object=response_object,
            )
        )
    lookup_tuple = tuple(lookups)
    return ListenBrainzPlaylistArtistFollowupArtifact(
        selection=selection,
        lookups=lookup_tuple,
        coverage=_coverage(lookup_tuple),
    )


def replay_followup_artist_credits(
    artifact: ListenBrainzPlaylistArtistFollowupArtifact, cache_directory: Path
) -> ListenBrainzPlaylistArtistFollowupArtifact:
    """Replay captured response custody only; do not re-read the source inputs."""
    replayed: list[RecordingLookupReceipt] = []
    for receipt in artifact.lookups:
        path = cache_directory / "sha256" / f"{receipt.response_object.sha256}.json"
        try:
            content = _read_bounded_response_object(path)
        except MusicBrainzRecordingCoverageError as error:
            raise ListenBrainzPlaylistArtistFollowupError(
                f"MusicBrainz response custody replay failed: {error}"
            ) from error
        if len(content) != receipt.response_object.byte_size:
            raise ListenBrainzPlaylistArtistFollowupError(
                "response custody byte size does not match"
            )
        if hashlib.sha256(content).hexdigest() != receipt.response_object.sha256:
            raise ListenBrainzPlaylistArtistFollowupError("response custody hash does not match")
        replayed.append(
            _receipt_from_response(
                receipt.requested_recording_id,
                httpx.Response(receipt.http_status_code, content=content),
                fetched_at_utc=receipt.fetched_at_utc,
                response_object=receipt.response_object,
            )
        )
    rebuilt = artifact.model_copy(
        update={"lookups": tuple(replayed), "coverage": _coverage(tuple(replayed))}
    )
    if rebuilt != artifact:
        raise ListenBrainzPlaylistArtistFollowupError(
            "offline response replay does not equal receipt"
        )
    return artifact


def _coverage(lookups: tuple[RecordingLookupReceipt, ...]) -> PlaylistArtistFollowupCoverage:
    artist_ids = frozenset(
        artist_id for receipt in lookups for artist_id in receipt.artist_credit_artist_ids
    )
    return PlaylistArtistFollowupCoverage(
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
    )
