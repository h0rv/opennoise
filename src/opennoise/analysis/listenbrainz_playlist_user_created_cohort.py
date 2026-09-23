"""Build a source-bound route-only ListenBrainz user-playlist cohort.

The ListenBrainz ``/user/<name>/playlists`` route establishes only that the
service lists playlists as created by that account.  It does not establish a
human account, manual selection, editorial review, or a genre claim.
"""

from __future__ import annotations

import hashlib
import json
import stat
from typing import TYPE_CHECKING, Literal
from urllib.parse import urlparse
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from opennoise.ingest.listenbrainz.playlist_source_roles import (
    PlaylistDiscoveryRouteReceipt,  # noqa: TC001  # Pydantic resolves this model annotation at runtime.
)
from opennoise.ingest.listenbrainz.playlists import PublicPlaylistSnapshotBundle
from opennoise.models import FrozenModel
from opennoise.types import (
    Sha256,  # noqa: TC001  # Pydantic resolves this model annotation at runtime.
)

if TYPE_CHECKING:
    from pathlib import Path

    from opennoise.analysis.listenbrainz_playlist_artist_bridge import (
        ListenBrainzPlaylistArtistBridgeArtifact,
    )

_MAXIMUM_LISTING_BYTES = 2 * 1024 * 1024
_MAXIMUM_BUNDLE_BYTES = 2 * 1024 * 1024
_MAXIMUM_PLAYLISTS = 50
_LISTENBRAINZ_ORIGIN = "https://listenbrainz.org"
_PLAYLIST_PATH_PREFIX = "/playlist/"
_EXPECTED_PLAYLIST_PATH_SEPARATORS = 2


class ListenBrainzUserCreatedCohortError(ValueError):
    """The local route-only cohort cannot be safely constructed."""


class _BoundaryModel(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True, extra="ignore")


class _ListedPlaylist(_BoundaryModel):
    identifier: str = Field(min_length=1, max_length=1_000)


class _ListingEntry(_BoundaryModel):
    playlist: _ListedPlaylist


class _UserPlaylistListing(_BoundaryModel):
    playlists: list[_ListingEntry] = Field(min_length=1, max_length=_MAXIMUM_PLAYLISTS)


class ListenBrainzUserCreatedPlaylistCohort(FrozenModel):
    """A local cohort whose only curator provenance is the documented route role."""

    revision: Literal["listenbrainz-user-created-playlist-cohort-v1"] = (
        "listenbrainz-user-created-playlist-cohort-v1"
    )
    local_only: Literal[True] = True
    export_allowed: Literal[False] = False
    serving_allowed: Literal[False] = False
    independent_genre_evaluation_eligible: Literal[False] = False
    listing_route_receipt: PlaylistDiscoveryRouteReceipt
    listing_available_playlist_count: int = Field(ge=1, le=_MAXIMUM_PLAYLISTS)
    source_snapshot_bundle_file_sha256: Sha256
    cohort_playlist_mbids: tuple[UUID, ...] = Field(min_length=1, max_length=_MAXIMUM_PLAYLISTS)
    source_role: Literal["user_created"] = "user_created"
    route_establishes: Literal["service_listed_as_created_by_account"] = (
        "service_listed_as_created_by_account"
    )
    human_curation_claim_criterion: Literal[
        "identity_bound_curator_attestation_of_manual_selection"
    ] = "identity_bound_curator_attestation_of_manual_selection"
    human_curation_established: Literal[False] = False
    manual_or_editorial_curation_established: Literal[False] = False
    all_snapshot_curator_kinds: Literal["unknown"] = "unknown"
    artist_bridge_requested_recording_count: int = Field(ge=0)
    artist_bridge_exact_lookup_count: int = Field(ge=0)
    artist_bridge_exact_artist_credit_count: int = Field(ge=0)
    artist_bridge_distinct_artist_pair_potential_count: int = Field(ge=0)

    @model_validator(mode="after")
    def require_route_only_constraints(self) -> ListenBrainzUserCreatedPlaylistCohort:
        """Prevent a route receipt or artist bridge from becoming a human claim."""
        if self.listing_route_receipt.source_role != "user_created":
            raise ValueError("cohort needs the official user-created listing route")
        if self.listing_route_receipt.human_curation_established:
            raise ValueError("route-only receipt cannot establish human curation")
        if len(self.cohort_playlist_mbids) != len(set(self.cohort_playlist_mbids)):
            raise ValueError("cohort repeats a playlist MBID")
        if self.artist_bridge_exact_lookup_count > self.artist_bridge_requested_recording_count:
            raise ValueError("artist bridge exact lookups exceed requests")
        if self.artist_bridge_exact_artist_credit_count > self.artist_bridge_exact_lookup_count:
            raise ValueError("artist-credit lookups exceed exact lookups")
        return self


