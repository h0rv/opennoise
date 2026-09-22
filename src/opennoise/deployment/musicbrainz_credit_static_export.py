"""Gate a narrowly scoped static export of verified MusicBrainz credit metadata.

This module is intentionally separate from direct artist discovery.  Exact
MusicBrainz artist-ID equality only permits a metadata row for an artist that
is already visible; it never transfers a genre, membership, score, rank, or
representative claim from the local catalog candidate.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from opennoise.deployment.public_static_discovery_v2 import (
    PublicStaticDiscoveryV2Payload,
    verify_public_static_discovery_v2_payload,
)
from opennoise.ingest.musicbrainz.artist_credit_catalog_candidate import (
    ArtistCreditCatalogReport,
)
from opennoise.models import FrozenModel

_REVISION = "musicbrainz-credit-static-metadata-v1"
_MBID_PREFIX = "https://musicbrainz.org/artist/"
_MBID_LENGTH = 36


class MusicBrainzCreditStaticExportError(RuntimeError):
    """Report a failed-closed local-candidate publication boundary."""


class CreditMetadataPublicationApproval(FrozenModel):
    """One explicit release decision, bound to all candidate and public inputs."""

    revision: Literal["musicbrainz-credit-static-metadata-approval-v1"] = (
        "musicbrainz-credit-static-metadata-approval-v1"
    )
    decision: Literal["approved"]
    candidate_database_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    candidate_report_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    public_database_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    static_discovery_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    credit_artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    approved_policy_key: str = Field(min_length=1)
    approved_use: Literal["musicbrainz_credit_metadata_artist_detail"] = (
        "musicbrainz_credit_metadata_artist_detail"
    )


class MusicBrainzCreditMemberPayload(FrozenModel):
    """One ordered, source-observed credit member."""

    position: int = Field(ge=0)
    musicbrainz_artist_id: str = Field(pattern=r"^[0-9a-f-]{36}$")
    credited_name: str = Field(min_length=1)
    join_phrase: str


class MusicBrainzCreditMetadataRow(FrozenModel):
    """Metadata for one already-visible artist, with no discovery semantics."""

    static_artist_id: str = Field(min_length=1)
    musicbrainz_artist_id: str = Field(pattern=r"^[0-9a-f-]{36}$")
    entity_kind: Literal["release", "recording"]
    musicbrainz_entity_id: str = Field(pattern=r"^[0-9a-f-]{36}$")
    title: str = Field(min_length=1)
    credit_record_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    credit_artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    credit_members: tuple[MusicBrainzCreditMemberPayload, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def require_ordered_members(self) -> MusicBrainzCreditMetadataRow:
        """Reject a credit whose stored source order is incomplete or ambiguous."""
        if tuple(member.position for member in self.credit_members) != tuple(
            range(len(self.credit_members))
        ):
            raise ValueError("credit members must have contiguous source order")
        return self


class MusicBrainzCreditStaticMetadataPayload(FrozenModel):
    """Optional artist-detail-only static asset, produced only after approval."""

    revision: Literal["musicbrainz-credit-static-metadata-v1"] = _REVISION
    scope: Literal["artist_detail_only"] = "artist_detail_only"
    label: Literal["MusicBrainz credit metadata"] = "MusicBrainz credit metadata"
    candidate_database_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    public_database_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    static_discovery_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    visible_artist_count: int = Field(ge=0)
    artists_with_credit_rows_count: int = Field(ge=0)
    release_row_count: int = Field(ge=0)
    recording_row_count: int = Field(ge=0)
    rows: tuple[MusicBrainzCreditMetadataRow, ...]


def sha256_file(path: Path) -> str:
    """Hash one file without treating any path as an implicit trusted input."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def build_musicbrainz_credit_static_metadata(
    *,
    candidate_database: Path,
    candidate_report: Path,
    public_database: Path,
    static_discovery: Path,
    approval: CreditMetadataPublicationApproval,
) -> MusicBrainzCreditStaticMetadataPayload:
    """Verify all boundaries and return a safe optional static payload in memory.

    Callers still own publication.  A missing approval, policy permission, or
    exact ID join raises before an output file can be created.
    """
    candidate_hash = sha256_file(candidate_database)
    report_bytes = candidate_report.read_bytes()
    report_hash = hashlib.sha256(report_bytes).hexdigest()
    public_hash = sha256_file(public_database)
    static_bytes = static_discovery.read_bytes()
    static_hash = hashlib.sha256(static_bytes).hexdigest()
    _require_hashes(approval, candidate_hash, report_hash, public_hash, static_hash)
    try:
        report = ArtistCreditCatalogReport.model_validate_json(report_bytes)
        discovery = _parse_discovery(static_bytes)
    except ValueError as error:
        raise MusicBrainzCreditStaticExportError(
            "publication input is not a valid typed artifact"
        ) from error
    if report.database_sha256 != candidate_hash:
        raise MusicBrainzCreditStaticExportError(
            "candidate report does not bind candidate database bytes"
        )
    if report.source_credit_sha256 != approval.credit_artifact_sha256:
        raise MusicBrainzCreditStaticExportError("approval does not bind candidate credit artifact")
    if (
        report.foreign_key_violations != 0
        or report.sealed_database_mutated
        or report.verified_cache_projections == 0
        or report.ordered_credit_members == 0
        or report.content_policy != "core_metadata_only_no_audio_preview_artwork_or_genres"
    ):
        raise MusicBrainzCreditStaticExportError(
            "candidate report does not meet metadata release gate"
        )
    if discovery.availability != "ready" or discovery.source is None:
        raise MusicBrainzCreditStaticExportError("static discovery is not ready")
    if discovery.source.observation_kind != "direct_source_claim":
        raise MusicBrainzCreditStaticExportError("static discovery lacks direct-source scope")
    if discovery.source.database_sha256 != public_hash:
        raise MusicBrainzCreditStaticExportError(
            "static discovery is bound to a different public database"
        )
    visible = _visible_artists(discovery)
    rows = _credit_rows(candidate_database, visible, approval)
    if not rows:
        raise MusicBrainzCreditStaticExportError("exact-ID credit export has no visible rows")
    return MusicBrainzCreditStaticMetadataPayload(
        candidate_database_sha256=candidate_hash,
        public_database_sha256=public_hash,
        static_discovery_sha256=static_hash,
        visible_artist_count=len(visible),
        artists_with_credit_rows_count=len({row.static_artist_id for row in rows}),
        release_row_count=sum(row.entity_kind == "release" for row in rows),
        recording_row_count=sum(row.entity_kind == "recording" for row in rows),
        rows=rows,
    )


