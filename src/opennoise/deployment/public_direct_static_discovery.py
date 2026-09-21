"""Compose the pinned public-direct receipt into a local additive discovery asset.

This module intentionally does not alter the sealed v1 discovery asset or the
Pages export.  Its output is a separately hashable sidecar whose base is kept
verbatim and whose additions have their own, truthful QID-position binding.
"""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path  # noqa: TC003
from typing import Final, Literal

from pydantic import Field, model_validator

from opennoise.checkpoints.sealed_qid_direct_bridge import (
    BridgeEvidence,
    SealedQidDirectBridge,
    SealedQidDirectMembership,
    sealed_qid_direct_bridge_sha256,
)
from opennoise.common import canonical_json, sha256_file, sha256_hex
from opennoise.deployment.static_discovery import (
    StaticDiscoveryEvidencePayload,
    StaticDiscoveryPayload,
)
from opennoise.models import FrozenModel
from opennoise.types import Sha256  # noqa: TC001

_REVISION: Final = "sealed-qid-additive-static-discovery-v1"
_PUBLIC_DATABASE_SHA256: Final = "240047cabddbbebccd48a775c9967488dd2dd2968d38d27f31354b90f3a3e8fc"
_STATIC_DISCOVERY_SHA256: Final = "b4ff2b1bcebb0bb6b1fd63b78caf9a416dbf5bb0c3050c0fa05e434fd0c700e8"
_SEALED_QID_BRIDGE_SHA256: Final = (
    "c488223b34afcd59596072d4623e3190cfff1941cfdccb4da3e286e7ccebef5b"
)
_QID_MAP_SHA256: Final = "dd5cf7cf33898a76c1e85e95351e25e7303933f4524e2776097c20fd0d73a449"
_BASE_OBSERVATION_COUNT: Final = 2900
_BASE_GENRE_COUNT: Final = 260
_ADDED_OBSERVATION_COUNT: Final = 959
_ADDED_MEMBERSHIP_COUNT: Final = 862
_ADDED_GENRE_COUNT: Final = 84


class PublicDirectStaticDiscoveryExportError(ValueError):
    """A pinned direct receipt cannot safely compose an additive asset."""


class AdditiveMembership(FrozenModel):
    """A direct P136 observation presented through one QID-position binding."""

    node_id: str = Field(pattern=r"^item[1-9][0-9]*$")
    catalog_genre_id: int = Field(gt=0)
    catalog_genre_name: str = Field(min_length=1)
    genre_qid: str = Field(pattern=r"^Q[1-9][0-9]*$")
    binding: Literal["one_to_one_qid_position_binding"]
    evidence: tuple[StaticDiscoveryEvidencePayload, ...] = Field(min_length=1)


class AdditiveArtist(FrozenModel):
    """A display-authorized artist retained under its stable catalog identity."""

    artist_id: str = Field(pattern=r"^artist:[1-9][0-9]*$")
    name: str = Field(min_length=1)
    musicbrainz_url: str = Field(pattern=r"^https://musicbrainz\.org/artist/[0-9a-f-]{36}$")
    wikidata_url: str = Field(pattern=r"^https://www\.wikidata\.org/wiki/Q[1-9][0-9]*$")
    memberships: tuple[AdditiveMembership, ...] = Field(min_length=1)


class AdditiveGenre(FrozenModel):
    """A newly covered map node with direct P136 artist memberships only."""

    node_id: str = Field(pattern=r"^item[1-9][0-9]*$")
    catalog_genre_id: int = Field(gt=0)
    catalog_genre_name: str = Field(min_length=1)
    genre_qid: str = Field(pattern=r"^Q[1-9][0-9]*$")
    binding: Literal["one_to_one_qid_position_binding"]
    artist_ids: tuple[str, ...] = Field(min_length=1)


