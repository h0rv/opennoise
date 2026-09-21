"""Build the sealed-input contract for a future static direct-genre bridge.

This is a construction receipt only.  It reuses the pinned public-direct
candidate rather than accepting a review JSON, and it neither exports nor
promotes any static asset.
"""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from contextlib import closing
from pathlib import Path  # noqa: TC003
from typing import TYPE_CHECKING, Literal

from pydantic import Field, model_validator

from opennoise.checkpoints.public_direct_bridge_candidate import (
    CandidateInputs,
    DirectBridgeRow,
    PublicDirectBridgeCandidate,
    build_public_direct_bridge_candidate,
    candidate_sha256,
)
from opennoise.common import canonical_json, sha256_hex
from opennoise.models import FrozenModel
from opennoise.types import Sha256  # noqa: TC001

if TYPE_CHECKING:
    from collections.abc import Sequence

_REVISION = "public-direct-production-bridge-v1"
_STATIC_DISCOVERY_SHA256 = "b4ff2b1bcebb0bb6b1fd63b78caf9a416dbf5bb0c3050c0fa05e434fd0c700e8"
_CANDIDATE_SHA256 = "78d1a3589b39dfa6322efbc0ee0e1f7bef4d3c836c0b2b7471550f88f2246dc4"
_PRIMARY_SELECTION_SHA256 = "324516e89b8c8099350d3ca6d8873d23a53a51ebc15fb7f67f613f10428a3e0b"
_MBID_URL = "https://musicbrainz.org/artist/"
_WIKIDATA_URL = "https://www.wikidata.org/wiki/"


class PublicDirectProductionBridgeError(ValueError):
    """The sealed factual bridge contract could not be replayed."""


class ProductionBridgeEvidence(FrozenModel):
    """One source-observed P136 row, retained without interpretation."""

    evidence_id: int = Field(gt=0)
    source_key: str = Field(min_length=1)
    source_record_id: str = Field(min_length=1)
    method_key: Literal["wikidata_p136"]
    method_version: Literal["1"]
    provenance_id: int = Field(gt=0)


class ProductionBridgeMembership(FrozenModel):
    """One authorized direct artist-to-positioned-seed presentation binding."""

    catalog_genre_id: int = Field(gt=0)
    source_genre_ref: str = Field(pattern=r"^wikidata:genre:Q[1-9][0-9]*$")
    seed_id: str = Field(pattern=r"^item[1-9][0-9]*$")
    reconciliation_disposition: Literal["reconciled", "public_only"]
    binding: Literal["one_to_one_qid_position_binding"]
    artist_catalog_id: int = Field(gt=0)
    artist_musicbrainz_id: str = Field(
        pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
    )
    artist_musicbrainz_url: str = Field(
        pattern=(
            r"^https://musicbrainz\.org/artist/"
            r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
        )
    )
    artist_wikidata_id: str = Field(pattern=r"^Q[1-9][0-9]*$")
    artist_wikidata_url: str = Field(pattern=r"^https://www\.wikidata\.org/wiki/Q[1-9][0-9]*$")
    evidence: tuple[ProductionBridgeEvidence, ...] = Field(min_length=1)


class ProductionBridgeCoverage(FrozenModel):
    """The fixed delta eligible for a separately reviewed exporter integration."""

    positioned_genre_count: int = Field(ge=0)
    grouped_membership_count: int = Field(ge=0)
    direct_observation_count: int = Field(ge=0)
    artist_count: int = Field(ge=0)
    net_new_artist_count: int = Field(ge=0)

    @model_validator(mode="after")
    def _bounds(self) -> ProductionBridgeCoverage:
        if self.net_new_artist_count > self.artist_count:
            raise ValueError("net-new artists exceed bridge artists")
        return self


class PublicDirectProductionBridge(FrozenModel):
    """A hash-pinned factual bridge receipt, not a release input yet."""

    revision: Literal["public-direct-production-bridge-v1"] = _REVISION
    publication_scope: Literal["sealed_input_contract_only"] = "sealed_input_contract_only"
    static_output_written: Literal[False] = False
    promotion_performed: Literal[False] = False
    historical_inputs_used: Literal[False] = False
    public_direct_candidate_sha256: Sha256
    primary_selection_sha256: Sha256
    public_database_sha256: Sha256
    static_discovery_sha256: Sha256
    reconciliation_sha256: Sha256
    canonical_layout_sha256: Sha256
    memberships: tuple[ProductionBridgeMembership, ...]
    coverage: ProductionBridgeCoverage
    output_sha256: Sha256


def production_bridge_sha256(receipt: PublicDirectProductionBridge) -> Sha256:
    """Hash the receipt independently of its self-hash field."""
    return sha256_hex(canonical_json(receipt.model_dump(mode="json", exclude={"output_sha256"})))


