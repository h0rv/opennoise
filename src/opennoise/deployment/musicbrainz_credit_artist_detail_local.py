"""Export a local-only artist-detail payload from an already-gated credit asset.

This is deliberately not part of the public static-page exporter.  It is a
small operational integration seam: callers name a non-existing local output
and the artist to inspect.  The renderer replays the source-bound static
discovery identity before exposing any credit metadata, but it neither creates
an approval nor treats its preview as release-ready.
"""

from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from pydantic import Field

from opennoise.deployment.musicbrainz_credit_static_export import (
    MusicBrainzCreditMetadataRow,
    MusicBrainzCreditStaticMetadataPayload,
    _parse_discovery,
)
from opennoise.models import FrozenModel

if TYPE_CHECKING:
    from opennoise.deployment.public_static_discovery_v2 import PublicStaticDiscoveryV2Payload

_REPOSITORY_DIST = Path(__file__).resolve().parents[3] / "dist"


class LocalMusicBrainzCreditArtistDetailError(RuntimeError):
    """Report an unsafe or non-local artist-credit preview request."""


class LocalMusicBrainzCreditArtistDetailPayload(FrozenModel):
    """One source-bound local candidate for a future artist-detail renderer."""

    revision: Literal["musicbrainz-credit-artist-detail-local-v1"] = (
        "musicbrainz-credit-artist-detail-local-v1"
    )
    publication_status: Literal["local_candidate_only_not_authorized_for_publication"] = (
        "local_candidate_only_not_authorized_for_publication"
    )
    scope: Literal["artist_detail_only"] = "artist_detail_only"
    label: Literal["MusicBrainz credit metadata"] = "MusicBrainz credit metadata"
    static_artist_id: str = Field(pattern=r"^artist:[1-9][0-9]*$")
    musicbrainz_artist_id: str = Field(pattern=r"^[0-9a-f-]{36}$")
    static_discovery_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    credit_metadata_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    public_database_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    credit_row_count: int = Field(gt=0)
    rows: tuple[MusicBrainzCreditMetadataRow, ...] = Field(min_length=1)


def export_local_musicbrainz_credit_artist_detail_payload(
    *,
    credit_metadata: Path,
    static_discovery: Path,
    static_artist_id: str,
    local_root: Path,
    output: Path,
) -> tuple[LocalMusicBrainzCreditArtistDetailPayload, str]:
    """Write a no-replace local JSON payload for one exact visible artist.

    `credit_metadata` must have been created by the separate approval-bound
    export gate.  This renderer does not accept a database, an approval, or a
    custody scope, so none of those local inputs can be mistaken for a new
    publication decision.
    """
    metadata_bytes = credit_metadata.read_bytes()
    discovery_bytes = static_discovery.read_bytes()
    metadata_sha256 = _sha256(metadata_bytes)
    discovery_sha256 = _sha256(discovery_bytes)
    try:
        metadata = MusicBrainzCreditStaticMetadataPayload.model_validate_json(metadata_bytes)
        discovery = _parse_discovery(discovery_bytes)
    except (ValueError, OSError) as error:
        raise LocalMusicBrainzCreditArtistDetailError(
            "artist-detail preview inputs are not verified typed static assets"
        ) from error

    visible = _verified_visible_artists(metadata, discovery, discovery_sha256)
    artist_mbid = visible.get(static_artist_id)
    if artist_mbid is None:
        raise LocalMusicBrainzCreditArtistDetailError(
            "requested artist is not a visible exact-MusicBrainz-ID static artist"
        )
    rows = tuple(row for row in metadata.rows if row.static_artist_id == static_artist_id)
    if not rows:
        raise LocalMusicBrainzCreditArtistDetailError(
            "requested artist has no source-bound credit metadata"
        )
    if any(row.musicbrainz_artist_id != artist_mbid for row in rows):
        raise LocalMusicBrainzCreditArtistDetailError(
            "credit metadata artist identity differs from static discovery"
        )
    payload = LocalMusicBrainzCreditArtistDetailPayload(
        static_artist_id=static_artist_id,
        musicbrainz_artist_id=artist_mbid,
        static_discovery_sha256=discovery_sha256,
        credit_metadata_sha256=metadata_sha256,
        public_database_sha256=metadata.public_database_sha256,
        credit_row_count=len(rows),
        rows=rows,
    )
    return payload, _write_no_replace(payload, local_root=local_root, output=output)


