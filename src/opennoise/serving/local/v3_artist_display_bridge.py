"""Read-only identity and display bridge for the pinned local v3 candidate.

This audit admits an artist only when the v3 direct-profile MusicBrainz ID
matches exactly one artist in the pinned, display-authorized static discovery
payload.  It intentionally does not use artist names to resolve identity, and
it cannot write a candidate, map, static payload, or public artifact.
"""

from __future__ import annotations

import hashlib
import sqlite3
from collections import Counter
from contextlib import closing
from pathlib import Path  # noqa: TC003
from typing import Final, Literal, Protocol

from pydantic import Field, model_validator

from opennoise.deployment.static_discovery import StaticDiscoveryPayload
from opennoise.ml.public_graph import public_model_output_sha256
from opennoise.models import FrozenModel
from opennoise.models.modeling import PublicModelArtifact
from opennoise.pipeline.candidate_public_projection import CandidatePublicProjectionV3Report
from opennoise.types import Sha256  # noqa: TC001

_REVISION: Final = "phase3-v3-local-artist-display-bridge-v1"
_V3_RECEIPT_FILE_SHA256: Final = "3bd6adb0d213a4e95ed06e78426f47e85b7ac20e3e0b662de7ee1097140008af"
_V3_MODEL_FILE_SHA256: Final = "c430b9948b863404827dd346fed6324a38b650ab2a827608078fc145b79fd1ba"
_V3_SERVING_DATABASE_SHA256: Final = (
    "1fca548fa214aae999f7b2462fd2ebf3e265a7f5195a3d6d76b5393f06bd8df9"
)
_V3_MANIFEST_SHA256: Final = "795992807586432e2b285e2ddca9a24a00a16e9fc83b6c382a3e914539333232"
_V3_CANDIDATE_SHA256: Final = "327bbf377cb9ad8a1ed48821718979606622175f255ece5958d674146aba6763"
_V3_BINDING_SHA256: Final = "ddaf45593ad78a6c6535691bf499c003d86e36227dd1bceb3e97e60dfae9d6a6"
_V3_SOURCE_SET_SHA256: Final = "5faa89fb81d69de534b985fb15b4d35cd3402191e4048569540a95778ac34f0a"
_STATIC_DISCOVERY_SHA256: Final = "b4ff2b1bcebb0bb6b1fd63b78caf9a416dbf5bb0c3050c0fa05e434fd0c700e8"
_STATIC_PUBLIC_DATABASE_SHA256: Final = (
    "240047cabddbbebccd48a775c9967488dd2dd2968d38d27f31354b90f3a3e8fc"
)
_MBID_PREFIX: Final = "musicbrainz:artist:"
_MBID_URL_PREFIX: Final = "https://musicbrainz.org/artist/"
_MBID_LENGTH: Final = 36


class V3ArtistDisplayBridgeError(ValueError):
    """The local identity/display bridge is altered, incomplete, or ambiguous."""


class V3ArtistDisplayBridgeInputs(FrozenModel):
    """Only the four read-only, pinned boundaries required by this audit."""

    v3_receipt: Path
    v3_model: Path
    v3_serving_database: Path
    static_discovery: Path


class _ServingDatabaseReceipt(Protocol):
    """The receipt facets required to open the bounded local SQLite input."""

    @property
    def serving_database_sha256(self) -> str: ...

    @property
    def serving_database_schema_version(self) -> int: ...


class V3ArtistDisplayLink(FrozenModel):
    """One exact identity match with a name already authorized by static discovery."""

    artist_musicbrainz_id: str = Field(
        pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
    )
    static_artist_id: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    v3_direct_profile_membership_count: int = Field(gt=0)
    identity_resolution: Literal["exact_musicbrainz_id"] = "exact_musicbrainz_id"
    display_authorization: Literal["static_discovery_display_authorized"] = (
        "static_discovery_display_authorized"
    )


class V3ArtistDisplayCoverage(FrozenModel):
    """Complete accounting for v3 direct-profile and static-discovery artists."""

    v3_direct_profile_artist_count: int = Field(ge=0)
    v3_direct_profile_membership_count: int = Field(ge=0)
    static_display_artist_count: int = Field(ge=0)
    static_artist_with_exact_musicbrainz_id_count: int = Field(ge=0)
    exact_identity_match_count: int = Field(ge=0)
    display_authorized_match_count: int = Field(ge=0)
    v3_abstained_artist_count: int = Field(ge=0)
    static_unmatched_artist_count: int = Field(ge=0)

    @model_validator(mode="after")
    def require_complete_accounting(self) -> V3ArtistDisplayCoverage:
        """Reject coverage that hides an unmatched or unauthorized artist."""
        if self.v3_direct_profile_artist_count != (
            self.exact_identity_match_count + self.v3_abstained_artist_count
        ):
            raise ValueError("v3 artist coverage does not partition exact matches and abstentions")
        if self.static_artist_with_exact_musicbrainz_id_count != (
            self.exact_identity_match_count + self.static_unmatched_artist_count
        ):
            raise ValueError("static artist coverage does not partition exact matches and absences")
        if self.display_authorized_match_count != self.exact_identity_match_count:
            raise ValueError("every identity match must be display-authorized")
        if self.static_display_artist_count != self.static_artist_with_exact_musicbrainz_id_count:
            raise ValueError("static artists without one exact MusicBrainz ID are not bridgeable")
        return self


