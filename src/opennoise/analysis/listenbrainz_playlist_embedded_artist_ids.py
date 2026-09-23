"""Measure source-claimed JSPF artist identifiers from a bounded local playlist cache.

The JSPF extension is a source claim, not a verified MusicBrainz artist credit.
This local-only diagnostic deliberately makes no genre, curation, similarity,
human-support, or publication claim and performs no network I/O.
"""

from __future__ import annotations

import hashlib
import stat
from collections import defaultdict
from dataclasses import dataclass
from itertools import combinations
from typing import TYPE_CHECKING, Literal
from urllib.parse import urlparse
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from opennoise.analysis.listenbrainz_playlist_artist_bridge import (
    ListenBrainzPlaylistArtistBridgeArtifact,  # noqa: TC001  # Runtime Pydantic annotation.
)
from opennoise.ingest.listenbrainz.playlists import PublicPlaylistSnapshotBundle
from opennoise.models import FrozenModel
from opennoise.types import Sha256  # noqa: TC001  # Runtime Pydantic annotation.

if TYPE_CHECKING:
    from pathlib import Path

_REVISION = "listenbrainz-playlist-jspf-embedded-artist-identifiers-v1"
_TRACK_EXTENSION_KEY = "https://musicbrainz.org/doc/jspf#track"
_PLAYLIST_EXTENSION_KEY = "https://musicbrainz.org/doc/jspf#playlist"
_MAXIMUM_BUNDLE_BYTES = 2 * 1024 * 1024
_MAXIMUM_RAW_OBJECT_BYTES = 2 * 1024 * 1024
_MAXIMUM_TRACKS_PER_PLAYLIST = 200
_MAXIMUM_ARTIST_IDENTIFIERS_PER_TRACK = 16
_MAXIMUM_CROSS_RECORDING_ARTIST_PAIR_OBSERVATIONS = 1_000_000
_REPEAT_PLAYLIST_FLOOR = 2
_EXPECTED_MUSICBRAINZ_PATH_SEPARATORS = 2


class ListenBrainzPlaylistEmbeddedArtistIdsError(ValueError):
    """Report malformed or receipt-mismatched JSPF custody input."""


class _JspfTrackExtension(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True, extra="ignore")

    artist_identifiers: list[str] = Field(
        default_factory=list, max_length=_MAXIMUM_ARTIST_IDENTIFIERS_PER_TRACK
    )
    added_by: str | None = Field(default=None, max_length=500)
    added_at: str | None = Field(default=None, max_length=500)


class _JspfPlaylistExtension(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True, extra="ignore")

    creator: str | None = Field(default=None, max_length=500)


class _JspfTrack(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True, extra="ignore")

    identifier: str | list[str] = Field(min_length=1, max_length=1_000)
    extension: dict[str, _JspfTrackExtension] = Field(default_factory=dict, max_length=32)


class _JspfPlaylist(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True, extra="ignore")

    track: list[_JspfTrack] = Field(max_length=_MAXIMUM_TRACKS_PER_PLAYLIST)
    extension: dict[str, _JspfPlaylistExtension] = Field(default_factory=dict, max_length=32)


class _JspfEnvelope(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True, extra="ignore")

    playlist: _JspfPlaylist


class PlaylistArtistIdentifierOccurrence(FrozenModel):
    """Exact source-claimed identifiers for one JSPF track occurrence."""

    playlist_mbid: UUID
    recording_mbid: UUID
    ordinal: int = Field(ge=0)
    source_claimed_artist_mbids: tuple[UUID, ...] = Field(min_length=1, max_length=128)

    @model_validator(mode="after")
    def require_unique_claims(self) -> PlaylistArtistIdentifierOccurrence:
        """Reject repeated source identifiers before pair expansion."""
        if len(self.source_claimed_artist_mbids) != len(set(self.source_claimed_artist_mbids)):
            raise ValueError("source-claimed artist identifiers repeat within a track")
        return self


