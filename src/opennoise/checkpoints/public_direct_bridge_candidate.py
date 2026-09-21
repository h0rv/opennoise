"""Build a local-only candidate from pinned public direct claims and seed identities.

This module never opens the local v3 model or any historical artifact.  It is
an audit/report boundary, not a static export or publication promotion path.
"""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from contextlib import closing
from pathlib import Path  # noqa: TC003
from typing import Final, Literal

from pydantic import Field, model_validator

from opennoise.common import canonical_json, sha256_file, sha256_hex
from opennoise.deployment.static_discovery import StaticDiscoveryPayload
from opennoise.ml.semantic_layout.contracts import (
    SemanticLayoutArtifact,
    verify_semantic_map_layout,
)
from opennoise.models import FrozenModel
from opennoise.types import Sha256  # noqa: TC001

_PUBLIC_DB_SHA256: Final = "240047cabddbbebccd48a775c9967488dd2dd2968d38d27f31354b90f3a3e8fc"
_STATIC_SHA256: Final = "b4ff2b1bcebb0bb6b1fd63b78caf9a416dbf5bb0c3050c0fa05e434fd0c700e8"
_RECON_SHA256: Final = "a9db9fb5d7a8dc1fdeae8e311b7e1d4556d98947a7d600ef4c331a86eba5bef0"
_RECON_LOGICAL_SHA256: Final = "ba2bba15c8fb1e5188dbd8c3406bba0a5064742de0d25e9be024cee49ebcd3f0"
_LAYOUT_SHA256: Final = "e7723b42657451a341e92a9aefa1ced499067e673366b468fd38f84fc86f5972"
_LAYOUT_LOGICAL_SHA256: Final = "469f207021157031e88853be1b9f2d1eb63af8f0fcfc9c504e19e7584fd0cc38"
_REVISION: Final = "public-direct-bridge-candidate-v1"


class PublicDirectBridgeCandidateError(ValueError):
    """A pinned public-only candidate boundary is invalid."""


class CandidateInputs(FrozenModel):
    """Pinned public-only construction paths."""

    public_database: Path
    static_discovery: Path
    reconciliation: Path
    canonical_layout: Path


class _LegacyPublicIdentity(FrozenModel):
    namespace: str
    identifier: str


class _LegacyDisposition(FrozenModel):
    source_item_id: str
    disposition: str
    public_identities: tuple[_LegacyPublicIdentity, ...]


class _LegacyReconciliation(FrozenModel):
    """The pinned v1 reconciliation shape retained for the v3 seed bridge."""

    seed_count: int
    dispositions: tuple[_LegacyDisposition, ...]
    output_sha256: Sha256


class DirectBridgeRow(FrozenModel):
    """One exact, authorized public direct claim on a new positioned seed."""

    catalog_genre_id: int = Field(gt=0)
    source_genre_ref: str = Field(pattern=r"^wikidata:genre:Q[1-9][0-9]*$")
    seed_id: str = Field(pattern=r"^item[1-9][0-9]*$")
    reconciliation_disposition: Literal["reconciled", "public_only"]
    artist_musicbrainz_id: str = Field(
        pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
    )
    artist_catalog_id: int = Field(gt=0)
    evidence_id: int = Field(gt=0)
    source_key: str = Field(min_length=1)
    source_record_id: str = Field(min_length=1)
    authorization_status: Literal["display_and_export_authorized"]
    identifier_status: Literal["one_authorized_musicbrainz_artist_id"]


class DirectBridgeCoverage(FrozenModel):
    """Aggregate accounting for the strictly bounded candidate."""

    resolved_reconciliation_count: int = Field(ge=0)
    positioned_seed_link_count: int = Field(ge=0)
    distinct_catalog_genre_count: int = Field(ge=0)
    direct_claim_catalog_genre_count: int = Field(ge=0)
    already_static_catalog_genre_count: int = Field(ge=0)
    new_direct_catalog_genre_count: int = Field(ge=0)
    exact_direct_pair_count: int = Field(ge=0)
    distinct_artist_count: int = Field(ge=0)
    net_new_artist_count: int = Field(ge=0)

    @model_validator(mode="after")
    def _replay(self) -> DirectBridgeCoverage:
        if (
            self.already_static_catalog_genre_count + self.new_direct_catalog_genre_count
            != self.direct_claim_catalog_genre_count
        ):
            raise ValueError("static and new direct genre counts do not replay")
        if self.net_new_artist_count > self.distinct_artist_count:
            raise ValueError("new artists exceed direct-claim artists")
        return self