def build_user_created_playlist_cohort(
    *,
    listing_payload: bytes,
    listing_route_receipt: PlaylistDiscoveryRouteReceipt,
    snapshot_bundle_bytes: bytes,
    raw_object_directory: Path,
    artist_bridge: ListenBrainzPlaylistArtistBridgeArtifact,
) -> ListenBrainzUserCreatedPlaylistCohort:
    """Bind a retained user-playlist listing to exact playlist snapshots and bridge coverage."""
    _verify_payload(listing_payload, listing_route_receipt)
    listed_playlist_ids = _parse_listing_playlist_ids(listing_payload)
    bundle = _parse_bundle(snapshot_bundle_bytes)
    _verify_bundle_raw_objects(bundle, raw_object_directory)
    cohort_playlist_ids = tuple(snapshot.playlist_mbid for snapshot in bundle.snapshots)
    if len(cohort_playlist_ids) != len(set(cohort_playlist_ids)):
        raise ListenBrainzUserCreatedCohortError("snapshot bundle repeats a playlist MBID")
    if not set(cohort_playlist_ids) <= set(listed_playlist_ids):
        raise ListenBrainzUserCreatedCohortError("snapshot playlist is absent from listing receipt")
    if any(snapshot.curator_kind != "unknown" for snapshot in bundle.snapshots):
        raise ListenBrainzUserCreatedCohortError(
            "route-only cohort requires unknown curator snapshots"
        )
    bundle_sha256 = hashlib.sha256(snapshot_bundle_bytes).hexdigest()
    _verify_artist_bridge(artist_bridge, bundle_sha256, cohort_playlist_ids)
    coverage = artist_bridge.coverage
    return ListenBrainzUserCreatedPlaylistCohort(
        listing_route_receipt=listing_route_receipt,
        listing_available_playlist_count=len(listed_playlist_ids),
        source_snapshot_bundle_file_sha256=bundle_sha256,
        cohort_playlist_mbids=cohort_playlist_ids,
        artist_bridge_requested_recording_count=coverage.requested_recording_count,
        artist_bridge_exact_lookup_count=coverage.successful_exact_lookup_count,
        artist_bridge_exact_artist_credit_count=coverage.artist_credit_present_count,
        artist_bridge_distinct_artist_pair_potential_count=(
            coverage.unique_cross_recording_artist_pair_potential_count
        ),
    )


def _verify_payload(payload: bytes, receipt: PlaylistDiscoveryRouteReceipt) -> None:
    if len(payload) > _MAXIMUM_LISTING_BYTES:
        raise ListenBrainzUserCreatedCohortError("listing payload exceeds custody boundary")
    if len(payload) != receipt.payload_bytes:
        raise ListenBrainzUserCreatedCohortError("listing payload size differs from receipt")
    if hashlib.sha256(payload).hexdigest() != receipt.payload_sha256:
        raise ListenBrainzUserCreatedCohortError("listing payload hash differs from receipt")
    if receipt.source_role != "user_created":
        raise ListenBrainzUserCreatedCohortError("listing route is not user-created")