class EmbeddedArtistIdentifierCoverage(FrozenModel):
    """Descriptive source-claim coverage, separated from verified credits."""

    raw_track_occurrence_count: int = Field(ge=0)
    exact_recording_occurrence_count: int = Field(ge=0)
    distinct_recording_count: int = Field(ge=0)
    occurrences_with_nonempty_source_claim_count: int = Field(ge=0)
    syntactically_valid_source_artist_uri_count: int = Field(ge=0)
    invalid_source_artist_uri_count: int = Field(ge=0)
    distinct_source_claimed_artist_id_count: int = Field(ge=0)
    multi_artist_source_claim_occurrence_count: int = Field(ge=0)
    playlist_extension_creator_present_count: int = Field(ge=0)
    source_track_added_by_present_count: int = Field(ge=0)
    source_track_added_at_present_count: int = Field(ge=0)
    source_track_added_by_equal_playlist_extension_creator_count: int = Field(ge=0)
    cross_recording_artist_pair_observation_count: int = Field(ge=0)
    distinct_cross_recording_artist_pair_count: int = Field(ge=0)
    repeat_within_one_account_cohort_pair_count_at_least_two_playlists: int = Field(ge=0)


class ExactBridgeAgreement(FrozenModel):
    """Agreement with retained exact MusicBrainz responses, never a source upgrade."""

    verified_exact_recording_count: int = Field(ge=0)
    verified_recording_with_source_claim_count: int = Field(ge=0)
    exact_artist_id_set_agreement_recording_count: int = Field(ge=0)
    exact_artist_id_set_disagreement_recording_count: int = Field(ge=0)
    ambiguous_source_claim_recording_count: int = Field(ge=0)


class ListenBrainzPlaylistEmbeddedArtistIdsArtifact(FrozenModel):
    """Replayable local receipt for JSPF source claims and cohort-only coappearance."""

    revision: Literal["listenbrainz-playlist-jspf-embedded-artist-identifiers-v1"] = _REVISION
    local_only: Literal[True] = True
    export_allowed: Literal[False] = False
    serving_allowed: Literal[False] = False
    model_input_allowed: Literal[False] = False
    source_documentation_url: Literal["https://musicbrainz.org/doc/jspf"] = (
        "https://musicbrainz.org/doc/jspf"
    )
    source_claim_label: Literal["jspf_embedded_artist_identifier_source_claim"] = (
        "jspf_embedded_artist_identifier_source_claim"
    )
    coappearance_scope: Literal["within_one_account_playlist_cohort_only"] = (
        "within_one_account_playlist_cohort_only"
    )
    source_playlist_bundle_file_sha256: Sha256
    source_raw_object_layout: Literal["raw/sha256/<payload_sha256>"]
    source_payload_sha256s: tuple[Sha256, ...] = Field(min_length=1, max_length=50)
    claims_by_occurrence: tuple[PlaylistArtistIdentifierOccurrence, ...]
    coverage: EmbeddedArtistIdentifierCoverage
    exact_musicbrainz_bridge_agreement: ExactBridgeAgreement | None = None