def export_musicbrainz_credit_static_metadata(  # noqa: PLR0913 - checked release boundary inputs.
    *,
    candidate_database: Path,
    candidate_report: Path,
    public_database: Path,
    static_discovery: Path,
    approval: CreditMetadataPublicationApproval,
    output: Path,
) -> tuple[MusicBrainzCreditStaticMetadataPayload, str]:
    """Build and no-replace write one asset through the complete checked boundary."""
    payload = build_musicbrainz_credit_static_metadata(
        candidate_database=candidate_database,
        candidate_report=candidate_report,
        public_database=public_database,
        static_discovery=static_discovery,
        approval=approval,
    )
    return payload, _write_musicbrainz_credit_static_metadata(payload, output=output)


def _write_musicbrainz_credit_static_metadata(
    payload: MusicBrainzCreditStaticMetadataPayload, *, output: Path
) -> str:
    """No-replace write of an asset that has already passed this module's gate."""
    if output.exists() or output.is_symlink():
        raise MusicBrainzCreditStaticExportError("static metadata output already exists")
    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{output.name}.", suffix=".staging", dir=output.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            encoded = (payload.model_dump_json() + "\n").encode()
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, output)
        except FileExistsError as error:
            raise MusicBrainzCreditStaticExportError(
                "static metadata output already exists"
            ) from error
        return hashlib.sha256(encoded).hexdigest()
    finally:
        temporary.unlink(missing_ok=True)