class PublicDirectBridgeCandidate(FrozenModel):
    """A non-promoted report of public direct claims eligible for review."""

    revision: Literal["public-direct-bridge-candidate-v1"] = _REVISION
    publication_scope: Literal["local_review_candidate_only"] = "local_review_candidate_only"
    static_output_written: Literal[False] = False
    promotion_performed: Literal[False] = False
    one_hop_claims_included: Literal[False] = False
    historical_inputs_used: Literal[False] = False
    public_database_sha256: Sha256
    static_discovery_sha256: Sha256
    reconciliation_sha256: Sha256
    canonical_layout_sha256: Sha256
    primary_selection_sha256: Sha256
    rows: tuple[DirectBridgeRow, ...]
    coverage: DirectBridgeCoverage
    output_sha256: Sha256


def candidate_sha256(candidate: PublicDirectBridgeCandidate) -> Sha256:
    """Hash the candidate independently of its self-hash field."""
    return sha256_hex(canonical_json(candidate.model_dump(mode="json", exclude={"output_sha256"})))


def build_public_direct_bridge_candidate(inputs: CandidateInputs) -> PublicDirectBridgeCandidate:
    """Return only new, positioned, direct, authorized candidate rows."""
    _require_hash(inputs.public_database, _PUBLIC_DB_SHA256, "public database")
    _require_hash(inputs.static_discovery, _STATIC_SHA256, "static discovery")
    _require_hash(inputs.reconciliation, _RECON_SHA256, "reconciliation")
    _require_hash(inputs.canonical_layout, _LAYOUT_SHA256, "canonical layout")
    static = _load_static(inputs.static_discovery)
    reconciliation = _load_reconciliation(inputs.reconciliation)
    layout = _load_layout(inputs.canonical_layout)
    all_links, resolved_count, positioned_link_count = _safe_positioned_links(
        inputs.public_database, reconciliation, layout
    )
    static_catalog_ids = {genre.catalog_genre_id for genre in static.genres}
    all_direct_rows = _authorized_direct_rows(inputs.public_database, all_links)
    direct_rows = tuple(row for row in all_direct_rows if row[0] not in static_catalog_ids)
    existing_artists = {
        artist.musicbrainz_url.rsplit("/", 1)[-1]
        for artist in static.artists
        if artist.musicbrainz_url is not None
    }
    rows = tuple(
        DirectBridgeRow(
            catalog_genre_id=genre_id,
            source_genre_ref=genre_ref,
            seed_id=seed_id,
            reconciliation_disposition=disposition,
            artist_catalog_id=artist_catalog_id,
            artist_musicbrainz_id=artist_id,
            evidence_id=evidence_id,
            source_key=source_key,
            source_record_id=source_record_id,
            authorization_status="display_and_export_authorized",
            identifier_status="one_authorized_musicbrainz_artist_id",
        )
        for (
            genre_id,
            genre_ref,
            seed_id,
            disposition,
            artist_catalog_id,
            artist_id,
            evidence_id,
            source_key,
            source_record_id,
        ) in direct_rows
    )
    artists = {row.artist_musicbrainz_id for row in rows}
    primary_selection_sha256 = sha256_hex(
        canonical_json(sorted((genre_id, *link) for genre_id, link in all_links.items()))
    )
    coverage = DirectBridgeCoverage(
        resolved_reconciliation_count=resolved_count,
        positioned_seed_link_count=positioned_link_count,
        distinct_catalog_genre_count=len({row.catalog_genre_id for row in rows} | set(all_links)),
        direct_claim_catalog_genre_count=len({row[0] for row in all_direct_rows}),
        already_static_catalog_genre_count=len(
            {row[0] for row in all_direct_rows} & static_catalog_ids
        ),
        new_direct_catalog_genre_count=len({row.catalog_genre_id for row in rows}),
        exact_direct_pair_count=len(rows),
        distinct_artist_count=len(artists),
        net_new_artist_count=len(artists - existing_artists),
    )
    base = PublicDirectBridgeCandidate(
        public_database_sha256=_PUBLIC_DB_SHA256,
        static_discovery_sha256=_STATIC_SHA256,
        reconciliation_sha256=_RECON_SHA256,
        canonical_layout_sha256=_LAYOUT_SHA256,
        primary_selection_sha256=primary_selection_sha256,
        rows=rows,
        coverage=coverage,
        output_sha256="0" * 64,
    )
    candidate = base.model_copy(update={"output_sha256": candidate_sha256(base)})
    if candidate.coverage.model_dump() != {
        "resolved_reconciliation_count": 441,
        "positioned_seed_link_count": 409,
        "distinct_catalog_genre_count": 355,
        "direct_claim_catalog_genre_count": 311,
        "already_static_catalog_genre_count": 227,
        "new_direct_catalog_genre_count": 84,
        "exact_direct_pair_count": 959,
        "distinct_artist_count": 536,
        "net_new_artist_count": 118,
    }:
        raise PublicDirectBridgeCandidateError(
            f"pinned public candidate coverage drifted: {candidate.coverage.model_dump()}"
        )
    return candidate