def _parse_listing_playlist_ids(payload: bytes) -> tuple[UUID, ...]:
    try:
        raw_listing: object = json.loads(payload)
        listing = _UserPlaylistListing.model_validate(raw_listing)
    except (json.JSONDecodeError, ValidationError) as error:
        raise ListenBrainzUserCreatedCohortError(
            "listing payload is not a bounded playlist listing"
        ) from error
    playlist_ids = tuple(
        _playlist_id_from_web_url(entry.playlist.identifier) for entry in listing.playlists
    )
    if len(playlist_ids) != len(set(playlist_ids)):
        raise ListenBrainzUserCreatedCohortError("listing response repeats a playlist MBID")
    return playlist_ids


def _playlist_id_from_web_url(identifier: str) -> UUID:
    parsed = urlparse(identifier)
    if f"{parsed.scheme}://{parsed.netloc}" != _LISTENBRAINZ_ORIGIN:
        raise ListenBrainzUserCreatedCohortError("listing playlist identifier is not ListenBrainz")
    path = parsed.path.rstrip("/")
    if (
        not path.startswith(_PLAYLIST_PATH_PREFIX)
        or path.count("/") != _EXPECTED_PLAYLIST_PATH_SEPARATORS
    ):
        raise ListenBrainzUserCreatedCohortError("listing playlist identifier has an invalid path")
    try:
        return UUID(path.removeprefix(_PLAYLIST_PATH_PREFIX))
    except ValueError as error:
        raise ListenBrainzUserCreatedCohortError(
            "listing playlist identifier is not a UUID"
        ) from error


def _parse_bundle(snapshot_bundle_bytes: bytes) -> PublicPlaylistSnapshotBundle:
    if len(snapshot_bundle_bytes) > _MAXIMUM_BUNDLE_BYTES:
        raise ListenBrainzUserCreatedCohortError("snapshot bundle exceeds custody boundary")
    try:
        return PublicPlaylistSnapshotBundle.model_validate_json(snapshot_bundle_bytes)
    except ValueError as error:
        raise ListenBrainzUserCreatedCohortError("snapshot bundle is invalid") from error


def _verify_bundle_raw_objects(bundle: PublicPlaylistSnapshotBundle, directory: Path) -> None:
    for snapshot in bundle.snapshots:
        receipt = snapshot.receipt
        path = directory / receipt.payload_sha256
        try:
            metadata = path.lstat()
            payload = path.read_bytes()
        except OSError as error:
            raise ListenBrainzUserCreatedCohortError(
                "snapshot raw custody object is missing"
            ) from error
        if not stat.S_ISREG(metadata.st_mode) or len(payload) != receipt.payload_bytes:
            raise ListenBrainzUserCreatedCohortError(
                "snapshot raw custody object differs from receipt"
            )
        if hashlib.sha256(payload).hexdigest() != receipt.payload_sha256:
            raise ListenBrainzUserCreatedCohortError(
                "snapshot raw custody hash differs from receipt"
            )


def _verify_artist_bridge(
    artist_bridge: ListenBrainzPlaylistArtistBridgeArtifact,
    bundle_sha256: Sha256,
    cohort_playlist_ids: tuple[UUID, ...],
) -> None:
    selection = artist_bridge.selection_receipt
    if selection.source_playlist_bundle_file_sha256 != bundle_sha256:
        raise ListenBrainzUserCreatedCohortError("artist bridge belongs to another snapshot bundle")
    source_ids = tuple(source.playlist_mbid for source in selection.ordered_playlist_sources)
    if source_ids != cohort_playlist_ids:
        raise ListenBrainzUserCreatedCohortError(
            "artist bridge does not cover this exact cohort order"
        )
    if any(source.curator_kind != "unknown" for source in selection.ordered_playlist_sources):
        raise ListenBrainzUserCreatedCohortError("artist bridge has non-route-only curator state")