def build_public_direct_production_bridge(inputs: CandidateInputs) -> PublicDirectProductionBridge:
    """Replay the pinned candidate into the stricter future-export contract."""
    candidate = build_public_direct_bridge_candidate(inputs)
    candidate_digest = _require_pinned_candidate(candidate)
    if candidate.static_discovery_sha256 != _STATIC_DISCOVERY_SHA256:
        raise PublicDirectProductionBridgeError(
            "candidate static discovery SHA-256 does not match the additive base pin"
        )
    observations = _load_bound_observations(inputs.public_database, candidate.rows)
    memberships = _memberships(candidate.rows, observations)
    coverage = ProductionBridgeCoverage(
        positioned_genre_count=len({item.catalog_genre_id for item in memberships}),
        grouped_membership_count=len(memberships),
        direct_observation_count=sum(len(item.evidence) for item in memberships),
        artist_count=len({item.artist_catalog_id for item in memberships}),
        net_new_artist_count=candidate.coverage.net_new_artist_count,
    )
    if coverage.model_dump() != {
        "positioned_genre_count": 84,
        "grouped_membership_count": 862,
        "direct_observation_count": 959,
        "artist_count": 536,
        "net_new_artist_count": 118,
    }:
        raise PublicDirectProductionBridgeError(
            f"pinned production bridge coverage drifted: {coverage.model_dump()}"
        )
    base = PublicDirectProductionBridge(
        public_direct_candidate_sha256=candidate_digest,
        primary_selection_sha256=candidate.primary_selection_sha256,
        public_database_sha256=candidate.public_database_sha256,
        static_discovery_sha256=candidate.static_discovery_sha256,
        reconciliation_sha256=candidate.reconciliation_sha256,
        canonical_layout_sha256=candidate.canonical_layout_sha256,
        memberships=memberships,
        coverage=coverage,
        output_sha256="0" * 64,
    )
    return base.model_copy(update={"output_sha256": production_bridge_sha256(base)})


def _require_pinned_candidate(candidate: PublicDirectBridgeCandidate) -> Sha256:
    """Require both the complete candidate selection and its primary link selection."""
    candidate_digest = candidate_sha256(candidate)
    if candidate.output_sha256 != candidate_digest or candidate_digest != _CANDIDATE_SHA256:
        raise PublicDirectProductionBridgeError(
            "candidate selection SHA-256 does not match the pin"
        )
    if candidate.primary_selection_sha256 != _PRIMARY_SELECTION_SHA256:
        raise PublicDirectProductionBridgeError(
            "candidate primary selection SHA-256 does not match the pin"
        )
    return candidate_digest


class _BoundObservation(FrozenModel):
    """One database row joined to its authorized immutable artist identities."""

    evidence_id: int = Field(gt=0)
    catalog_genre_id: int = Field(gt=0)
    artist_catalog_id: int = Field(gt=0)
    source_key: str = Field(min_length=1)
    source_record_id: str = Field(min_length=1)
    provenance_id: int = Field(gt=0)
    artist_musicbrainz_id: str
    artist_wikidata_id: str


def _load_bound_observations(
    database_path: Path, rows: tuple[DirectBridgeRow, ...]
) -> dict[int, _BoundObservation]:
    evidence_ids = tuple(row.evidence_id for row in rows)
    if not evidence_ids or len(set(evidence_ids)) != len(evidence_ids):
        raise PublicDirectProductionBridgeError(
            "candidate evidence IDs must be non-empty and unique"
        )
    placeholders = ",".join("?" for _ in evidence_ids)
    try:
        with closing(
            sqlite3.connect(f"file:{database_path.resolve()}?mode=ro&immutable=1", uri=True)
        ) as database:
            database.row_factory = sqlite3.Row
            database_rows = database.execute(
                f"""WITH authorized_identifier AS (
                        SELECT identifier.entity_id,
                               CASE
                                   WHEN identifier.namespace = 'musicbrainz'
                                    AND identifier_type.type_key = 'musicbrainz_artist_id'
                                   THEN 'musicbrainz'
                                   WHEN identifier.namespace = 'wikidata'
                                    AND identifier_type.type_key IN (
                                        'wikidata_qid', 'wikidata_artist_qid'
                                    )
                                   THEN 'wikidata'
                               END AS identifier_kind,
                               identifier.normalized_value
                        FROM entity_identifiers AS identifier
                        JOIN identifier_types AS identifier_type
                          ON identifier_type.id = identifier.identifier_type_id
                        JOIN provenance_records AS provenance
                          ON provenance.id = identifier.provenance_id
                        JOIN active_rights_policy_permissions AS export_permission
                          ON export_permission.policy_id = provenance.policy_id
                         AND export_permission.use_kind = 'export'
                         AND export_permission.decision = 'allow'
                        JOIN active_rights_policy_permissions AS display_permission
                          ON display_permission.policy_id = provenance.policy_id
                         AND display_permission.use_kind = 'display'
                         AND display_permission.decision = 'allow'
                        WHERE (identifier.namespace = 'musicbrainz'
                               AND identifier_type.type_key = 'musicbrainz_artist_id')
                           OR (identifier.namespace = 'wikidata'
                               AND identifier_type.type_key IN (
                                   'wikidata_qid', 'wikidata_artist_qid'
                               ))
                    ), unique_identifier AS (
                        SELECT entity_id, identifier_kind, min(normalized_value) AS normalized_value
                        FROM authorized_identifier
                        GROUP BY entity_id, identifier_kind
                        HAVING count(DISTINCT normalized_value) = 1
                    )
                    SELECT evidence.id AS evidence_id,
                           evidence.genre_id AS catalog_genre_id,
                           evidence.artist_id AS artist_catalog_id,
                           evidence.source_key, evidence.source_record_id, evidence.provenance_id,
                           mbid.normalized_value AS artist_musicbrainz_id,
                           wikidata.normalized_value AS artist_wikidata_id
                    FROM displayable_artist_genre_evidence AS evidence
                    JOIN provenance_records AS provenance ON provenance.id = evidence.provenance_id
                    JOIN active_rights_policy_permissions AS export_permission
                      ON export_permission.policy_id = provenance.policy_id
                     AND export_permission.use_kind = 'export'
                     AND export_permission.decision = 'allow'
                    JOIN active_rights_policy_permissions AS display_permission
                      ON display_permission.policy_id = provenance.policy_id
                     AND display_permission.use_kind = 'display'
                     AND display_permission.decision = 'allow'
                    JOIN unique_identifier AS mbid
                      ON mbid.entity_id = evidence.artist_id
                     AND mbid.identifier_kind = 'musicbrainz'
                    JOIN unique_identifier AS wikidata
                      ON wikidata.entity_id = evidence.artist_id
                     AND wikidata.identifier_kind = 'wikidata'
                    WHERE evidence.id IN ({placeholders})
                      AND evidence.evidence_kind = 'direct_source_claim'
                      AND evidence.method_key = 'wikidata_p136'
                      AND evidence.method_version = '1'
                    ORDER BY evidence.id""",  # noqa: S608 - pinned integer IDs only.
                evidence_ids,
            ).fetchall()
    except sqlite3.Error as error:
        raise PublicDirectProductionBridgeError(
            "public database cannot replay bridge evidence"
        ) from error
    return _index_observations([dict(row) for row in database_rows], evidence_ids)