def _require_hash(path: Path, expected: str, role: str) -> None:
    actual, _ = sha256_file(path)
    if actual != expected:
        raise PublicDirectBridgeCandidateError(f"pinned {role} hash does not match")


def _load_static(path: Path) -> StaticDiscoveryPayload:
    try:
        payload = StaticDiscoveryPayload.model_validate_json(path.read_bytes())
    except (OSError, ValueError) as error:
        raise PublicDirectBridgeCandidateError("static discovery is invalid") from error
    if (
        payload.availability != "ready"
        or payload.source is None
        or payload.source.database_sha256 != _PUBLIC_DB_SHA256
    ):
        raise PublicDirectBridgeCandidateError(
            "static discovery is not bound to the public database"
        )
    return payload


def _load_reconciliation(path: Path) -> _LegacyReconciliation:
    try:
        artifact = _LegacyReconciliation.model_validate_json(path.read_bytes())
    except (OSError, ValueError) as error:
        raise PublicDirectBridgeCandidateError("reconciliation is invalid") from error
    if artifact.output_sha256 != _RECON_LOGICAL_SHA256:
        raise PublicDirectBridgeCandidateError("reconciliation logical hash does not match")
    return artifact


def _load_layout(path: Path) -> SemanticLayoutArtifact:
    try:
        artifact = SemanticLayoutArtifact.model_validate_json(path.read_bytes())
        verify_semantic_map_layout(artifact)
    except (OSError, ValueError) as error:
        raise PublicDirectBridgeCandidateError("canonical layout is invalid") from error
    if artifact.output_sha256 != _LAYOUT_LOGICAL_SHA256:
        raise PublicDirectBridgeCandidateError("canonical layout logical hash does not match")
    return artifact


def _safe_positioned_links(
    database_path: Path, reconciliation: _LegacyReconciliation, layout: SemanticLayoutArtifact
) -> tuple[dict[int, tuple[str, str, Literal["reconciled", "public_only"]]], int, int]:
    candidates: list[tuple[str, str, Literal["reconciled", "public_only"]]] = [
        (
            disposition.public_identities[0].identifier,
            disposition.source_item_id,
            disposition.disposition,
        )
        for disposition in reconciliation.dispositions
        if disposition.disposition in {"reconciled", "public_only"}
        and len(disposition.public_identities) == 1
        and disposition.public_identities[0].namespace == "wikidata_genre_qid"
    ]
    positioned = {coordinate.seed_id for coordinate in layout.coordinates}
    positioned_candidates = [item for item in candidates if item[1] in positioned]
    resolved = _resolved_genre_ids(database_path)
    # Several exact QID aliases can resolve to one DB genre. A genre with
    # different positioned seed IDs has no single truthful map context, so
    # omit it from automatic candidate rows rather than choosing arbitrarily.
    grouped: dict[int, list[tuple[str, str, Literal["reconciled", "public_only"]]]] = defaultdict(
        list
    )
    resolved_candidate_count = sum(genre_ref in resolved for genre_ref, _, _ in candidates)
    for genre_ref, seed_id, disposition in positioned_candidates:
        if (genre_id := resolved.get(genre_ref)) is not None:
            grouped[genre_id].append((genre_ref, seed_id, disposition))
    unambiguous = {
        genre_id: values[0]
        for genre_id, values in grouped.items()
        if len({seed_id for _, seed_id, _ in values}) == 1
    }
    return (
        unambiguous,
        resolved_candidate_count,
        sum(genre_ref in resolved for genre_ref, _, _ in positioned_candidates),
    )


