"""Derive a sealed direct-genre bridge from a QID-map receipt and public inputs.

This is a local release-qualification candidate.  It deliberately does not
read reconciliation, v3, or a prior direct-bridge receipt.
"""

from __future__ import annotations

import os
import sqlite3
import tempfile
from collections import defaultdict
from contextlib import closing
from pathlib import Path
from typing import Final, Literal

from pydantic import Field, model_validator

from opennoise.checkpoints.public_qid_seed_map import (
    PublicQidSeedMap,
    load_public_qid_seed_map,
)
from opennoise.common import canonical_json, sha256_file, sha256_hex
from opennoise.deployment.static_discovery import StaticDiscoveryPayload
from opennoise.models import FrozenModel
from opennoise.types import Sha256  # noqa: TC001

_REVISION: Final = "sealed-qid-direct-bridge-v1"
_PUBLIC_DATABASE_SHA256: Final = "240047cabddbbebccd48a775c9967488dd2dd2968d38d27f31354b90f3a3e8fc"
_STATIC_DISCOVERY_SHA256: Final = "b4ff2b1bcebb0bb6b1fd63b78caf9a416dbf5bb0c3050c0fa05e434fd0c700e8"
_QID_MAP_SHA256: Final = "dd5cf7cf33898a76c1e85e95351e25e7303933f4524e2776097c20fd0d73a449"
_SELECTION_SHA256: Final = "a6e24b756236abf94416c129d442dd7b7fd5592eb27e2fe742c4c7ece30c1b4a"
_OUTPUT_SHA256: Final = "c488223b34afcd59596072d4623e3190cfff1941cfdccb4da3e286e7ccebef5b"
_EXPECTED_COVERAGE: Final = {
    "positioned_genre_count": 84,
    "grouped_membership_count": 862,
    "direct_observation_count": 959,
    "artist_count": 536,
    "net_new_artist_count": 118,
}


class SealedQidDirectBridgeError(ValueError):
    """The sealed QID bridge cannot truthfully replay its construction inputs."""


class SealedQidDirectBridgeInputs(FrozenModel):
    """The three and only three construction inputs."""

    public_qid_seed_map: Path
    public_database: Path
    base_static_discovery: Path


class BridgeEvidence(FrozenModel):
    """One exact source-observed, presentation-authorized P136 v1 observation."""

    evidence_id: int = Field(gt=0)
    source_key: str = Field(min_length=1)
    source_record_id: str = Field(min_length=1)
    source_name: str = Field(min_length=1)
    policy_key: str = Field(min_length=1)
    policy_version: int = Field(gt=0)
    provenance_id: int = Field(gt=0)
    method_key: Literal["wikidata_p136"] = "wikidata_p136"
    method_version: Literal["1"] = "1"


class SealedQidDirectMembership(FrozenModel):
    """One artist/genre membership, with all supporting direct observations."""

    catalog_genre_id: int = Field(gt=0)
    genre_qid: str = Field(pattern=r"^Q[1-9][0-9]*$")
    seed_id: str = Field(min_length=1)
    binding: Literal["one_to_one_qid_position_binding"] = "one_to_one_qid_position_binding"
    artist_catalog_id: int = Field(gt=0)
    artist_name: str = Field(min_length=1)
    artist_musicbrainz_id: str = Field(
        pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
    )
    artist_wikidata_id: str = Field(pattern=r"^Q[1-9][0-9]*$")
    evidence: tuple[BridgeEvidence, ...] = Field(min_length=1)


class SealedQidDirectCoverage(FrozenModel):
    """Exact cardinality accounting for this bounded additive delta."""

    positioned_genre_count: int = Field(ge=0)
    grouped_membership_count: int = Field(ge=0)
    direct_observation_count: int = Field(ge=0)
    artist_count: int = Field(ge=0)
    net_new_artist_count: int = Field(ge=0)

    @model_validator(mode="after")
    def _bounds(self) -> SealedQidDirectCoverage:
        if self.net_new_artist_count > self.artist_count:
            raise ValueError("net-new artists exceed bridge artists")
        if self.grouped_membership_count > self.direct_observation_count:
            raise ValueError("grouped memberships exceed direct observations")
        return self


