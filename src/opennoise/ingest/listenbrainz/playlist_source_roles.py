"""Classify retained ListenBrainz playlist-listing routes without inferring curation.

Route role is acquisition metadata only. It does not establish that a person
curated a playlist, nor does it alter the local playlist probe's evidence role.
"""

from __future__ import annotations

from typing import Literal
from urllib.parse import urlparse
from uuid import UUID

from pydantic import Field, HttpUrl, model_validator

from opennoise.models import FrozenModel
from opennoise.types import (
    Sha256,  # noqa: TC001  # Pydantic resolves this annotation at definition.
)

_API_ORIGIN = "https://api.listenbrainz.org"
_USER_PLAYLISTS_PREFIX = "/1/user/"

type PlaylistSourceRole = Literal["user_created", "unknown"]
type PlaylistDiscoveryRoute = Literal[
    "user_playlists_created",
    "user_playlists_createdfor",
    "user_playlists_recommendations",
    "direct_playlist_endpoint",
    "unclassified",
]


class ListenBrainzPlaylistSourceRoleError(ValueError):
    """The local route receipt is malformed or outside the supported API boundary."""


class PlaylistDiscoveryRouteReceipt(FrozenModel):
    """One content-addressed playlist-listing or exact-playlist route observation."""

    source_url: HttpUrl
    payload_sha256: Sha256
    payload_bytes: int = Field(gt=0)
    route: PlaylistDiscoveryRoute
    source_role: PlaylistSourceRole
    local_only: Literal[True] = True
    export_allowed: Literal[False] = False
    serving_allowed: Literal[False] = False
    human_curation_established: Literal[False] = False

    @model_validator(mode="after")
    def require_url_matches_declared_route_and_role(self) -> PlaylistDiscoveryRouteReceipt:
        """Bind the non-curation role to the exact official route, not response text."""
        route, role = classify_playlist_discovery_route(self.source_url)
        if (self.route, self.source_role) != (route, role):
            raise ValueError("playlist route receipt does not match official source URL")
        return self


def classify_playlist_discovery_route(
    source_url: HttpUrl,
) -> tuple[PlaylistDiscoveryRoute, PlaylistSourceRole]:
    """Classify only documented/implemented route semantics; all direct IDs stay unknown.

    ``/playlists`` is the server's created-by-user listing route. ``createdfor``
    and recommendations retain their more limited route evidence, but do not
    establish an algorithmic origin, playlist quality, or anything about
    creator text.
    """
    parsed = urlparse(str(source_url))
    if f"{parsed.scheme}://{parsed.netloc}" != _API_ORIGIN:
        raise ListenBrainzPlaylistSourceRoleError("playlist route is not the official API origin")
    path = parsed.path.rstrip("/")
    if path.startswith(_USER_PLAYLISTS_PREFIX):
        match tuple(path[len(_USER_PLAYLISTS_PREFIX) :].split("/")):
            case (str() as user_name, "playlists") if user_name:
                return "user_playlists_created", "user_created"
            case (str() as user_name, "playlists", "createdfor") if user_name:
                return "user_playlists_createdfor", "unknown"
            case (str() as user_name, "playlists", "recommendations") if user_name:
                return "user_playlists_recommendations", "unknown"
    match tuple(path.split("/")):
        case ("", "1", "playlist", str() as playlist_id) if _is_uuid(playlist_id):
            return "direct_playlist_endpoint", "unknown"
    return "unclassified", "unknown"


def make_playlist_discovery_route_receipt(
    source_url: HttpUrl, *, payload_sha256: Sha256, payload_bytes: int
) -> PlaylistDiscoveryRouteReceipt:
    """Parse one bounded raw route observation into a permanently non-curation receipt."""
    route, source_role = classify_playlist_discovery_route(source_url)
    return PlaylistDiscoveryRouteReceipt(
        source_url=source_url,
        payload_sha256=payload_sha256,
        payload_bytes=payload_bytes,
        route=route,
        source_role=source_role,
    )


def _is_uuid(value: str) -> bool:
    try:
        return str(UUID(value)) == value
    except ValueError:
        return False