class AdditiveCoverage(FrozenModel):
    """Fixed base and delta coverage used by a separate local certifier."""

    base_bound_observation_count: int = _BASE_OBSERVATION_COUNT
    base_genre_count: int = _BASE_GENRE_COUNT
    added_direct_observation_count: int
    added_membership_count: int
    added_genre_count: int

    @model_validator(mode="after")
    def _require_pinned_counts(self) -> AdditiveCoverage:
        if self.model_dump() != {
            "base_bound_observation_count": _BASE_OBSERVATION_COUNT,
            "base_genre_count": _BASE_GENRE_COUNT,
            "added_direct_observation_count": _ADDED_OBSERVATION_COUNT,
            "added_membership_count": _ADDED_MEMBERSHIP_COUNT,
            "added_genre_count": _ADDED_GENRE_COUNT,
        }:
            raise ValueError("additive static discovery coverage drifted")
        return self


class SealedQidAdditiveStaticDiscovery(FrozenModel):
    """Local-only sidecar; it is never a replacement for the sealed v1 asset."""

    revision: Literal["sealed-qid-additive-static-discovery-v1"] = _REVISION
    publication_scope: Literal["local_separately_certifiable_additive_export"] = (
        "local_separately_certifiable_additive_export"
    )
    canonical_release_modified: Literal[False] = False
    deployment_performed: Literal[False] = False
    base_static_discovery_sha256: Sha256
    sealed_qid_direct_bridge_sha256: Sha256
    public_database_sha256: Sha256
    base: StaticDiscoveryPayload
    genres: tuple[AdditiveGenre, ...]
    artists: tuple[AdditiveArtist, ...]
    coverage: AdditiveCoverage
    output_sha256: Sha256


@dataclass(frozen=True, slots=True)
class _Observation:
    evidence_id: int
    artist_catalog_id: int
    artist_name: str
    catalog_genre_id: int
    catalog_genre_name: str
    source_key: str
    source_record_id: str
    provenance_id: int


def sealed_qid_additive_static_discovery_sha256(
    payload: SealedQidAdditiveStaticDiscovery,
) -> Sha256:
    """Hash the local sidecar independently of its self-hash field."""
    return sha256_hex(canonical_json(payload.model_dump(mode="json", exclude={"output_sha256"})))


def build_sealed_qid_additive_static_discovery(
    *,
    database: Path,
    base_static_discovery: Path,
    bridge: SealedQidDirectBridge,
) -> SealedQidAdditiveStaticDiscovery:
    """Return a fail-closed local sidecar from exact pinned base and bridge inputs."""
    base = _load_pinned_base(base_static_discovery)
    _require_pinned_bridge(bridge)
    _require_pinned_database(database, bridge, base)
    observations = _load_observations(database, bridge)
    genres, artists = _additions(bridge, observations, base)
    coverage = AdditiveCoverage(
        added_direct_observation_count=sum(
            len(membership.evidence) for artist in artists for membership in artist.memberships
        ),
        added_membership_count=sum(len(artist.memberships) for artist in artists),
        added_genre_count=len(genres),
    )
    draft = SealedQidAdditiveStaticDiscovery(
        base_static_discovery_sha256=_STATIC_DISCOVERY_SHA256,
        sealed_qid_direct_bridge_sha256=bridge.output_sha256,
        public_database_sha256=_PUBLIC_DATABASE_SHA256,
        base=base,
        genres=genres,
        artists=artists,
        coverage=coverage,
        output_sha256="0" * 64,
    )
    return draft.model_copy(
        update={"output_sha256": sealed_qid_additive_static_discovery_sha256(draft)}
    )


def sealed_qid_additive_static_discovery_json(payload: SealedQidAdditiveStaticDiscovery) -> bytes:
    """Serialize a validated sidecar deterministically for no-replace creation."""
    return (payload.model_dump_json(exclude_none=True) + "\n").encode()


