"""Adapt the pinned local merged candidate into the public discovery v2 contract.

The v1 asset remains its own exact-label contract.  This module has no Pages
or deployment integration: it is the typed, fail-closed boundary between the
locally composed candidate and a future public v2 exporter.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path  # noqa: TC003
from typing import Final, Literal

from pydantic import ConfigDict, Field

from opennoise.common import canonical_json, sha256_file, sha256_hex
from opennoise.deployment.merged_public_direct_discovery import (
    MergedPublicDirectDiscoveryCandidate,
    merged_public_direct_discovery_sha256,
)
from opennoise.deployment.static_discovery import (
    StaticDiscoveryArtistOverlapPayload,  # noqa: TC001
    StaticDiscoveryEvidencePayload,  # noqa: TC001
    StaticDiscoverySourcePayload,  # noqa: TC001
)
from opennoise.models import FrozenModel
from opennoise.types import Sha256  # noqa: TC001

_REVISION: Final = "static-direct-discovery-v2"
_BASE_STATIC_DISCOVERY_SHA256: Final = (
    "b4ff2b1bcebb0bb6b1fd63b78caf9a416dbf5bb0c3050c0fa05e434fd0c700e8"
)
_SEALED_QID_ADDITIVE_SHA256: Final = (
    "dfc4c74915ddc72df831a350d3fd420c9b14ff24c1f99e3758b6cdbb8257da73"
)
_SEALED_QID_BRIDGE_SHA256: Final = (
    "c488223b34afcd59596072d4623e3190cfff1941cfdccb4da3e286e7ccebef5b"
)
_PUBLIC_DATABASE_SHA256: Final = "240047cabddbbebccd48a775c9967488dd2dd2968d38d27f31354b90f3a3e8fc"
_MERGED_CANDIDATE_SHA256: Final = "9ee2a464de74e0b681ea347163fda94afa6eb28e3189a4fa4e6d0ee3d708232b"
_SEMANTIC_ATLAS_SHA256: Final = "730bca93300870d35b527f377eb883ae95a3f931aad7e820b013fa592c5bf4ac"
_EXACT_LABEL_GENRE_COUNT: Final = 260
_QID_POSITION_GENRE_COUNT: Final = 84
_GENRE_COUNT: Final = 344
_ARTIST_COUNT: Final = 1126
_BOUND_OBSERVATION_COUNT: Final = 3859


class PublicStaticDiscoveryV2Error(ValueError):
    """The local candidate cannot safely become a public v2 payload."""


class PublicStaticDiscoveryV2Membership(FrozenModel):
    """A direct artist-to-genre relation with its declared binding basis."""

    node_id: str = Field(pattern=r"^item[1-9][0-9]*$")
    catalog_genre_id: int = Field(gt=0)
    catalog_genre_name: str = Field(min_length=1)
    binding: Literal["exact_casefolded_label", "one_to_one_qid_position_binding"]
    evidence: tuple[StaticDiscoveryEvidencePayload, ...] = Field(min_length=1)


class PublicStaticDiscoveryV2Artist(FrozenModel):
    """A stable catalog artist and only its direct public memberships."""

    artist_id: str = Field(pattern=r"^artist:[1-9][0-9]*$")
    name: str = Field(min_length=1)
    musicbrainz_url: str | None = Field(
        default=None,
        pattern=(
            r"^https://musicbrainz\.org/artist/"
            r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
        ),
    )
    wikidata_url: str | None = Field(
        default=None, pattern=r"^https://www\.wikidata\.org/wiki/Q[1-9][0-9]*$"
    )
    memberships: tuple[PublicStaticDiscoveryV2Membership, ...] = Field(min_length=1)
    shared_genre_artists: tuple[StaticDiscoveryArtistOverlapPayload, ...]


class PublicStaticDiscoveryV2Genre(FrozenModel):
    """A placed atlas node and its reciprocal direct artist relations."""

    node_id: str = Field(pattern=r"^item[1-9][0-9]*$")
    catalog_genre_id: int = Field(gt=0)
    catalog_genre_name: str = Field(min_length=1)
    binding: Literal["exact_casefolded_label", "one_to_one_qid_position_binding"]
    artist_ids: tuple[str, ...] = Field(min_length=1)


class PublicStaticDiscoveryV2Coverage(FrozenModel):
    """Replayable coverage split between sealed v1 and QID-position additions."""

    placed_map_node_count: int = Field(gt=0)
    exact_label_bound_catalog_genre_count: int = Field(gt=0)
    one_to_one_qid_position_bound_catalog_genre_count: int = Field(ge=0)
    exact_label_genres_with_direct_artists: int = Field(ge=0)
    one_to_one_qid_position_genres_with_direct_artists: int = Field(ge=0)
    genres_with_direct_artists: int = Field(gt=0)
    artists_with_direct_map_genres: int = Field(gt=0)
    direct_catalog_observation_count: int = Field(gt=0)
    bound_direct_observation_count: int = Field(gt=0)
    artist_relation_method: Literal["shared_direct_catalog_genre"]
    unserved_colisten_reason: Literal["active_display_policy_denies_colisten"]


class PublicStaticDiscoveryV2InputChain(FrozenModel):
    """Pins every reviewed input required to reproduce this public projection."""

    merged_public_direct_discovery_sha256: Sha256
    base_static_discovery_sha256: Sha256
    sealed_qid_additive_static_discovery_sha256: Sha256
    sealed_qid_direct_bridge_sha256: Sha256
    public_database_sha256: Sha256
    semantic_atlas_sha256: Sha256


class PublicStaticDiscoveryV2Payload(FrozenModel):
    """The future public v2 JSON schema, separate from unchanged v1 bytes."""

    revision: Literal["static-direct-discovery-v2"] = _REVISION
    availability: Literal["ready"] = "ready"
    input_chain: PublicStaticDiscoveryV2InputChain
    source: StaticDiscoverySourcePayload
    coverage: PublicStaticDiscoveryV2Coverage
    genres: tuple[PublicStaticDiscoveryV2Genre, ...]
    artists: tuple[PublicStaticDiscoveryV2Artist, ...]
    output_sha256: Sha256


class _AtlasNode(FrozenModel):
    """The only atlas field needed to certify discovery node references."""

    node_id: str = Field(validation_alias="id", pattern=r"^item[1-9][0-9]*$")


class _AtlasPayload(FrozenModel):
    """Strictly parse the atlas node list while ignoring unrelated renderer data."""

    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)

    nodes: tuple[_AtlasNode, ...] = Field(min_length=1)


def public_static_discovery_v2_sha256(payload: PublicStaticDiscoveryV2Payload) -> Sha256:
    """Hash the public payload independently from its self-hash field."""
    return sha256_hex(canonical_json(payload.model_dump(mode="json", exclude={"output_sha256"})))


def public_static_discovery_v2_json(payload: PublicStaticDiscoveryV2Payload) -> bytes:
    """Serialize one validated v2 payload deterministically."""
    verify_public_static_discovery_v2_payload(
        payload, frozenset(genre.node_id for genre in payload.genres)
    )
    return (payload.model_dump_json(exclude_none=True) + "\n").encode()


def adapt_public_static_discovery_v2(
    *, candidate: MergedPublicDirectDiscoveryCandidate, semantic_atlas: Path
) -> PublicStaticDiscoveryV2Payload:
    """Project the exact clean local chain into a self-hashed public v2 payload."""
    _require_pinned_candidate(candidate)
    atlas_node_ids = _load_pinned_atlas_nodes(semantic_atlas)
    payload = _payload_from_candidate(candidate)
    verify_public_static_discovery_v2_payload(payload, atlas_node_ids)
    return payload


def verify_public_static_discovery_v2_payload(
    payload: PublicStaticDiscoveryV2Payload, atlas_node_ids: frozenset[str]
) -> None:
    """Replay a v2 payload's self-hash, accounting, and supplied atlas membership."""
    _require_payload_replays(payload, atlas_node_ids)