class SealedQidDirectBridge(FrozenModel):
    """An independently replayable, non-promoted QID direct bridge receipt."""

    revision: Literal["sealed-qid-direct-bridge-v1"] = _REVISION
    publication_scope: Literal["release_qualification_candidate_only"] = (
        "release_qualification_candidate_only"
    )
    static_output_written: Literal[False] = False
    promotion_performed: Literal[False] = False
    experimental_reconciliation_used: Literal[False] = False
    historical_bridge_used: Literal[False] = False
    public_qid_seed_map_sha256: Sha256
    public_database_sha256: Sha256
    base_static_discovery_sha256: Sha256
    selection_sha256: Sha256
    memberships: tuple[SealedQidDirectMembership, ...]
    coverage: SealedQidDirectCoverage
    output_sha256: Sha256


def sealed_qid_direct_bridge_sha256(receipt: SealedQidDirectBridge) -> Sha256:
    """Hash the receipt independently of its self-hash field."""
    return sha256_hex(canonical_json(receipt.model_dump(mode="json", exclude={"output_sha256"})))


def build_sealed_qid_direct_bridge(inputs: SealedQidDirectBridgeInputs) -> SealedQidDirectBridge:
    """Build only the direct, authorized, base-disjoint QID-map delta."""
    _require_hash(inputs.public_database, _PUBLIC_DATABASE_SHA256, "public database")
    _require_hash(inputs.base_static_discovery, _STATIC_DISCOVERY_SHA256, "base static discovery")
    qid_map = _load_pinned_qid_map(inputs.public_qid_seed_map)
    base = _load_base_static(inputs.base_static_discovery)
    selected = _resolve_selected_qids(inputs.public_database, qid_map)
    base_genres = {item.catalog_genre_id for item in base.genres}
    base_seed_ids = {item.node_id for item in base.genres}
    # The QID receipt establishes every safe positioned binding.  This bridge
    # is only its additive delta, so discard the already-present base nodes
    # before asking whether a direct observation exists.
    selected = {
        genre_id: binding for genre_id, binding in selected.items() if genre_id not in base_genres
    }
    if {seed_id for _, seed_id in selected.values()} & base_seed_ids:
        raise SealedQidDirectBridgeError(
            "selected QID seed is already present in base static genres"
        )
    if set(selected) & base_genres:
        raise SealedQidDirectBridgeError(
            "selected QID genres are not disjoint from base static genres"
        )
    observations = _load_observations(inputs.public_database, selected)
    memberships = _group_memberships(observations)
    _assert_base_artist_consistency(base, memberships)
    artists = {item.artist_catalog_id for item in memberships}
    base_artists = {
        int(item.artist_id.removeprefix("artist:"))
        for item in base.artists
        if item.artist_id.startswith("artist:")
    }
    coverage = SealedQidDirectCoverage(
        positioned_genre_count=len({item.catalog_genre_id for item in memberships}),
        grouped_membership_count=len(memberships),
        direct_observation_count=sum(len(item.evidence) for item in memberships),
        artist_count=len(artists),
        net_new_artist_count=len(artists - base_artists),
    )
    bindings = {(item.catalog_genre_id, item.genre_qid, item.seed_id) for item in memberships}
    if len(bindings) != coverage.positioned_genre_count:
        raise SealedQidDirectBridgeError("direct-positive genre bindings do not replay uniquely")
    selection_sha256 = sha256_hex(canonical_json(sorted(bindings)))
    base_receipt = SealedQidDirectBridge(
        public_qid_seed_map_sha256=qid_map.output_sha256,
        public_database_sha256=_PUBLIC_DATABASE_SHA256,
        base_static_discovery_sha256=_STATIC_DISCOVERY_SHA256,
        selection_sha256=selection_sha256,
        memberships=memberships,
        coverage=coverage,
        output_sha256="0" * 64,
    )
    receipt = base_receipt.model_copy(
        update={"output_sha256": sealed_qid_direct_bridge_sha256(base_receipt)}
    )
    _verify_receipt(receipt)
    return receipt


def write_sealed_qid_direct_bridge(receipt: SealedQidDirectBridge, output: Path) -> Sha256:
    """Atomically create one local receipt, never replacing an existing target."""
    _verify_receipt(receipt)
    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{output.name}.", dir=output.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(canonical_json(receipt.model_dump(mode="json")) + b"\n")
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, output)
        except FileExistsError as error:
            raise SealedQidDirectBridgeError("refusing to overwrite an existing receipt") from error
    finally:
        temporary.unlink(missing_ok=True)
    return sha256_file(output)[0]


