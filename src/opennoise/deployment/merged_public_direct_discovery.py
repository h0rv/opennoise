"""Locally compose the sealed discovery asset with its pinned additive sidecar.

This is a review candidate only.  It neither changes the sealed static asset
nor participates in the Pages export.  QID-position records remain explicitly
distinguished from the base asset's exact-label records.  The nested payload
is a distinct local v2 schema; it is not a public v1 compatibility claim.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from pathlib import Path  # noqa: TC003
from typing import Final, Literal

from opennoise.common import canonical_json, sha256_file, sha256_hex
from opennoise.deployment.public_direct_static_discovery import (
    AdditiveMembership,
    SealedQidAdditiveStaticDiscovery,
    sealed_qid_additive_static_discovery_sha256,
)
from opennoise.deployment.static_discovery import (
    StaticDiscoveryArtistOverlapPayload,
    StaticDiscoveryArtistPayload,
    StaticDiscoveryCoveragePayload,
    StaticDiscoveryEvidencePayload,
    StaticDiscoveryMembershipPayload,
    StaticDiscoveryPayload,
    StaticDiscoverySourceCount,
    StaticDiscoverySourcePayload,
    static_discovery_json,
)
from opennoise.models import FrozenModel
from opennoise.types import Sha256  # noqa: TC001

_REVISION: Final = "merged-public-direct-static-discovery-v2"
_LOCAL_DISCOVERY_REVISION: Final = "local-merged-static-discovery-v2"
_RELATED_LIMIT: Final = 8
_ARTIST_ID_PATTERN: Final = re.compile(r"artist:([1-9][0-9]*)\Z")
_SEALED_QID_ADDITIVE_STATIC_DISCOVERY_SHA256: Final = (
    "dfc4c74915ddc72df831a350d3fd420c9b14ff24c1f99e3758b6cdbb8257da73"
)


class MergedPublicDirectDiscoveryError(ValueError):
    """The sealed base and additive sidecar cannot safely form one candidate."""


class LocalMergedDiscoveryMembershipPayload(FrozenModel):
    """One base exact-label or additive QID-position direct membership."""

    node_id: str
    catalog_genre_id: int
    catalog_genre_name: str
    binding: Literal["exact_casefolded_label", "one_to_one_qid_position_binding"]
    evidence: tuple[StaticDiscoveryEvidencePayload, ...]


class LocalMergedDiscoveryArtistPayload(FrozenModel):
    """One local merged artist with recalculated direct-genre peers."""

    artist_id: str
    name: str
    musicbrainz_url: str | None = None
    wikidata_url: str | None = None
    memberships: tuple[LocalMergedDiscoveryMembershipPayload, ...]
    shared_genre_artists: tuple[StaticDiscoveryArtistOverlapPayload, ...]


class LocalMergedDiscoveryGenrePayload(FrozenModel):
    """One local merged genre retaining its explicit binding basis."""

    node_id: str
    catalog_genre_id: int
    catalog_genre_name: str
    binding: Literal["exact_casefolded_label", "one_to_one_qid_position_binding"]
    artist_ids: tuple[str, ...]


class LocalMergedDiscoveryPayload(FrozenModel):
    """The non-publishable complete discovery payload with local v2 semantics."""

    revision: Literal["local-merged-static-discovery-v2"] = _LOCAL_DISCOVERY_REVISION
    availability: Literal["ready"] = "ready"
    source: StaticDiscoverySourcePayload
    coverage: StaticDiscoveryCoveragePayload
    genres: tuple[LocalMergedDiscoveryGenrePayload, ...]
    artists: tuple[LocalMergedDiscoveryArtistPayload, ...]


class MergedPublicDirectDiscoveryCandidate(FrozenModel):
    """A hash-bound, non-publishing complete discovery candidate."""

    revision: Literal["merged-public-direct-static-discovery-v2"] = _REVISION
    publication_scope: Literal["local_candidate_only"] = "local_candidate_only"
    canonical_release_modified: Literal[False] = False
    deployment_performed: Literal[False] = False
    base_static_discovery_sha256: Sha256
    sealed_qid_additive_static_discovery_sha256: Sha256
    sealed_qid_direct_bridge_sha256: Sha256
    public_database_sha256: Sha256
    discovery: LocalMergedDiscoveryPayload
    output_sha256: Sha256


def merged_public_direct_discovery_sha256(
    candidate: MergedPublicDirectDiscoveryCandidate,
) -> Sha256:
    """Hash a candidate independently of its self-reference."""
    return sha256_hex(canonical_json(candidate.model_dump(mode="json", exclude={"output_sha256"})))


def build_merged_public_direct_discovery_candidate(
    *,
    base_static_discovery: Path,
    additive: SealedQidAdditiveStaticDiscovery,
) -> MergedPublicDirectDiscoveryCandidate:
    """Return a complete local candidate only when both pinned inputs replay exactly."""
    base_bytes = _load_exact_base_bytes(base_static_discovery, additive)
    base = StaticDiscoveryPayload.model_validate_json(base_bytes)
    _require_additive(additive, base)
    discovery = _merge(base, additive)
    draft = MergedPublicDirectDiscoveryCandidate(
        base_static_discovery_sha256=additive.base_static_discovery_sha256,
        sealed_qid_additive_static_discovery_sha256=additive.output_sha256,
        sealed_qid_direct_bridge_sha256=additive.sealed_qid_direct_bridge_sha256,
        public_database_sha256=additive.public_database_sha256,
        discovery=discovery,
        output_sha256="0" * 64,
    )
    return draft.model_copy(update={"output_sha256": merged_public_direct_discovery_sha256(draft)})


def merged_public_direct_discovery_json(candidate: MergedPublicDirectDiscoveryCandidate) -> bytes:
    """Serialize a locally reviewable candidate deterministically."""
    return (candidate.model_dump_json(exclude_none=True) + "\n").encode()


def _load_exact_base_bytes(path: Path, additive: SealedQidAdditiveStaticDiscovery) -> bytes:
    try:
        base_bytes = path.read_bytes()
        base = StaticDiscoveryPayload.model_validate_json(base_bytes)
    except (OSError, ValueError) as error:
        raise MergedPublicDirectDiscoveryError("base static discovery is invalid") from error
    actual, _ = sha256_file(path)
    if actual != additive.base_static_discovery_sha256:
        raise MergedPublicDirectDiscoveryError(
            "base static discovery hash does not match additive pin"
        )
    if static_discovery_json(base) != base_bytes:
        raise MergedPublicDirectDiscoveryError("base static discovery bytes do not replay exactly")
    return base_bytes


def _require_additive(
    additive: SealedQidAdditiveStaticDiscovery, base: StaticDiscoveryPayload
) -> None:
    if (
        additive.output_sha256 != sealed_qid_additive_static_discovery_sha256(additive)
        or additive.output_sha256 != _SEALED_QID_ADDITIVE_STATIC_DISCOVERY_SHA256
    ):
        raise MergedPublicDirectDiscoveryError("additive sidecar self-hash does not replay")
    if additive.base != base:
        raise MergedPublicDirectDiscoveryError("additive sidecar embeds a different base payload")
    if base.availability != "ready" or base.source is None or base.coverage is None:
        raise MergedPublicDirectDiscoveryError(
            "base static discovery is not a ready source-bound payload"
        )
    if base.source.database_sha256 != additive.public_database_sha256:
        raise MergedPublicDirectDiscoveryError("base and additive sidecar bind different databases")
    if (
        additive.coverage.base_bound_observation_count
        != base.coverage.bound_direct_observation_count
    ):
        raise MergedPublicDirectDiscoveryError("additive sidecar base observation count drifted")
    if additive.coverage.base_genre_count != len(base.genres):
        raise MergedPublicDirectDiscoveryError("additive sidecar base genre count drifted")
    _require_base_accounting(base)
    _require_additive_accounting(additive)


def _require_base_accounting(base: StaticDiscoveryPayload) -> None:
    source = base.source
    coverage = base.coverage
    if source is None or coverage is None:
        raise MergedPublicDirectDiscoveryError("base static discovery is missing source coverage")
    if len({genre.node_id for genre in base.genres}) != len(base.genres) or len(
        {genre.catalog_genre_id for genre in base.genres}
    ) != len(base.genres):
        raise MergedPublicDirectDiscoveryError("base contains duplicate genres")
    if len({artist.artist_id for artist in base.artists}) != len(base.artists):
        raise MergedPublicDirectDiscoveryError("base contains duplicate artists")
    if len({item.source_key for item in source.sources}) != len(source.sources):
        raise MergedPublicDirectDiscoveryError("base source coverage repeats a source partition")
    evidence = [
        item
        for artist in base.artists
        for membership in artist.memberships
        for item in membership.evidence
    ]
    if len({item.evidence_id for item in evidence}) != len(evidence):
        raise MergedPublicDirectDiscoveryError("base contains duplicate direct evidence")
    if len(evidence) != coverage.bound_direct_observation_count:
        raise MergedPublicDirectDiscoveryError("base observation coverage does not replay")
    if Counter(item.source_key for item in evidence) != {
        item.source_key: item.observation_count for item in source.sources
    }:
        raise MergedPublicDirectDiscoveryError("base source coverage does not replay")


def _require_additive_accounting(additive: SealedQidAdditiveStaticDiscovery) -> None:
    artist_ids = [artist.artist_id for artist in additive.artists]
    genre_nodes = [genre.node_id for genre in additive.genres]
    genre_catalog_ids = [genre.catalog_genre_id for genre in additive.genres]
    memberships = [membership for artist in additive.artists for membership in artist.memberships]
    evidence = [item for membership in memberships for item in membership.evidence]
    if len(set(artist_ids)) != len(artist_ids):
        raise MergedPublicDirectDiscoveryError("additive sidecar contains duplicate artists")
    if len(set(genre_nodes)) != len(genre_nodes) or len(set(genre_catalog_ids)) != len(
        genre_catalog_ids
    ):
        raise MergedPublicDirectDiscoveryError("additive sidecar contains duplicate genres")
    if len(
        {
            (artist.artist_id, membership.node_id)
            for artist in additive.artists
            for membership in artist.memberships
        }
    ) != len(memberships):
        raise MergedPublicDirectDiscoveryError("additive sidecar contains duplicate memberships")
    if len({item.evidence_id for item in evidence}) != len(evidence):
        raise MergedPublicDirectDiscoveryError(
            "additive sidecar contains duplicate direct evidence"
        )
    if len(evidence) != additive.coverage.added_direct_observation_count:
        raise MergedPublicDirectDiscoveryError(
            "additive direct-observation coverage does not replay"
        )
    if len(memberships) != additive.coverage.added_membership_count:
        raise MergedPublicDirectDiscoveryError("additive membership coverage does not replay")
    if len(additive.genres) != additive.coverage.added_genre_count:
        raise MergedPublicDirectDiscoveryError("additive genre coverage does not replay")
    _require_additive_genre_reciprocity(additive)


def _require_additive_genre_reciprocity(additive: SealedQidAdditiveStaticDiscovery) -> None:
    expected_by_genre = {
        genre.node_id: {
            artist.artist_id
            for artist in additive.artists
            for membership in artist.memberships
            if membership.node_id == genre.node_id
        }
        for genre in additive.genres
    }
    genres_by_node = {genre.node_id: genre for genre in additive.genres}
    for genre in additive.genres:
        if set(genre.artist_ids) != expected_by_genre[genre.node_id]:
            raise MergedPublicDirectDiscoveryError(
                "additive genre artists do not replay memberships"
            )
    for artist in additive.artists:
        for membership in artist.memberships:
            genre = genres_by_node.get(membership.node_id)
            if genre is None or (
                membership.catalog_genre_id,
                membership.catalog_genre_name,
                membership.genre_qid,
                membership.binding,
            ) != (
                genre.catalog_genre_id,
                genre.catalog_genre_name,
                genre.genre_qid,
                genre.binding,
            ):
                raise MergedPublicDirectDiscoveryError(
                    "additive membership does not match its positioned genre"
                )


def _merge(
    base: StaticDiscoveryPayload, additive: SealedQidAdditiveStaticDiscovery
) -> LocalMergedDiscoveryPayload:
    source = base.source
    coverage = base.coverage
    if source is None or coverage is None:
        raise MergedPublicDirectDiscoveryError("base static discovery is missing source coverage")
    base_genres = {genre.node_id: genre for genre in base.genres}
    base_catalog_ids = {genre.catalog_genre_id for genre in base.genres}
    if any(
        genre.node_id in base_genres or genre.catalog_genre_id in base_catalog_ids
        for genre in additive.genres
    ):
        raise MergedPublicDirectDiscoveryError("additive genre overlaps the sealed base")
    base_evidence_ids = {
        item.evidence_id
        for artist in base.artists
        for membership in artist.memberships
        for item in membership.evidence
    }
    additive_evidence_ids = {
        item.evidence_id
        for artist in additive.artists
        for membership in artist.memberships
        for item in membership.evidence
    }
    if base_evidence_ids & additive_evidence_ids:
        raise MergedPublicDirectDiscoveryError("additive evidence overlaps the sealed base")

    additive_by_id = {artist.artist_id: artist for artist in additive.artists}
    merged_artists: list[LocalMergedDiscoveryArtistPayload] = []
    for base_artist in base.artists:
        extra = additive_by_id.pop(base_artist.artist_id, None)
        if extra is None:
            merged_artists.append(_local_artist(base_artist))
            continue
        if (
            base_artist.name != extra.name
            or base_artist.musicbrainz_url != extra.musicbrainz_url
            or base_artist.wikidata_url != extra.wikidata_url
        ):
            raise MergedPublicDirectDiscoveryError(
                "overlapping artist presentation identity conflicts"
            )
        merged_artists.append(
            _local_artist(
                base_artist,
                memberships=(
                    *tuple(_local_base_membership(item) for item in base_artist.memberships),
                    *tuple(_local_additive_membership(item) for item in extra.memberships),
                ),
            )
        )
    merged_artists.extend(
        LocalMergedDiscoveryArtistPayload(
            artist_id=artist.artist_id,
            name=artist.name,
            musicbrainz_url=artist.musicbrainz_url,
            wikidata_url=artist.wikidata_url,
            memberships=tuple(_local_additive_membership(item) for item in artist.memberships),
            shared_genre_artists=(),
        )
        for artist in additive_by_id.values()
    )
    _require_merged_memberships(merged_artists)
    related = _related_artists(merged_artists)
    complete_artists = tuple(
        artist.model_copy(update={"shared_genre_artists": related.get(artist.artist_id, ())})
        for artist in sorted(
            merged_artists,
            key=lambda artist: (artist.name.casefold(), _artist_number(artist.artist_id)),
        )
    )
    genres = _genres(base, complete_artists)
    source_counts = Counter(
        item.source_key
        for artist in complete_artists
        for membership in artist.memberships
        for item in membership.evidence
    )
    bound_count = sum(source_counts.values())
    if bound_count > coverage.direct_catalog_observation_count:
        raise MergedPublicDirectDiscoveryError(
            "merged observations exceed catalog direct-observation coverage"
        )
    return LocalMergedDiscoveryPayload(
        source=StaticDiscoverySourcePayload(
            database_sha256=source.database_sha256,
            database_byte_count=source.database_byte_count,
            observation_kind="direct_source_claim",
            sources=tuple(
                StaticDiscoverySourceCount(source_key=key, observation_count=count)
                for key, count in sorted(source_counts.items())
            ),
        ),
        coverage=StaticDiscoveryCoveragePayload(
            placed_map_node_count=coverage.placed_map_node_count,
            exact_label_bound_catalog_genre_count=coverage.exact_label_bound_catalog_genre_count,
            genres_with_direct_artists=len(genres),
            artists_with_direct_map_genres=len(complete_artists),
            direct_catalog_observation_count=coverage.direct_catalog_observation_count,
            bound_direct_observation_count=bound_count,
            artist_relation_method="shared_direct_catalog_genre",
            unserved_colisten_reason="active_display_policy_denies_colisten",
        ),
        genres=genres,
        artists=complete_artists,
    )


def _local_base_membership(
    membership: StaticDiscoveryMembershipPayload,
) -> LocalMergedDiscoveryMembershipPayload:
    """Preserve one exact-label base membership in the separate local schema."""
    return LocalMergedDiscoveryMembershipPayload(
        node_id=membership.node_id,
        catalog_genre_id=membership.catalog_genre_id,
        catalog_genre_name=membership.catalog_genre_name,
        binding="exact_casefolded_label",
        evidence=membership.evidence,
    )


def _local_additive_membership(
    additive_membership: AdditiveMembership,
) -> LocalMergedDiscoveryMembershipPayload:
    """Project a typed QID-position sidecar membership into the local v2 schema."""
    return LocalMergedDiscoveryMembershipPayload(
        node_id=additive_membership.node_id,
        catalog_genre_id=additive_membership.catalog_genre_id,
        catalog_genre_name=additive_membership.catalog_genre_name,
        binding="one_to_one_qid_position_binding",
        evidence=additive_membership.evidence,
    )


def _local_artist(
    artist: StaticDiscoveryArtistPayload,
    memberships: tuple[LocalMergedDiscoveryMembershipPayload, ...] | None = None,
) -> LocalMergedDiscoveryArtistPayload:
    return LocalMergedDiscoveryArtistPayload(
        artist_id=artist.artist_id,
        name=artist.name,
        musicbrainz_url=artist.musicbrainz_url,
        wikidata_url=artist.wikidata_url,
        memberships=(
            tuple(_local_base_membership(item) for item in artist.memberships)
            if memberships is None
            else memberships
        ),
        shared_genre_artists=(),
    )


def _require_merged_memberships(artists: list[LocalMergedDiscoveryArtistPayload]) -> None:
    seen_artist_ids: set[str] = set()
    seen_memberships: set[tuple[str, str]] = set()
    for artist in artists:
        if artist.artist_id in seen_artist_ids:
            raise MergedPublicDirectDiscoveryError("merged payload contains duplicate artists")
        seen_artist_ids.add(artist.artist_id)
        for membership in artist.memberships:
            key = (artist.artist_id, membership.node_id)
            if key in seen_memberships:
                raise MergedPublicDirectDiscoveryError(
                    "merged payload contains duplicate memberships"
                )
            seen_memberships.add(key)


def _genres(
    base: StaticDiscoveryPayload,
    artists: tuple[LocalMergedDiscoveryArtistPayload, ...],
) -> tuple[LocalMergedDiscoveryGenrePayload, ...]:
    grouped: dict[
        str, list[tuple[LocalMergedDiscoveryArtistPayload, LocalMergedDiscoveryMembershipPayload]]
    ] = defaultdict(list)
    for artist in artists:
        for membership in artist.memberships:
            grouped[membership.node_id].append((artist, membership))
    base_genres = {genre.node_id: genre for genre in base.genres}
    result: list[LocalMergedDiscoveryGenrePayload] = []
    catalog_ids: set[int] = set()
    for node_id, rows in sorted(grouped.items()):
        identities = {
            (membership.catalog_genre_id, membership.catalog_genre_name, membership.binding)
            for _, membership in rows
        }
        if len(identities) != 1:
            raise MergedPublicDirectDiscoveryError("merged genre presentation identity conflicts")
        catalog_id, catalog_name, binding = next(iter(identities))
        if catalog_id in catalog_ids:
            raise MergedPublicDirectDiscoveryError(
                "merged payload contains duplicate catalog genres"
            )
        catalog_ids.add(catalog_id)
        base_genre = base_genres.get(node_id)
        if base_genre is not None:
            if (base_genre.catalog_genre_id, base_genre.catalog_genre_name, base_genre.binding) != (
                catalog_id,
                catalog_name,
                binding,
            ) or set(base_genre.artist_ids) != {artist.artist_id for artist, _ in rows}:
                raise MergedPublicDirectDiscoveryError(
                    "base genre record does not replay merged memberships"
                )
            result.append(
                LocalMergedDiscoveryGenrePayload(
                    node_id=base_genre.node_id,
                    catalog_genre_id=base_genre.catalog_genre_id,
                    catalog_genre_name=base_genre.catalog_genre_name,
                    binding="exact_casefolded_label",
                    artist_ids=base_genre.artist_ids,
                )
            )
            continue
        result.append(
            LocalMergedDiscoveryGenrePayload(
                node_id=node_id,
                catalog_genre_id=catalog_id,
                catalog_genre_name=catalog_name,
                binding=binding,
                artist_ids=tuple(sorted(artist.artist_id for artist, _ in rows)),
            )
        )
    if len(result) != len(grouped):
        raise MergedPublicDirectDiscoveryError("merged payload has an unrepresented genre")
    return tuple(result)


def _related_artists(
    artists: list[LocalMergedDiscoveryArtistPayload],
) -> dict[str, tuple[StaticDiscoveryArtistOverlapPayload, ...]]:
    artists_by_genre: dict[str, set[str]] = defaultdict(set)
    genres_by_artist: dict[str, set[str]] = {}
    names = {artist.artist_id: artist.name for artist in artists}
    for artist in artists:
        genre_ids = {membership.node_id for membership in artist.memberships}
        genres_by_artist[artist.artist_id] = genre_ids
        for genre_id in genre_ids:
            artists_by_genre[genre_id].add(artist.artist_id)
    shared: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    for genre_id, artist_ids in artists_by_genre.items():
        ordered = sorted(artist_ids, key=_artist_number)
        for index, artist_id in enumerate(ordered):
            for other_id in ordered[index + 1 :]:
                shared[artist_id][other_id].add(genre_id)
                shared[other_id][artist_id].add(genre_id)
    return {
        artist_id: tuple(
            StaticDiscoveryArtistOverlapPayload(
                artist_id=other_id,
                shared_genre_ids=tuple(sorted(shared_genres)),
                shared_genre_count=len(shared_genres),
                score=_jaccard(genres_by_artist[artist_id], genres_by_artist[other_id]),
                method="shared_direct_catalog_genre",
            )
            for other_id, shared_genres in sorted(
                peers.items(),
                key=lambda item: (
                    -len(item[1]),
                    -_jaccard(genres_by_artist[artist_id], genres_by_artist[item[0]]),
                    names[item[0]].casefold(),
                    _artist_number(item[0]),
                ),
            )[:_RELATED_LIMIT]
        )
        for artist_id, peers in shared.items()
    }


def _artist_number(artist_id: str) -> int:
    match = _ARTIST_ID_PATTERN.fullmatch(artist_id)
    if match is None:
        raise MergedPublicDirectDiscoveryError("artist identity is not a stable catalog key")
    return int(match.group(1))


def _jaccard(left: set[str], right: set[str]) -> float:
    return len(left & right) / len(left | right)