def _require_hashes(
    approval: CreditMetadataPublicationApproval,
    candidate_hash: str,
    report_hash: str,
    public_hash: str,
    static_hash: str,
) -> None:
    if (
        approval.candidate_database_sha256,
        approval.candidate_report_sha256,
        approval.public_database_sha256,
        approval.static_discovery_sha256,
    ) != (candidate_hash, report_hash, public_hash, static_hash):
        raise MusicBrainzCreditStaticExportError(
            "publication approval does not bind current inputs"
        )


def _parse_discovery(payload: bytes) -> PublicStaticDiscoveryV2Payload:
    """Parse and semantically replay the sole supported public v2 discovery asset."""
    try:
        revision = json.loads(payload)["revision"]
    except (json.JSONDecodeError, KeyError, TypeError) as error:
        raise MusicBrainzCreditStaticExportError("static discovery has no revision") from error
    if revision == "static-direct-discovery-v2":
        discovery = PublicStaticDiscoveryV2Payload.model_validate_json(payload)
        verify_public_static_discovery_v2_payload(
            discovery, frozenset(genre.node_id for genre in discovery.genres)
        )
        return discovery
    raise MusicBrainzCreditStaticExportError("static discovery must be public v2")


def _visible_artists(discovery: PublicStaticDiscoveryV2Payload) -> dict[str, str]:
    visible: dict[str, str] = {}
    for artist in discovery.artists:
        if artist.musicbrainz_url is None:
            continue
        mbid = artist.musicbrainz_url.removeprefix(_MBID_PREFIX)
        if len(mbid) != _MBID_LENGTH:
            raise MusicBrainzCreditStaticExportError("static artist has an invalid MusicBrainz ID")
        if mbid in visible:
            raise MusicBrainzCreditStaticExportError(
                "static discovery repeats a MusicBrainz artist ID"
            )
        visible[mbid] = artist.artist_id
    return visible


def _credit_rows(
    database: Path, visible: dict[str, str], approval: CreditMetadataPublicationApproval
) -> tuple[MusicBrainzCreditMetadataRow, ...]:
    if not visible:
        return ()
    uri = f"file:{database.resolve(strict=True).as_posix()}?mode=ro&immutable=1"
    try:
        with closing(sqlite3.connect(uri, uri=True)) as connection:
            connection.row_factory = sqlite3.Row
            records = connection.execute(
                _CREDIT_ROWS_SQL,
                (approval.credit_artifact_sha256, approval.approved_policy_key),
            ).fetchall()
    except sqlite3.Error as error:
        raise MusicBrainzCreditStaticExportError(
            "candidate lacks verified artist-credit catalog data"
        ) from error
    grouped: dict[tuple[str, str, str, str, str, str], list[MusicBrainzCreditMemberPayload]] = {}
    titles: dict[tuple[str, str, str, str, str, str], str] = {}
    for record in records:
        artist_mbid = str(record["visible_artist_mbid"])
        static_artist_id = visible.get(artist_mbid)
        if static_artist_id is None:
            continue
        key = (
            static_artist_id,
            artist_mbid,
            str(record["entity_kind"]),
            str(record["entity_mbid"]),
            str(record["record_fingerprint"]),
            str(record["credit_artifact_sha256"]),
        )
        title = str(record["title"])
        previous_title = titles.setdefault(key, title)
        if previous_title != title:
            raise MusicBrainzCreditStaticExportError(
                "verified credit entity has conflicting titles"
            )
        grouped.setdefault(key, []).append(
            MusicBrainzCreditMemberPayload(
                position=int(record["member_position"]),
                musicbrainz_artist_id=str(record["member_mbid"]),
                credited_name=str(record["credited_name"]),
                join_phrase=str(record["join_phrase"]),
            )
        )
    return tuple(
        MusicBrainzCreditMetadataRow(
            static_artist_id=static_artist_id,
            musicbrainz_artist_id=artist_mbid,
            entity_kind=_entity_kind(entity_kind),
            musicbrainz_entity_id=entity_mbid,
            title=titles[
                (
                    static_artist_id,
                    artist_mbid,
                    entity_kind,
                    entity_mbid,
                    fingerprint,
                    artifact_sha256,
                )
            ],
            credit_record_fingerprint=fingerprint,
            credit_artifact_sha256=artifact_sha256,
            credit_members=tuple(sorted(members, key=lambda member: member.position)),
        )
        for (
            static_artist_id,
            artist_mbid,
            entity_kind,
            entity_mbid,
            fingerprint,
            artifact_sha256,
        ), members in sorted(grouped.items())
    )