def load_sealed_qid_direct_bridge(path: Path) -> SealedQidDirectBridge:
    """Load a self-consistent local candidate receipt."""
    try:
        receipt = SealedQidDirectBridge.model_validate_json(path.read_bytes())
    except (OSError, ValueError) as error:
        raise SealedQidDirectBridgeError("sealed QID direct bridge receipt is invalid") from error
    _verify_receipt(receipt)
    return receipt


def _verify_receipt(receipt: SealedQidDirectBridge) -> None:
    if receipt.output_sha256 != sealed_qid_direct_bridge_sha256(receipt):
        raise SealedQidDirectBridgeError("receipt logical hash does not replay")
    if receipt.public_qid_seed_map_sha256 != _QID_MAP_SHA256:
        raise SealedQidDirectBridgeError("public QID seed-map pin does not match")
    if receipt.public_database_sha256 != _PUBLIC_DATABASE_SHA256:
        raise SealedQidDirectBridgeError("public database pin does not match")
    if receipt.base_static_discovery_sha256 != _STATIC_DISCOVERY_SHA256:
        raise SealedQidDirectBridgeError("base static discovery pin does not match")
    if receipt.coverage.model_dump() != _EXPECTED_COVERAGE:
        raise SealedQidDirectBridgeError("pinned sealed QID bridge coverage drifted")
    if receipt.selection_sha256 != _SELECTION_SHA256:
        raise SealedQidDirectBridgeError("pinned sealed QID bridge selection hash does not match")
    if receipt.output_sha256 != _OUTPUT_SHA256:
        raise SealedQidDirectBridgeError("pinned sealed QID bridge output hash does not match")


def _require_hash(path: Path, expected: Sha256, role: str) -> None:
    try:
        actual, _ = sha256_file(path)
    except OSError as error:
        raise SealedQidDirectBridgeError(f"cannot read pinned {role}") from error
    if actual != expected:
        raise SealedQidDirectBridgeError(f"pinned {role} hash does not match")


def _load_pinned_qid_map(path: Path) -> PublicQidSeedMap:
    receipt = load_public_qid_seed_map(path)
    if receipt.output_sha256 != _QID_MAP_SHA256:
        raise SealedQidDirectBridgeError("public QID seed-map selection hash does not match")
    return receipt


def _load_base_static(path: Path) -> StaticDiscoveryPayload:
    try:
        payload = StaticDiscoveryPayload.model_validate_json(path.read_bytes())
    except (OSError, ValueError) as error:
        raise SealedQidDirectBridgeError("base static discovery is invalid") from error
    if payload.availability != "ready" or payload.source is None:
        raise SealedQidDirectBridgeError("base static discovery is unavailable")
    if payload.source.database_sha256 != _PUBLIC_DATABASE_SHA256:
        raise SealedQidDirectBridgeError(
            "base static discovery is not bound to the public database"
        )
    return payload


def _resolve_selected_qids(
    database_path: Path, receipt: PublicQidSeedMap
) -> dict[int, tuple[str, str]]:
    """Replay every selected QID against exactly one public catalog genre node."""
    expected = {item.qid: (item.catalog_genre_id, item.seed_id) for item in receipt.mappings}
    if len(expected) != len(receipt.mappings):
        raise SealedQidDirectBridgeError("QID seed map contains duplicate QID bindings")
    try:
        with closing(
            sqlite3.connect(
                f"file:{database_path.resolve(strict=True)}?mode=ro&immutable=1", uri=True
            )
        ) as database:
            rows = database.execute(
                """SELECT identifier.normalized_value, identifier.entity_id, entity.entity_kind
                   FROM entity_identifiers AS identifier
                   JOIN identifier_types AS type ON type.id = identifier.identifier_type_id
                   JOIN catalog_entities AS entity ON entity.id = identifier.entity_id
                   WHERE type.type_key = 'wikidata_genre_qid' AND identifier.namespace = 'wikidata'
                   ORDER BY identifier.normalized_value, identifier.entity_id"""
            ).fetchall()
    except sqlite3.Error as error:
        raise SealedQidDirectBridgeError("public database cannot resolve selected QIDs") from error
    resolved: dict[str, set[tuple[int, str]]] = defaultdict(set)
    for qid, genre_id, entity_kind in rows:
        if str(qid) in expected:
            resolved[str(qid)].add((int(genre_id), str(entity_kind)))
    selected: dict[int, tuple[str, str]] = {}
    for qid, (expected_id, seed_id) in expected.items():
        if resolved.get(qid) != {(expected_id, "genre")}:
            raise SealedQidDirectBridgeError(
                "selected QID does not resolve to exactly one mapped genre node"
            )
        if expected_id in selected:
            raise SealedQidDirectBridgeError(
                "multiple selected QIDs resolve to one catalog genre node"
            )
        selected[expected_id] = (qid, seed_id)
    return selected