def measure_embedded_artist_identifiers(
    bundle_file: Path,
    *,
    raw_object_directory: Path,
    exact_musicbrainz_bridge: ListenBrainzPlaylistArtistBridgeArtifact | None = None,
) -> ListenBrainzPlaylistEmbeddedArtistIdsArtifact:
    """Verify raw custody, parse only the JSPF extension, and measure local claims."""
    bundle_bytes = _read_regular_file(bundle_file, _MAXIMUM_BUNDLE_BYTES, "playlist bundle")
    try:
        bundle = PublicPlaylistSnapshotBundle.model_validate_json(bundle_bytes)
    except ValidationError as error:
        raise ListenBrainzPlaylistEmbeddedArtistIdsError("playlist bundle is invalid") from error
    occurrences: list[PlaylistArtistIdentifierOccurrence] = []
    raw_track_count = 0
    exact_recording_occurrence_count = 0
    valid_uri_count = 0
    invalid_uri_count = 0
    playlist_extension_creator_present_count = 0
    source_track_added_by_present_count = 0
    source_track_added_at_present_count = 0
    source_track_added_by_equal_playlist_extension_creator_count = 0
    for snapshot in bundle.snapshots:
        payload = _read_raw_object(
            snapshot.receipt.payload_sha256, snapshot.receipt.payload_bytes, raw_object_directory
        )
        try:
            envelope = _JspfEnvelope.model_validate_json(payload)
        except ValidationError as error:
            raise ListenBrainzPlaylistEmbeddedArtistIdsError(
                "raw JSPF object is invalid"
            ) from error
        raw_track_count += len(envelope.playlist.track)
        playlist_extension = envelope.playlist.extension.get(_PLAYLIST_EXTENSION_KEY)
        playlist_creator = playlist_extension.creator if playlist_extension is not None else None
        playlist_extension_creator_present_count += playlist_creator is not None
        parsed = _parse_playlist_claims(snapshot.playlist_mbid, envelope, playlist_creator)
        occurrences.extend(parsed.occurrences)
        exact_recording_occurrence_count += parsed.exact_recording_occurrence_count
        valid_uri_count += parsed.valid_uri_count
        invalid_uri_count += parsed.invalid_uri_count
        source_track_added_by_present_count += parsed.source_track_added_by_present_count
        source_track_added_at_present_count += parsed.source_track_added_at_present_count
        source_track_added_by_equal_playlist_extension_creator_count += (
            parsed.source_track_added_by_equal_playlist_extension_creator_count
        )
    coverage = _coverage(
        raw_track_count,
        exact_recording_occurrence_count,
        tuple(occurrences),
        valid_uri_count,
        invalid_uri_count,
        playlist_extension_creator_present_count,
        source_track_added_by_present_count,
        source_track_added_at_present_count,
        source_track_added_by_equal_playlist_extension_creator_count,
    )
    agreement = (
        _exact_bridge_agreement(
            tuple(occurrences),
            exact_musicbrainz_bridge,
            source_bundle_file_sha256=hashlib.sha256(bundle_bytes).hexdigest(),
        )
        if exact_musicbrainz_bridge is not None
        else None
    )
    return ListenBrainzPlaylistEmbeddedArtistIdsArtifact(
        source_playlist_bundle_file_sha256=hashlib.sha256(bundle_bytes).hexdigest(),
        source_raw_object_layout=bundle.raw_object_layout,
        source_payload_sha256s=tuple(item.receipt.payload_sha256 for item in bundle.snapshots),
        claims_by_occurrence=tuple(occurrences),
        coverage=coverage,
        exact_musicbrainz_bridge_agreement=agreement,
    )


@dataclass(frozen=True, slots=True)
class _ParsedPlaylistClaims:
    """Internal parsed result that prevents raw dictionaries leaving the boundary."""

    occurrences: tuple[PlaylistArtistIdentifierOccurrence, ...]
    exact_recording_occurrence_count: int
    valid_uri_count: int
    invalid_uri_count: int
    source_track_added_by_present_count: int
    source_track_added_at_present_count: int
    source_track_added_by_equal_playlist_extension_creator_count: int


def _parse_playlist_claims(
    playlist_mbid: UUID, envelope: _JspfEnvelope, playlist_extension_creator: str | None
) -> _ParsedPlaylistClaims:
    occurrences: list[PlaylistArtistIdentifierOccurrence] = []
    exact_recording_occurrence_count = 0
    valid_uri_count = 0
    invalid_uri_count = 0
    source_track_added_by_present_count = 0
    source_track_added_at_present_count = 0
    source_track_added_by_equal_playlist_extension_creator_count = 0
    for ordinal, track in enumerate(envelope.playlist.track):
        recording_mbid = _recording_mbid(track.identifier)
        if recording_mbid is None:
            continue
        exact_recording_occurrence_count += 1
        extension = track.extension.get(_TRACK_EXTENSION_KEY)
        if extension is None:
            continue
        source_track_added_by_present_count += extension.added_by is not None
        source_track_added_at_present_count += extension.added_at is not None
        source_track_added_by_equal_playlist_extension_creator_count += (
            extension.added_by == playlist_extension_creator and extension.added_by is not None
        )
        artist_ids: list[UUID] = []
        for identifier in extension.artist_identifiers:
            artist_mbid = _artist_mbid(identifier)
            if artist_mbid is None:
                invalid_uri_count += 1
                continue
            valid_uri_count += 1
            if artist_mbid not in artist_ids:
                artist_ids.append(artist_mbid)
        if artist_ids:
            occurrences.append(
                PlaylistArtistIdentifierOccurrence(
                    playlist_mbid=playlist_mbid,
                    recording_mbid=recording_mbid,
                    ordinal=ordinal,
                    source_claimed_artist_mbids=tuple(artist_ids),
                )
            )
    return _ParsedPlaylistClaims(
        tuple(occurrences),
        exact_recording_occurrence_count,
        valid_uri_count,
        invalid_uri_count,
        source_track_added_by_present_count,
        source_track_added_at_present_count,
        source_track_added_by_equal_playlist_extension_creator_count,
    )