def _require_pinned_candidate(candidate: MergedPublicDirectDiscoveryCandidate) -> None:
    if (
        candidate.output_sha256 != merged_public_direct_discovery_sha256(candidate)
        or candidate.output_sha256 != _MERGED_CANDIDATE_SHA256
    ):
        raise PublicStaticDiscoveryV2Error("merged candidate self-hash does not match pin")
    if (
        candidate.base_static_discovery_sha256 != _BASE_STATIC_DISCOVERY_SHA256
        or candidate.sealed_qid_additive_static_discovery_sha256 != _SEALED_QID_ADDITIVE_SHA256
        or candidate.sealed_qid_direct_bridge_sha256 != _SEALED_QID_BRIDGE_SHA256
        or candidate.public_database_sha256 != _PUBLIC_DATABASE_SHA256
    ):
        raise PublicStaticDiscoveryV2Error("merged candidate clean input chain does not match pin")


def _load_pinned_atlas_nodes(path: Path) -> frozenset[str]:
    try:
        actual, _ = sha256_file(path)
        atlas = _AtlasPayload.model_validate_json(path.read_bytes())
    except (OSError, ValueError) as error:
        raise PublicStaticDiscoveryV2Error("semantic atlas is invalid") from error
    if actual != _SEMANTIC_ATLAS_SHA256:
        raise PublicStaticDiscoveryV2Error("semantic atlas hash does not match pin")
    node_ids = tuple(node.node_id for node in atlas.nodes)
    if len(node_ids) != len(set(node_ids)):
        raise PublicStaticDiscoveryV2Error("semantic atlas repeats a node ID")
    return frozenset(node_ids)