def _index_observations(
    database_rows: Sequence[dict[str, object]], evidence_ids: tuple[int, ...]
) -> dict[int, _BoundObservation]:
    """Reject duplicated policy joins before indexing by source evidence ID."""
    if len(database_rows) != len(evidence_ids):
        raise PublicDirectProductionBridgeError(
            "bridge evidence query returned duplicate or missing authorized rows"
        )
    parsed = tuple(_BoundObservation.model_validate(row) for row in database_rows)
    observations = {row.evidence_id: row for row in parsed}
    if set(observations) != set(evidence_ids):
        raise PublicDirectProductionBridgeError(
            "every bridge row must retain authorized direct P136 evidence and unique artist IDs"
        )
    return observations


def _memberships(
    rows: tuple[DirectBridgeRow, ...], observations: dict[int, _BoundObservation]
) -> tuple[ProductionBridgeMembership, ...]:
    grouped: dict[tuple[int, int], list[tuple[DirectBridgeRow, _BoundObservation]]] = defaultdict(
        list
    )
    for row in rows:
        observation = observations[row.evidence_id]
        if (
            observation.catalog_genre_id != row.catalog_genre_id
            or observation.artist_catalog_id != row.artist_catalog_id
            or observation.source_key != row.source_key
            or observation.source_record_id != row.source_record_id
            or observation.artist_musicbrainz_id != row.artist_musicbrainz_id
        ):
            raise PublicDirectProductionBridgeError(
                "database observation does not match candidate row"
            )
        grouped[(row.artist_catalog_id, row.catalog_genre_id)].append((row, observation))
    result = []
    for (artist_id, genre_id), items in sorted(grouped.items()):
        identities = {
            (
                row.source_genre_ref,
                row.seed_id,
                row.reconciliation_disposition,
                observation.artist_musicbrainz_id,
                observation.artist_wikidata_id,
            )
            for row, observation in items
        }
        if len(identities) != 1:
            raise PublicDirectProductionBridgeError(
                "grouped candidate evidence does not share one production presentation identity"
            )
        source_genre_ref, seed_id, disposition, mbid, wikidata_id = next(iter(identities))
        result.append(
            ProductionBridgeMembership(
                catalog_genre_id=genre_id,
                source_genre_ref=source_genre_ref,
                seed_id=seed_id,
                reconciliation_disposition=disposition,
                binding="one_to_one_qid_position_binding",
                artist_catalog_id=artist_id,
                artist_musicbrainz_id=mbid,
                artist_musicbrainz_url=f"{_MBID_URL}{mbid}",
                artist_wikidata_id=wikidata_id,
                artist_wikidata_url=f"{_WIKIDATA_URL}{wikidata_id}",
                evidence=tuple(
                    ProductionBridgeEvidence(
                        evidence_id=observation.evidence_id,
                        source_key=observation.source_key,
                        source_record_id=observation.source_record_id,
                        method_key="wikidata_p136",
                        method_version="1",
                        provenance_id=observation.provenance_id,
                    )
                    for _, observation in items
                ),
            )
        )
    return tuple(result)