class _Observation(FrozenModel):
    catalog_genre_id: int
    genre_qid: str
    seed_id: str
    artist_catalog_id: int
    artist_name: str
    artist_musicbrainz_id: str
    artist_wikidata_id: str
    evidence: BridgeEvidence


def _load_observations(
    database_path: Path, selected: dict[int, tuple[str, str]]
) -> tuple[_Observation, ...]:
    if not selected:
        raise SealedQidDirectBridgeError("QID seed map selected no genre nodes")
    placeholders = ",".join("?" for _ in selected)
    query = f"""WITH authorized_identifier AS (
                    SELECT identifier.entity_id,
                           CASE WHEN identifier.namespace = 'musicbrainz'
                                  AND type.type_key = 'musicbrainz_artist_id' THEN 'mbid'
                                WHEN identifier.namespace = 'wikidata'
                                  AND type.type_key IN ('wikidata_qid', 'wikidata_artist_qid') THEN 'qid'
                           END AS kind, identifier.normalized_value
                    FROM entity_identifiers AS identifier
                    JOIN identifier_types AS type ON type.id = identifier.identifier_type_id
                    JOIN provenance_records AS provenance ON provenance.id = identifier.provenance_id
                    JOIN rights_policies AS policy ON policy.id = provenance.policy_id
                    JOIN active_rights_policy_permissions AS export_permission ON export_permission.policy_id = policy.id AND export_permission.use_kind = 'export' AND export_permission.decision = 'allow'
                    JOIN active_rights_policy_permissions AS display_permission ON display_permission.policy_id = policy.id AND display_permission.use_kind = 'display' AND display_permission.decision = 'allow'
                    WHERE (identifier.namespace = 'musicbrainz' AND type.type_key = 'musicbrainz_artist_id')
                       OR (identifier.namespace = 'wikidata' AND type.type_key IN ('wikidata_qid', 'wikidata_artist_qid'))
                 ), unique_identifier AS (
                    SELECT entity_id, kind, min(normalized_value) AS value FROM authorized_identifier
                    GROUP BY entity_id, kind HAVING count(DISTINCT normalized_value) = 1
                 ), authorized_name AS (
                    SELECT entity_id, name FROM (
                    SELECT name.entity_id, name.name,
                           row_number() OVER (PARTITION BY name.entity_id
                               ORDER BY (name.language_tag = 'en') DESC,
                                        name.is_preferred DESC,
                                        (name.language_tag = 'und') DESC, name.id) AS row_number
                    FROM displayable_entity_names AS name
                    JOIN artists AS artist ON artist.id = name.entity_id
                    JOIN provenance_records AS provenance ON provenance.id = name.provenance_id
                    JOIN rights_policies AS policy ON policy.id = provenance.policy_id
                    JOIN active_rights_policy_permissions AS export_permission ON export_permission.policy_id = policy.id AND export_permission.use_kind = 'export' AND export_permission.decision = 'allow'
                    JOIN active_rights_policy_permissions AS display_permission ON display_permission.policy_id = policy.id AND display_permission.use_kind = 'display' AND display_permission.decision = 'allow'
                    ) WHERE row_number = 1
                 )
                 SELECT evidence.genre_id, evidence.artist_id, artist_name.name, mbid.value, wikidata.value,
                        evidence.id, evidence.source_key, evidence.source_record_id, source.name,
                        policy.policy_key, policy.policy_version, evidence.provenance_id
                 FROM displayable_artist_genre_evidence AS evidence
                 JOIN provenance_records AS provenance ON provenance.id = evidence.provenance_id
                 JOIN data_sources AS source ON source.id = provenance.source_id
                 JOIN rights_policies AS policy ON policy.id = provenance.policy_id
                 JOIN active_rights_policy_permissions AS export_permission ON export_permission.policy_id = policy.id AND export_permission.use_kind = 'export' AND export_permission.decision = 'allow'
                 JOIN active_rights_policy_permissions AS display_permission ON display_permission.policy_id = policy.id AND display_permission.use_kind = 'display' AND display_permission.decision = 'allow'
                 JOIN unique_identifier AS mbid ON mbid.entity_id = evidence.artist_id AND mbid.kind = 'mbid'
                 JOIN unique_identifier AS wikidata ON wikidata.entity_id = evidence.artist_id AND wikidata.kind = 'qid'
                 JOIN authorized_name AS artist_name ON artist_name.entity_id = evidence.artist_id
                 WHERE evidence.genre_id IN ({placeholders})
                   AND evidence.evidence_kind = 'direct_source_claim'
                   AND evidence.method_key = 'wikidata_p136' AND evidence.method_version = '1'
                 ORDER BY evidence.genre_id, evidence.artist_id, evidence.id"""  # noqa: E501, S608
    try:
        with closing(
            sqlite3.connect(
                f"file:{database_path.resolve(strict=True)}?mode=ro&immutable=1", uri=True
            )
        ) as database:
            rows = database.execute(query, tuple(sorted(selected))).fetchall()
    except sqlite3.Error as error:
        raise SealedQidDirectBridgeError(
            "public database cannot replay authorized P136 evidence"
        ) from error
    parsed = []
    for row in rows:
        genre_id = int(row[0])
        qid, seed_id = selected[genre_id]
        parsed.append(
            _Observation(
                catalog_genre_id=genre_id,
                genre_qid=qid,
                seed_id=seed_id,
                artist_catalog_id=int(row[1]),
                artist_name=str(row[2]),
                artist_musicbrainz_id=str(row[3]),
                artist_wikidata_id=str(row[4]),
                evidence=BridgeEvidence(
                    evidence_id=int(row[5]),
                    source_key=str(row[6]),
                    source_record_id=str(row[7]),
                    source_name=str(row[8]),
                    policy_key=str(row[9]),
                    policy_version=int(row[10]),
                    provenance_id=int(row[11]),
                ),
            )
        )
    _require_unique_evidence_ids(tuple(parsed))
    return tuple(parsed)