def _resolved_genre_ids(database_path: Path) -> dict[str, int]:
    with closing(
        sqlite3.connect(f"file:{database_path.resolve()}?mode=ro&immutable=1", uri=True)
    ) as database:
        rows = database.execute(
            """SELECT 'wikidata:genre:' || identifier.normalized_value, identifier.entity_id
               FROM entity_identifiers AS identifier
               JOIN identifier_types AS type ON type.id = identifier.identifier_type_id
               JOIN genres AS genre ON genre.id = identifier.entity_id
               WHERE type.type_key = 'wikidata_genre_qid' AND identifier.namespace = 'wikidata'
               GROUP BY identifier.normalized_value
               HAVING count(DISTINCT identifier.entity_id) = 1"""
        ).fetchall()
    return {str(ref): int(genre_id) for ref, genre_id in rows}


def _authorized_direct_rows(
    database_path: Path,
    links: dict[int, tuple[str, str, Literal["reconciled", "public_only"]]],
) -> tuple[
    tuple[int, str, str, Literal["reconciled", "public_only"], int, str, int, str, str], ...
]:
    with closing(
        sqlite3.connect(f"file:{database_path.resolve()}?mode=ro&immutable=1", uri=True)
    ) as database:
        rows = database.execute(
            """WITH authorized_artist_mbid AS (
                   SELECT identifier.entity_id, identifier.normalized_value
                   FROM entity_identifiers AS identifier
                   JOIN identifier_types AS type ON type.id = identifier.identifier_type_id
                   JOIN provenance_records AS provenance ON provenance.id = identifier.provenance_id
                   JOIN active_rights_policy_permissions AS export_permission
                     ON export_permission.policy_id = provenance.policy_id
                    AND export_permission.use_kind = 'export'
                    AND export_permission.decision = 'allow'
                   JOIN active_rights_policy_permissions AS display_permission
                     ON display_permission.policy_id = provenance.policy_id
                    AND display_permission.use_kind = 'display'
                    AND display_permission.decision = 'allow'
                   WHERE type.type_key = 'musicbrainz_artist_id'
                     AND identifier.namespace = 'musicbrainz'
                   GROUP BY identifier.entity_id
                   HAVING count(DISTINCT identifier.normalized_value) = 1
               )
               SELECT evidence.genre_id, evidence.artist_id, mbid.normalized_value,
                      evidence.id, evidence.source_key, evidence.source_record_id
               FROM displayable_artist_genre_evidence AS evidence
               JOIN provenance_records AS provenance ON provenance.id = evidence.provenance_id
               JOIN active_rights_policy_permissions AS export_permission
                 ON export_permission.policy_id = provenance.policy_id
                AND export_permission.use_kind = 'export' AND export_permission.decision = 'allow'
               JOIN active_rights_policy_permissions AS display_permission
                 ON display_permission.policy_id = provenance.policy_id
                 AND display_permission.use_kind = 'display'
                 AND display_permission.decision = 'allow'
               JOIN authorized_artist_mbid AS mbid
                 ON mbid.entity_id = evidence.artist_id
               WHERE evidence.evidence_kind = 'direct_source_claim'
                 AND evidence.method_key = 'wikidata_p136'
                 AND evidence.method_version = '1'
               ORDER BY evidence.genre_id, evidence.artist_id, evidence.id"""
        ).fetchall()
    selected = []
    for genre_id, artist_catalog_id, artist_id, evidence_id, source_key, source_record_id in rows:
        link = links.get(int(genre_id))
        if link is None:
            continue
        genre_ref, seed_id, disposition = link
        selected.append(
            (
                int(genre_id),
                genre_ref,
                seed_id,
                disposition,
                int(artist_catalog_id),
                str(artist_id),
                int(evidence_id),
                str(source_key),
                str(source_record_id),
            )
        )
    return tuple(selected)