def _verified_visible_artists(
    metadata: MusicBrainzCreditStaticMetadataPayload,
    discovery: PublicStaticDiscoveryV2Payload,
    discovery_sha256: str,
) -> dict[str, str]:
    """Recheck all payload accounting and exact static artist identities."""
    if metadata.scope != "artist_detail_only":
        raise LocalMusicBrainzCreditArtistDetailError("credit metadata has the wrong scope")
    if metadata.static_discovery_sha256 != discovery_sha256:
        raise LocalMusicBrainzCreditArtistDetailError(
            "credit metadata is bound to different static discovery bytes"
        )
    if discovery.availability != "ready" or discovery.source is None:
        raise LocalMusicBrainzCreditArtistDetailError("static discovery is not ready")
    if discovery.source.observation_kind != "direct_source_claim":
        raise LocalMusicBrainzCreditArtistDetailError("static discovery lacks direct-source scope")
    if metadata.public_database_sha256 != discovery.source.database_sha256:
        raise LocalMusicBrainzCreditArtistDetailError(
            "credit metadata and static discovery bind different public databases"
        )
    visible: dict[str, str] = {}
    artist_ids_by_mbid: dict[str, str] = {}
    for artist in discovery.artists:
        if artist.musicbrainz_url is None:
            continue
        mbid = artist.musicbrainz_url.removeprefix("https://musicbrainz.org/artist/")
        previous = visible.setdefault(artist.artist_id, mbid)
        previous_artist_id = artist_ids_by_mbid.setdefault(mbid, artist.artist_id)
        if previous != mbid or previous_artist_id != artist.artist_id:
            raise LocalMusicBrainzCreditArtistDetailError(
                "static discovery does not have one-to-one MusicBrainz artist identities"
            )
    if metadata.visible_artist_count != len(visible):
        raise LocalMusicBrainzCreditArtistDetailError(
            "credit metadata visible artist count does not replay static discovery"
        )
    _verify_rows(metadata, visible)
    return visible


def _verify_rows(metadata: MusicBrainzCreditStaticMetadataPayload, visible: dict[str, str]) -> None:
    """Keep each metadata row source-bound without adding display semantics."""
    if (
        metadata.release_row_count != sum(row.entity_kind == "release" for row in metadata.rows)
        or metadata.recording_row_count
        != sum(row.entity_kind == "recording" for row in metadata.rows)
        or metadata.artists_with_credit_rows_count
        != len({row.static_artist_id for row in metadata.rows})
    ):
        raise LocalMusicBrainzCreditArtistDetailError(
            "credit metadata row accounting does not replay"
        )
    expected_order = tuple(
        sorted(
            metadata.rows,
            key=lambda row: (
                row.static_artist_id,
                row.entity_kind,
                row.musicbrainz_entity_id,
                row.credit_record_fingerprint,
                row.credit_artifact_sha256,
            ),
        )
    )
    if metadata.rows != expected_order:
        raise LocalMusicBrainzCreditArtistDetailError("credit metadata rows are not deterministic")
    seen: set[tuple[str, str, str, str, str]] = set()
    for row in metadata.rows:
        if visible.get(row.static_artist_id) != row.musicbrainz_artist_id:
            raise LocalMusicBrainzCreditArtistDetailError(
                "credit metadata row is not an exact static MusicBrainz-ID join"
            )
        key = (
            row.static_artist_id,
            row.entity_kind,
            row.musicbrainz_entity_id,
            row.credit_record_fingerprint,
            row.credit_artifact_sha256,
        )
        if key in seen:
            raise LocalMusicBrainzCreditArtistDetailError("credit metadata repeats a source row")
        seen.add(key)


def _write_no_replace(
    payload: LocalMusicBrainzCreditArtistDetailPayload, *, local_root: Path, output: Path
) -> str:
    """Atomically create one payload below an explicit existing ``.cache`` root."""
    try:
        root = local_root.resolve(strict=True)
    except OSError as error:
        raise LocalMusicBrainzCreditArtistDetailError("local root must already exist") from error
    if root.name != ".cache" or not root.is_dir():
        raise LocalMusicBrainzCreditArtistDetailError(
            "local root must be an existing .cache directory"
        )
    if root.is_relative_to(_REPOSITORY_DIST.resolve(strict=False)):
        raise LocalMusicBrainzCreditArtistDetailError(
            "local root must not be inside this repository's dist"
        )
    resolved_output = output.resolve(strict=False)
    if not resolved_output.is_relative_to(root):
        raise LocalMusicBrainzCreditArtistDetailError(
            "local preview output must stay below local .cache"
        )
    output = resolved_output
    encoded = (payload.model_dump_json() + "\n").encode()
    if output.exists() or output.is_symlink():
        raise LocalMusicBrainzCreditArtistDetailError("local preview output already exists")
    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{output.name}.", suffix=".staging", dir=output.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, output)
        except FileExistsError as error:
            raise LocalMusicBrainzCreditArtistDetailError(
                "local preview output already exists"
            ) from error
        return _sha256(encoded)
    finally:
        temporary.unlink(missing_ok=True)


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()