def _load_pinned_base(path: Path) -> StaticDiscoveryPayload:
    actual, _ = sha256_file(path)
    if actual != _STATIC_DISCOVERY_SHA256:
        raise PublicDirectStaticDiscoveryExportError(
            "base static discovery hash does not match pin"
        )
    try:
        base = StaticDiscoveryPayload.model_validate_json(path.read_bytes())
    except (OSError, ValueError) as error:
        raise PublicDirectStaticDiscoveryExportError("base static discovery is invalid") from error
    if (
        base.revision != "static-direct-discovery-v1"
        or base.availability != "ready"
        or base.source is None
        or base.coverage is None
        or base.source.database_sha256 != _PUBLIC_DATABASE_SHA256
        or base.coverage.bound_direct_observation_count != _BASE_OBSERVATION_COUNT
        or len(base.genres) != _BASE_GENRE_COUNT
    ):
        raise PublicDirectStaticDiscoveryExportError(
            "base static discovery coverage or policy drifted"
        )
    return base


def _require_pinned_bridge(bridge: SealedQidDirectBridge) -> None:
    if (
        bridge.output_sha256 != sealed_qid_direct_bridge_sha256(bridge)
        or bridge.output_sha256 != _SEALED_QID_BRIDGE_SHA256
        or bridge.public_qid_seed_map_sha256 != _QID_MAP_SHA256
    ):
        raise PublicDirectStaticDiscoveryExportError(
            "sealed QID direct bridge selection or self-hash does not match pin"
        )
    if (
        bridge.public_database_sha256 != _PUBLIC_DATABASE_SHA256
        or bridge.base_static_discovery_sha256 != _STATIC_DISCOVERY_SHA256
        or bridge.coverage.positioned_genre_count != _ADDED_GENRE_COUNT
        or bridge.coverage.grouped_membership_count != _ADDED_MEMBERSHIP_COUNT
        or bridge.coverage.direct_observation_count != _ADDED_OBSERVATION_COUNT
    ):
        raise PublicDirectStaticDiscoveryExportError(
            "sealed QID direct bridge pin or coverage drifted"
        )


def _require_pinned_database(
    database: Path, bridge: SealedQidDirectBridge, base: StaticDiscoveryPayload
) -> None:
    actual, _ = sha256_file(database)
    if actual != _PUBLIC_DATABASE_SHA256 or bridge.public_database_sha256 != actual:
        raise PublicDirectStaticDiscoveryExportError("public database hash does not match pin")
    if base.source is None or base.source.database_sha256 != actual:
        raise PublicDirectStaticDiscoveryExportError(
            "base and bridge do not share the pinned database"
        )