def _coverage(  # noqa: PLR0913, PLR0917  # Explicit local receipt measurement dimensions.
    raw_track_count: int,
    exact_recording_occurrence_count: int,
    occurrences: tuple[PlaylistArtistIdentifierOccurrence, ...],
    valid_uri_count: int,
    invalid_uri_count: int,
    playlist_extension_creator_present_count: int,
    source_track_added_by_present_count: int,
    source_track_added_at_present_count: int,
    source_track_added_by_equal_playlist_extension_creator_count: int,
) -> EmbeddedArtistIdentifierCoverage:
    by_playlist: dict[UUID, list[PlaylistArtistIdentifierOccurrence]] = defaultdict(list)
    for occurrence in occurrences:
        by_playlist[occurrence.playlist_mbid].append(occurrence)
    pairs_by_playlist: dict[tuple[UUID, UUID], set[UUID]] = defaultdict(set)
    observation_count = 0
    pair_expansion_work_count = 0
    for playlist_mbid, playlist_occurrences in by_playlist.items():
        for left, right in combinations(playlist_occurrences, 2):
            if left.recording_mbid == right.recording_mbid:
                continue
            pair_expansion_work_count += len(left.source_claimed_artist_mbids) * len(
                right.source_claimed_artist_mbids
            )
            if pair_expansion_work_count > _MAXIMUM_CROSS_RECORDING_ARTIST_PAIR_OBSERVATIONS:
                raise ListenBrainzPlaylistEmbeddedArtistIdsError(
                    "source claims exceed cross-recording artist-pair observation boundary"
                )
            for left_artist in left.source_claimed_artist_mbids:
                for right_artist in right.source_claimed_artist_mbids:
                    if left_artist == right_artist:
                        continue
                    pair = (
                        (left_artist, right_artist)
                        if str(left_artist) < str(right_artist)
                        else (right_artist, left_artist)
                    )
                    pairs_by_playlist[pair].add(playlist_mbid)
                    observation_count += 1
    artist_ids = frozenset(
        artist_id
        for occurrence in occurrences
        for artist_id in occurrence.source_claimed_artist_mbids
    )
    return EmbeddedArtistIdentifierCoverage(
        raw_track_occurrence_count=raw_track_count,
        exact_recording_occurrence_count=exact_recording_occurrence_count,
        distinct_recording_count=len({item.recording_mbid for item in occurrences}),
        occurrences_with_nonempty_source_claim_count=len(occurrences),
        syntactically_valid_source_artist_uri_count=valid_uri_count,
        invalid_source_artist_uri_count=invalid_uri_count,
        distinct_source_claimed_artist_id_count=len(artist_ids),
        multi_artist_source_claim_occurrence_count=sum(
            len(item.source_claimed_artist_mbids) > 1 for item in occurrences
        ),
        playlist_extension_creator_present_count=playlist_extension_creator_present_count,
        source_track_added_by_present_count=source_track_added_by_present_count,
        source_track_added_at_present_count=source_track_added_at_present_count,
        source_track_added_by_equal_playlist_extension_creator_count=(
            source_track_added_by_equal_playlist_extension_creator_count
        ),
        cross_recording_artist_pair_observation_count=observation_count,
        distinct_cross_recording_artist_pair_count=len(pairs_by_playlist),
        repeat_within_one_account_cohort_pair_count_at_least_two_playlists=sum(
            len(playlists) >= _REPEAT_PLAYLIST_FLOOR for playlists in pairs_by_playlist.values()
        ),
    )