class V3ArtistDisplayBridgeAudit(FrozenModel):
    """An in-memory local-only audit, deliberately unsuitable for publication."""

    revision: Literal["phase3-v3-local-artist-display-bridge-v1"] = _REVISION
    publication_scope: Literal["local_research_only"] = "local_research_only"
    export_allowed: Literal[False] = False
    static_output_written: Literal[False] = False
    map_output_written: Literal[False] = False
    historical_inputs_used: Literal[False] = False
    v3_receipt_file_sha256: Sha256
    v3_model_file_sha256: Sha256
    v3_serving_database_sha256: Sha256
    static_discovery_sha256: Sha256
    links: tuple[V3ArtistDisplayLink, ...]
    coverage: V3ArtistDisplayCoverage


def build_local_v3_artist_display_bridge_audit(
    inputs: V3ArtistDisplayBridgeInputs,
) -> V3ArtistDisplayBridgeAudit:
    """Return exact local identity/display links without writing any artifact."""
    receipt = _load_receipt(inputs.v3_receipt)
    _load_model(inputs.v3_model, receipt)
    memberships = _direct_profile_memberships(inputs.v3_serving_database, receipt)
    static_artists = _load_static_artists(inputs.static_discovery)

    matched_ids = tuple(sorted(set(memberships) & set(static_artists)))
    links = tuple(
        V3ArtistDisplayLink(
            artist_musicbrainz_id=artist_id,
            static_artist_id=static_artists[artist_id][0],
            display_name=static_artists[artist_id][1],
            v3_direct_profile_membership_count=memberships[artist_id],
        )
        for artist_id in matched_ids
    )
    coverage = V3ArtistDisplayCoverage(
        v3_direct_profile_artist_count=len(memberships),
        v3_direct_profile_membership_count=sum(memberships.values()),
        static_display_artist_count=len(static_artists),
        static_artist_with_exact_musicbrainz_id_count=len(static_artists),
        exact_identity_match_count=len(links),
        display_authorized_match_count=len(links),
        v3_abstained_artist_count=len(set(memberships) - set(static_artists)),
        static_unmatched_artist_count=len(set(static_artists) - set(memberships)),
    )
    return V3ArtistDisplayBridgeAudit(
        v3_receipt_file_sha256=_file_sha256(inputs.v3_receipt),
        v3_model_file_sha256=_file_sha256(inputs.v3_model),
        v3_serving_database_sha256=_file_sha256(inputs.v3_serving_database),
        static_discovery_sha256=_file_sha256(inputs.static_discovery),
        links=links,
        coverage=coverage,
    )


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
    except OSError as error:
        raise V3ArtistDisplayBridgeError("pinned bridge input cannot be read") from error
    return digest.hexdigest()


def _load_receipt(path: Path) -> CandidatePublicProjectionV3Report:
    if _file_sha256(path) != _V3_RECEIPT_FILE_SHA256:
        raise V3ArtistDisplayBridgeError(
            "v3 projection receipt file hash is not the pinned receipt"
        )
    try:
        receipt = CandidatePublicProjectionV3Report.model_validate_json(path.read_bytes())
    except (OSError, ValueError) as error:
        raise V3ArtistDisplayBridgeError("v3 projection receipt is invalid") from error
    if not receipt.gate.passed:
        raise V3ArtistDisplayBridgeError("v3 projection model gate did not pass")
    if (
        receipt.manifest_sha256,
        receipt.candidate_sha256,
        receipt.historical_candidate_binding_sha256,
        receipt.source_artifact_set_sha256,
    ) != (_V3_MANIFEST_SHA256, _V3_CANDIDATE_SHA256, _V3_BINDING_SHA256, _V3_SOURCE_SET_SHA256):
        raise V3ArtistDisplayBridgeError("v3 receipt is outside the pinned local custody boundary")
    return receipt