def _load_observations(database: Path, bridge: SealedQidDirectBridge) -> dict[int, _Observation]:
    evidence_rows = tuple(
        evidence for membership in bridge.memberships for evidence in membership.evidence
    )
    expected: dict[int, BridgeEvidence] = {
        evidence.evidence_id: evidence for evidence in evidence_rows
    }
    if len(expected) != len(evidence_rows):
        raise PublicDirectStaticDiscoveryExportError("bridge repeats a direct observation")
    if len(expected) != bridge.coverage.direct_observation_count:
        raise PublicDirectStaticDiscoveryExportError("bridge repeats or omits direct observations")
    marks = ",".join("?" for _ in expected)
    try:
        with closing(
            sqlite3.connect(f"file:{database.resolve()}?mode=ro&immutable=1", uri=True)
        ) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                f"""WITH preferred_artist_names AS (
                        SELECT entity_id, name FROM (
                            SELECT name.entity_id, name.name,
                                   row_number() OVER (PARTITION BY name.entity_id ORDER BY
                                       (name.language_tag = 'en') DESC, name.is_preferred DESC,
                                       (name.language_tag = 'und') DESC, name.id) AS row_number
                            FROM displayable_entity_names AS name
                            JOIN artists AS artist ON artist.id = name.entity_id
                        ) WHERE row_number = 1
                    )
                    SELECT evidence.id, evidence.artist_id, artist_name.name AS artist_name,
                           evidence.genre_id, genre.name AS genre_name, evidence.source_key,
                           evidence.source_record_id, evidence.provenance_id
                    FROM displayable_artist_genre_evidence AS evidence
                    JOIN genres AS genre ON genre.id = evidence.genre_id
                    JOIN preferred_artist_names AS artist_name
                      ON artist_name.entity_id = evidence.artist_id
                    JOIN provenance_records AS provenance ON provenance.id = evidence.provenance_id
                    JOIN active_rights_policy_permissions AS export_permission
                      ON export_permission.policy_id = provenance.policy_id
                     AND export_permission.use_kind = 'export'
                     AND export_permission.decision = 'allow'
                    JOIN active_rights_policy_permissions AS display_permission
                      ON display_permission.policy_id = provenance.policy_id
                     AND display_permission.use_kind = 'display'
                     AND display_permission.decision = 'allow'
                    WHERE evidence.id IN ({marks})
                      AND evidence.evidence_kind = 'direct_source_claim'
                      AND evidence.method_key = 'wikidata_p136'
                      AND evidence.method_version = '1'
                    ORDER BY evidence.id""",  # noqa: S608 - IDs originate in a pinned receipt.
                tuple(expected),
            ).fetchall()
    except sqlite3.Error as error:
        raise PublicDirectStaticDiscoveryExportError(
            "public database cannot replay bridge observations"
        ) from error
    if len(rows) != len(expected):
        raise PublicDirectStaticDiscoveryExportError(
            "bridge observations lost authorization or became ambiguous"
        )
    observations = {
        int(row["id"]): _Observation(
            evidence_id=int(row["id"]),
            artist_catalog_id=int(row["artist_id"]),
            artist_name=str(row["artist_name"]),
            catalog_genre_id=int(row["genre_id"]),
            catalog_genre_name=str(row["genre_name"]),
            source_key=str(row["source_key"]),
            source_record_id=str(row["source_record_id"]),
            provenance_id=int(row["provenance_id"]),
        )
        for row in rows
    }
    if set(observations) != set(expected):
        raise PublicDirectStaticDiscoveryExportError(
            "bridge observation query returned duplicate or missing rows"
        )
    return observations


def _additions(
    bridge: SealedQidDirectBridge,
    observations: dict[int, _Observation],
    base: StaticDiscoveryPayload,
) -> tuple[tuple[AdditiveGenre, ...], tuple[AdditiveArtist, ...]]:
    by_artist: dict[int, list[tuple[SealedQidDirectMembership, _Observation]]] = defaultdict(list)
    by_genre: dict[int, list[tuple[SealedQidDirectMembership, _Observation]]] = defaultdict(list)
    base_genres = {genre.catalog_genre_id for genre in base.genres}
    base_nodes = {genre.node_id for genre in base.genres}
    for membership in bridge.memberships:
        if membership.catalog_genre_id in base_genres or membership.seed_id in base_nodes:
            raise PublicDirectStaticDiscoveryExportError(
                "bridge overlaps the sealed base genre or map node"
            )
        for evidence in membership.evidence:
            observation = observations.get(evidence.evidence_id)
            if observation is None or (
                observation.artist_catalog_id != membership.artist_catalog_id
                or observation.catalog_genre_id != membership.catalog_genre_id
                or observation.artist_name != membership.artist_name
                or observation.source_key != evidence.source_key
                or observation.source_record_id != evidence.source_record_id
                or observation.provenance_id != evidence.provenance_id
            ):
                raise PublicDirectStaticDiscoveryExportError(
                    "bridge evidence conflicts with the public database"
                )
            by_artist[observation.artist_catalog_id].append((membership, observation))
            by_genre[observation.catalog_genre_id].append((membership, observation))
    artists = tuple(_artist(artist_id, rows) for artist_id, rows in sorted(by_artist.items()))
    genres = tuple(_genre(genre_id, rows) for genre_id, rows in sorted(by_genre.items()))
    if len({artist.artist_id for artist in artists}) != len(artists) or len(
        {genre.node_id for genre in genres}
    ) != len(genres):
        raise PublicDirectStaticDiscoveryExportError("additive artist or genre identities overlap")
    return genres, artists