def _entity_kind(value: str) -> Literal["release", "recording"]:
    match value:
        case "release" | "recording":
            return value
        case _:
            raise MusicBrainzCreditStaticExportError("verified credit has an invalid entity kind")


_CREDIT_ROWS_SQL = """
SELECT visible_identifier.normalized_value AS visible_artist_mbid,
       entity.entity_kind, entity_identifier.normalized_value AS entity_mbid,
       (SELECT title.name FROM entity_names AS title
        WHERE title.entity_id = entity.id
        ORDER BY title.is_preferred DESC, title.id LIMIT 1) AS title,
       provenance.record_fingerprint, provenance.artifact_sha256 AS credit_artifact_sha256,
       member.position AS member_position,
       member_identifier.normalized_value AS member_mbid,
       member.credited_name, member.join_phrase
FROM entity_artist_credits AS link
JOIN provenance_records AS provenance ON provenance.id = link.provenance_id
JOIN rights_policies AS policy ON policy.id = provenance.policy_id
JOIN active_rights_policy_permissions AS display_permission
  ON display_permission.policy_id = policy.id
 AND display_permission.use_kind = 'display' AND display_permission.decision = 'allow'
JOIN active_rights_policy_permissions AS export_permission
  ON export_permission.policy_id = policy.id
 AND export_permission.use_kind = 'export' AND export_permission.decision = 'allow'
JOIN catalog_entities AS entity ON entity.id = link.entity_id
JOIN entity_identifiers AS entity_identifier ON entity_identifier.entity_id = entity.id
JOIN identifier_types AS entity_type ON entity_type.id = entity_identifier.identifier_type_id
JOIN artist_credit_members AS member ON member.artist_credit_id = link.artist_credit_id
JOIN entity_identifiers AS member_identifier ON member_identifier.entity_id = member.artist_id
JOIN identifier_types AS member_type ON member_type.id = member_identifier.identifier_type_id
JOIN artist_credit_members AS visible_member
  ON visible_member.artist_credit_id = link.artist_credit_id
JOIN entity_identifiers AS visible_identifier
  ON visible_identifier.entity_id = visible_member.artist_id
JOIN identifier_types AS visible_type ON visible_type.id = visible_identifier.identifier_type_id
WHERE provenance.artifact_sha256 = ?
  AND policy.local_only = 0
  AND policy.policy_key = ?
  AND entity.entity_kind IN ('release', 'recording')
  AND entity_type.type_key = 'musicbrainz_' || entity.entity_kind || '_id'
  AND member_type.type_key = 'musicbrainz_artist_id'
  AND visible_type.type_key = 'musicbrainz_artist_id'
  AND (SELECT title.name FROM entity_names AS title
       WHERE title.entity_id = entity.id
       ORDER BY title.is_preferred DESC, title.id LIMIT 1) IS NOT NULL
ORDER BY visible_identifier.normalized_value, entity.entity_kind,
         entity_identifier.normalized_value, link.provenance_id, member.position
"""