def _load_model(path: Path, receipt: CandidatePublicProjectionV3Report) -> None:
    if (
        _file_sha256(path) != _V3_MODEL_FILE_SHA256
        or receipt.model_file_sha256 != _V3_MODEL_FILE_SHA256
    ):
        raise V3ArtistDisplayBridgeError("v3 model file hash does not match its receipt")
    try:
        model = PublicModelArtifact.model_validate_json(path.read_bytes())
    except (OSError, ValueError) as error:
        raise V3ArtistDisplayBridgeError("v3 model identity is invalid") from error
    if (model.input_sha256, model.settings_sha256, model.output_sha256) != (
        receipt.model_input_sha256,
        receipt.model_settings_sha256,
        receipt.model_logical_sha256,
    ) or public_model_output_sha256(model) != model.output_sha256:
        raise V3ArtistDisplayBridgeError("v3 model logical identities do not replay")


def _direct_profile_memberships(path: Path, receipt: _ServingDatabaseReceipt) -> Counter[str]:
    if (
        _file_sha256(path) != _V3_SERVING_DATABASE_SHA256
        or receipt.serving_database_sha256 != _V3_SERVING_DATABASE_SHA256
    ):
        raise V3ArtistDisplayBridgeError("v3 serving database hash does not match its receipt")
    try:
        with closing(sqlite3.connect(f"file:{path.resolve()}?mode=ro&immutable=1", uri=True)) as db:
            integrity = db.execute("PRAGMA integrity_check").fetchone()
            foreign_keys = tuple(db.execute("PRAGMA foreign_key_check"))
            version = db.execute("PRAGMA user_version").fetchone()
            refs = tuple(
                str(row[0])
                for row in db.execute(
                    """SELECT source_artist_ref FROM public_genre_profile_memberships
                       WHERE profile_kind = 'direct' ORDER BY source_artist_ref"""
                )
            )
    except sqlite3.Error as error:
        raise V3ArtistDisplayBridgeError(
            "v3 serving database cannot supply direct artists"
        ) from error
    if (
        integrity != ("ok",)
        or foreign_keys
        or version != (receipt.serving_database_schema_version,)
    ):
        raise V3ArtistDisplayBridgeError(
            "v3 serving database integrity or schema does not match receipt"
        )
    if not refs or any(not _is_musicbrainz_artist_ref(ref) for ref in refs):
        raise V3ArtistDisplayBridgeError(
            "v3 direct profiles contain a non-MusicBrainz artist identity"
        )
    return Counter(ref.removeprefix(_MBID_PREFIX) for ref in refs)


def _load_static_artists(path: Path) -> dict[str, tuple[str, str]]:
    if _file_sha256(path) != _STATIC_DISCOVERY_SHA256:
        raise V3ArtistDisplayBridgeError("static discovery file hash is not the pinned artifact")
    try:
        payload = StaticDiscoveryPayload.model_validate_json(path.read_bytes())
    except (OSError, ValueError) as error:
        raise V3ArtistDisplayBridgeError("static discovery artifact is invalid") from error
    if (
        payload.availability != "ready"
        or payload.source is None
        or payload.coverage is None
        or payload.source.database_sha256 != _STATIC_PUBLIC_DATABASE_SHA256
        or payload.source.observation_kind != "direct_source_claim"
        or payload.coverage.artists_with_direct_map_genres != len(payload.artists)
    ):
        raise V3ArtistDisplayBridgeError(
            "static discovery is not a pinned display-authorized snapshot"
        )
    artists: dict[str, tuple[str, str]] = {}
    static_artist_ids: set[str] = set()
    for artist in payload.artists:
        if (
            artist.musicbrainz_url is None
            or not artist.artist_id.strip()
            or not artist.name.strip()
            or not artist.memberships
        ):
            raise V3ArtistDisplayBridgeError(
                "static discovery artist lacks an exact display bridge"
            )
        artist_id = artist.musicbrainz_url.removeprefix(_MBID_URL_PREFIX)
        if (
            not _is_musicbrainz_artist_id(artist_id)
            or artist_id in artists
            or artist.artist_id in static_artist_ids
        ):
            raise V3ArtistDisplayBridgeError("static discovery artist identity is ambiguous")
        artists[artist_id] = (artist.artist_id, artist.name)
        static_artist_ids.add(artist.artist_id)
    if len(artists) != len(payload.artists):
        raise V3ArtistDisplayBridgeError("static discovery artist identity coverage is incomplete")
    return artists


def _is_musicbrainz_artist_ref(value: str) -> bool:
    return value.startswith(_MBID_PREFIX) and _is_musicbrainz_artist_id(
        value.removeprefix(_MBID_PREFIX)
    )


def _is_musicbrainz_artist_id(value: str) -> bool:
    return (
        len(value) == _MBID_LENGTH
        and value[8] == value[13] == value[18] == value[23] == "-"
        and all(character in "0123456789abcdef" for character in value.replace("-", ""))
    )