def _artist(
    artist_id: int, rows: list[tuple[SealedQidDirectMembership, _Observation]]
) -> AdditiveArtist:
    memberships = tuple(_membership(group) for group in _group_memberships(rows))
    names = {observation.artist_name for _, observation in rows}
    bridge_memberships = {item for item, _ in rows}
    identities = {
        (item.artist_musicbrainz_id, item.artist_wikidata_id) for item in bridge_memberships
    }
    if len(names) != 1 or len(identities) != 1:
        raise PublicDirectStaticDiscoveryExportError(
            "artist presentation identity conflicts within bridge"
        )
    musicbrainz_id, wikidata_id = next(iter(identities))
    return AdditiveArtist(
        artist_id=f"artist:{artist_id}",
        name=next(iter(names)),
        musicbrainz_url=f"https://musicbrainz.org/artist/{musicbrainz_id}",
        wikidata_url=f"https://www.wikidata.org/wiki/{wikidata_id}",
        memberships=memberships,
    )


def _genre(
    genre_id: int, rows: list[tuple[SealedQidDirectMembership, _Observation]]
) -> AdditiveGenre:
    memberships = {item for item, _ in rows}
    identities = {(item.seed_id, item.genre_qid) for item in memberships}
    names = {observation.catalog_genre_name for _, observation in rows}
    if len(identities) != 1 or len(names) != 1:
        raise PublicDirectStaticDiscoveryExportError(
            "genre presentation identity conflicts within bridge"
        )
    node_id, genre_qid = next(iter(identities))
    return AdditiveGenre(
        node_id=node_id,
        catalog_genre_id=genre_id,
        catalog_genre_name=next(iter(names)),
        genre_qid=genre_qid,
        binding="one_to_one_qid_position_binding",
        artist_ids=tuple(
            sorted({f"artist:{observation.artist_catalog_id}" for _, observation in rows})
        ),
    )


def _group_memberships(
    rows: list[tuple[SealedQidDirectMembership, _Observation]],
) -> list[list[tuple[SealedQidDirectMembership, _Observation]]]:
    grouped: dict[tuple[int, str], list[tuple[SealedQidDirectMembership, _Observation]]] = (
        defaultdict(list)
    )
    for membership, observation in rows:
        grouped[(observation.catalog_genre_id, membership.seed_id)].append(
            (membership, observation)
        )
    return [grouped[key] for key in sorted(grouped)]


def _membership(
    rows: list[tuple[SealedQidDirectMembership, _Observation]],
) -> AdditiveMembership:
    bridge_memberships = {item for item, _ in rows}
    identities = {
        (
            item.seed_id,
            item.catalog_genre_id,
            item.genre_qid,
        )
        for item in bridge_memberships
    }
    names = {observation.catalog_genre_name for _, observation in rows}
    if len(identities) != 1 or len(names) != 1:
        raise PublicDirectStaticDiscoveryExportError(
            "membership presentation identity conflicts within bridge"
        )
    node_id, genre_id, genre_qid = next(iter(identities))
    evidence = tuple(
        StaticDiscoveryEvidencePayload(
            evidence_id=observation.evidence_id,
            source_key=observation.source_key,
            source_record_id=observation.source_record_id,
            method_key="wikidata_p136",
            method_version="1",
            provenance_id=observation.provenance_id,
        )
        for _, observation in sorted(rows, key=lambda row: row[1].evidence_id)
    )
    return AdditiveMembership(
        node_id=node_id,
        catalog_genre_id=genre_id,
        catalog_genre_name=next(iter(names)),
        genre_qid=genre_qid,
        binding="one_to_one_qid_position_binding",
        evidence=evidence,
    )