def _exact_bridge_agreement(
    occurrences: tuple[PlaylistArtistIdentifierOccurrence, ...],
    bridge: ListenBrainzPlaylistArtistBridgeArtifact,
    *,
    source_bundle_file_sha256: Sha256,
) -> ExactBridgeAgreement:
    if bridge.selection_receipt.source_playlist_bundle_file_sha256 != source_bundle_file_sha256:
        raise ListenBrainzPlaylistEmbeddedArtistIdsError(
            "exact MusicBrainz bridge belongs to another playlist bundle"
        )
    source_sets: dict[UUID, set[frozenset[UUID]]] = defaultdict(set)
    for occurrence in occurrences:
        source_sets[occurrence.recording_mbid].add(
            frozenset(occurrence.source_claimed_artist_mbids)
        )
    verified = [item for item in bridge.lookups if item.outcome == "exact_match"]
    comparable = [item for item in verified if item.requested_recording_id in source_sets]
    unambiguous = [
        item for item in comparable if len(source_sets[item.requested_recording_id]) == 1
    ]
    return ExactBridgeAgreement(
        verified_exact_recording_count=len(verified),
        verified_recording_with_source_claim_count=len(comparable),
        exact_artist_id_set_agreement_recording_count=sum(
            next(iter(source_sets[item.requested_recording_id]))
            == frozenset(item.artist_credit_artist_ids)
            for item in unambiguous
        ),
        exact_artist_id_set_disagreement_recording_count=sum(
            next(iter(source_sets[item.requested_recording_id]))
            != frozenset(item.artist_credit_artist_ids)
            for item in unambiguous
        ),
        ambiguous_source_claim_recording_count=len(comparable) - len(unambiguous),
    )


def _read_regular_file(path: Path, maximum_bytes: int, label: str) -> bytes:
    try:
        metadata = path.lstat()
    except OSError as error:
        raise ListenBrainzPlaylistEmbeddedArtistIdsError(f"{label} is missing") from error
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > maximum_bytes:
        raise ListenBrainzPlaylistEmbeddedArtistIdsError(f"{label} exceeds custody boundary")
    payload = path.read_bytes()
    if len(payload) != metadata.st_size:
        raise ListenBrainzPlaylistEmbeddedArtistIdsError(f"{label} changed during read")
    return payload


def _read_raw_object(digest: Sha256, byte_count: int, directory: Path) -> bytes:
    payload = _read_regular_file(directory / digest, _MAXIMUM_RAW_OBJECT_BYTES, "raw JSPF object")
    if len(payload) != byte_count or hashlib.sha256(payload).hexdigest() != digest:
        raise ListenBrainzPlaylistEmbeddedArtistIdsError("raw JSPF object does not match receipt")
    return payload


def _recording_mbid(identifier: str | list[str]) -> UUID | None:
    identifiers = (identifier,) if isinstance(identifier, str) else identifier
    candidates = {
        candidate for value in identifiers if (candidate := _musicbrainz_mbid(value, "recording"))
    }
    return next(iter(candidates)) if len(candidates) == 1 else None


def _artist_mbid(identifier: str) -> UUID | None:
    return _musicbrainz_mbid(identifier, "artist")


def _musicbrainz_mbid(identifier: str, kind: Literal["recording", "artist"]) -> UUID | None:
    parsed = urlparse(identifier)
    if (
        parsed.scheme != "https"
        or parsed.netloc != "musicbrainz.org"
        or parsed.query
        or parsed.fragment
        or parsed.params
        or parsed.path.count("/") != _EXPECTED_MUSICBRAINZ_PATH_SEPARATORS
        or not parsed.path.startswith(f"/{kind}/")
    ):
        return None
    try:
        return UUID(parsed.path.rsplit("/", 1)[-1])
    except ValueError:
        return None