def _require_unique_evidence_ids(observations: tuple[_Observation, ...]) -> None:
    """Reject a policy-join replay that would duplicate one immutable evidence row."""
    if len({item.evidence.evidence_id for item in observations}) != len(observations):
        raise SealedQidDirectBridgeError("authorized P136 evidence IDs are not unique")


def _group_memberships(
    observations: tuple[_Observation, ...],
) -> tuple[SealedQidDirectMembership, ...]:
    grouped: dict[tuple[int, int], list[_Observation]] = defaultdict(list)
    for observation in observations:
        grouped[(observation.artist_catalog_id, observation.catalog_genre_id)].append(observation)
    memberships = []
    for _, items in sorted(grouped.items()):
        first = items[0]
        identity = (
            first.genre_qid,
            first.seed_id,
            first.artist_name,
            first.artist_musicbrainz_id,
            first.artist_wikidata_id,
        )
        if any(
            (
                item.genre_qid,
                item.seed_id,
                item.artist_name,
                item.artist_musicbrainz_id,
                item.artist_wikidata_id,
            )
            != identity
            for item in items
        ):
            raise SealedQidDirectBridgeError(
                "grouped evidence does not share one authorized identity"
            )
        memberships.append(
            SealedQidDirectMembership(
                catalog_genre_id=first.catalog_genre_id,
                genre_qid=first.genre_qid,
                seed_id=first.seed_id,
                artist_catalog_id=first.artist_catalog_id,
                artist_name=first.artist_name,
                artist_musicbrainz_id=first.artist_musicbrainz_id,
                artist_wikidata_id=first.artist_wikidata_id,
                evidence=tuple(item.evidence for item in items),
            )
        )
    return tuple(memberships)


def _assert_base_artist_consistency(
    base: StaticDiscoveryPayload, memberships: tuple[SealedQidDirectMembership, ...]
) -> None:
    """Ensure a shared catalog artist retains the base's authorized presentation identity."""
    base_artists = {
        int(item.artist_id.removeprefix("artist:")): item
        for item in base.artists
        if item.artist_id.startswith("artist:")
    }
    for membership in memberships:
        if (base_artist := base_artists.get(membership.artist_catalog_id)) is None:
            continue
        if (
            base_artist.name != membership.artist_name
            or base_artist.musicbrainz_url
            != f"https://musicbrainz.org/artist/{membership.artist_musicbrainz_id}"
            or base_artist.wikidata_url
            != f"https://www.wikidata.org/wiki/{membership.artist_wikidata_id}"
        ):
            raise SealedQidDirectBridgeError(
                "overlapping base artist does not retain its authorized name and identifiers"
            )