def _payload_from_candidate(
    candidate: MergedPublicDirectDiscoveryCandidate,
) -> PublicStaticDiscoveryV2Payload:
    discovery = candidate.discovery
    genres = tuple(
        PublicStaticDiscoveryV2Genre.model_validate(genre.model_dump())
        for genre in discovery.genres
    )
    artists = tuple(
        PublicStaticDiscoveryV2Artist.model_validate(artist.model_dump())
        for artist in discovery.artists
    )
    exact_genres = sum(genre.binding == "exact_casefolded_label" for genre in genres)
    qid_genres = len(genres) - exact_genres
    coverage = discovery.coverage
    draft = PublicStaticDiscoveryV2Payload(
        input_chain=PublicStaticDiscoveryV2InputChain(
            merged_public_direct_discovery_sha256=candidate.output_sha256,
            base_static_discovery_sha256=candidate.base_static_discovery_sha256,
            sealed_qid_additive_static_discovery_sha256=(
                candidate.sealed_qid_additive_static_discovery_sha256
            ),
            sealed_qid_direct_bridge_sha256=candidate.sealed_qid_direct_bridge_sha256,
            public_database_sha256=candidate.public_database_sha256,
            semantic_atlas_sha256=_SEMANTIC_ATLAS_SHA256,
        ),
        source=discovery.source,
        coverage=PublicStaticDiscoveryV2Coverage(
            placed_map_node_count=coverage.placed_map_node_count,
            exact_label_bound_catalog_genre_count=coverage.exact_label_bound_catalog_genre_count,
            one_to_one_qid_position_bound_catalog_genre_count=qid_genres,
            exact_label_genres_with_direct_artists=exact_genres,
            one_to_one_qid_position_genres_with_direct_artists=qid_genres,
            genres_with_direct_artists=len(genres),
            artists_with_direct_map_genres=len(artists),
            direct_catalog_observation_count=coverage.direct_catalog_observation_count,
            bound_direct_observation_count=coverage.bound_direct_observation_count,
            artist_relation_method=coverage.artist_relation_method,
            unserved_colisten_reason=coverage.unserved_colisten_reason,
        ),
        genres=genres,
        artists=artists,
        output_sha256="0" * 64,
    )
    return draft.model_copy(update={"output_sha256": public_static_discovery_v2_sha256(draft)})


def _require_payload_replays(
    payload: PublicStaticDiscoveryV2Payload, atlas_node_ids: frozenset[str]
) -> None:
    if payload.output_sha256 != public_static_discovery_v2_sha256(payload):
        raise PublicStaticDiscoveryV2Error("public v2 payload self-hash does not replay")
    chain = payload.input_chain
    if chain.semantic_atlas_sha256 != _SEMANTIC_ATLAS_SHA256:
        raise PublicStaticDiscoveryV2Error("public v2 payload atlas chain drifted")
    if len(payload.genres) != len({genre.node_id for genre in payload.genres}) or len(
        payload.genres
    ) != len({genre.catalog_genre_id for genre in payload.genres}):
        raise PublicStaticDiscoveryV2Error("public v2 payload repeats a genre")
    if len(payload.artists) != len({artist.artist_id for artist in payload.artists}):
        raise PublicStaticDiscoveryV2Error("public v2 payload repeats an artist")
    if any(genre.node_id not in atlas_node_ids for genre in payload.genres):
        raise PublicStaticDiscoveryV2Error("public v2 payload references an atlas node outside pin")
    _require_reciprocal_memberships(payload)
    _require_related_artist_targets(payload)
    _require_source_accounting(payload)
    _require_coverage(payload)


def _require_reciprocal_memberships(payload: PublicStaticDiscoveryV2Payload) -> None:
    genres_by_node = {genre.node_id: genre for genre in payload.genres}
    memberships = [
        (artist, membership) for artist in payload.artists for membership in artist.memberships
    ]
    if len(memberships) != len(
        {(artist.artist_id, membership.node_id) for artist, membership in memberships}
    ):
        raise PublicStaticDiscoveryV2Error("public v2 payload repeats an artist genre relation")
    expected_artist_ids = {node_id: set() for node_id in genres_by_node}
    for artist, membership in memberships:
        genre = genres_by_node.get(membership.node_id)
        if genre is None or (
            membership.catalog_genre_id,
            membership.catalog_genre_name,
            membership.binding,
        ) != (genre.catalog_genre_id, genre.catalog_genre_name, genre.binding):
            raise PublicStaticDiscoveryV2Error("artist membership does not replay its genre")
        expected_artist_ids[membership.node_id].add(artist.artist_id)
    for genre in payload.genres:
        if (
            len(genre.artist_ids) != len(set(genre.artist_ids))
            or set(genre.artist_ids) != expected_artist_ids[genre.node_id]
        ):
            raise PublicStaticDiscoveryV2Error(
                "genre artists do not reciprocally replay memberships"
            )


def _require_source_accounting(payload: PublicStaticDiscoveryV2Payload) -> None:
    evidence = [
        item
        for artist in payload.artists
        for membership in artist.memberships
        for item in membership.evidence
    ]
    if len(evidence) != len({item.evidence_id for item in evidence}):
        raise PublicStaticDiscoveryV2Error("public v2 payload repeats direct evidence")
    counts = Counter(item.source_key for item in evidence)
    source_counts = {item.source_key: item.observation_count for item in payload.source.sources}
    if len(source_counts) != len(payload.source.sources) or counts != source_counts:
        raise PublicStaticDiscoveryV2Error("public v2 source accounting does not replay evidence")
    if len(evidence) != payload.coverage.bound_direct_observation_count:
        raise PublicStaticDiscoveryV2Error("public v2 evidence coverage does not replay")


def _require_related_artist_targets(payload: PublicStaticDiscoveryV2Payload) -> None:
    """Require every displayed peer relation to replay two public memberships."""
    memberships_by_artist = {
        artist.artist_id: {membership.node_id for membership in artist.memberships}
        for artist in payload.artists
    }
    for artist in payload.artists:
        seen_peer_ids: set[str] = set()
        artist_genres = memberships_by_artist[artist.artist_id]
        for peer in artist.shared_genre_artists:
            if peer.artist_id == artist.artist_id or peer.artist_id in seen_peer_ids:
                raise PublicStaticDiscoveryV2Error("public v2 payload repeats a related artist")
            seen_peer_ids.add(peer.artist_id)
            peer_genres = memberships_by_artist.get(peer.artist_id)
            if peer_genres is None:
                raise PublicStaticDiscoveryV2Error(
                    "public v2 related artist is outside the stable artist identity set"
                )
            shared_genres = set(peer.shared_genre_ids)
            if (
                len(shared_genres) != len(peer.shared_genre_ids)
                or peer.shared_genre_count != len(shared_genres)
                or shared_genres != artist_genres & peer_genres
                or peer.score != len(shared_genres) / len(artist_genres | peer_genres)
            ):
                raise PublicStaticDiscoveryV2Error(
                    "public v2 related artist does not replay direct memberships"
                )


def _require_coverage(payload: PublicStaticDiscoveryV2Payload) -> None:
    coverage = payload.coverage
    exact_count = sum(genre.binding == "exact_casefolded_label" for genre in payload.genres)
    qid_count = len(payload.genres) - exact_count
    if (
        len(payload.genres) != coverage.genres_with_direct_artists
        or len(payload.artists) != coverage.artists_with_direct_map_genres
        or exact_count != coverage.exact_label_genres_with_direct_artists
        or qid_count != coverage.one_to_one_qid_position_genres_with_direct_artists
        or qid_count != coverage.one_to_one_qid_position_bound_catalog_genre_count
        or coverage.bound_direct_observation_count > coverage.direct_catalog_observation_count
    ):
        raise PublicStaticDiscoveryV2Error("public v2 coverage does not replay")
    if (
        exact_count != _EXACT_LABEL_GENRE_COUNT
        or qid_count != _QID_POSITION_GENRE_COUNT
        or len(payload.genres) != _GENRE_COUNT
        or len(payload.artists) != _ARTIST_COUNT
        or coverage.bound_direct_observation_count != _BOUND_OBSERVATION_COUNT
    ):
        raise PublicStaticDiscoveryV2Error("public v2 pinned coverage drifted")
