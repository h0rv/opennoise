"""Join sealed release-group genre support to exact local release credits.

This is a local research report, not a membership projection.  A MusicBrainz
genre/tag association belongs to a release group, while the independently
cached release and recording credits identify who is credited on a particular
catalog entity.  A row exists only when the two sources share the same exact
MusicBrainz artist ID; it never turns that contextual association into an
artist-direct genre claim.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections import defaultdict
from contextlib import closing
from typing import TYPE_CHECKING, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from opennoise.ingest.musicbrainz.artist_credit_catalog_candidate import (
    ARTIST_CREDIT_V2_SHA256,
    CORE_HYDRATION_SHA256,
    ArtistCreditCatalogReport,
)
from opennoise.ingest.musicbrainz.release_group_evidence import (
    ReleaseGroupEvidenceArtifact,
    verify_release_group_evidence,
)

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

_REVISION: Final = "musicbrainz-release-credit-genre-report-v1"
_CATALOG_CONTENT_POLICY: Final = "core_metadata_only_no_audio_preview_artwork_or_genres"
_SHA256: Final = r"^[0-9a-f]{64}$"
_EVIDENCE_ARTIFACT_SHA256: Final = (
    "0a626b524a2e5976f47be13b29b8d44b1dabe54098443512b548c1abd4348de6"
)
_EVIDENCE_DATABASE_SHA256: Final = (
    "980b2c58e16b024d282ca1acc58b98dcab292f0e1a50917812d1b59df0340c8a"
)
_CATALOG_REPORT_SHA256: Final = "f9ab6d74552935ecf198e28ea9f3875caf67cfcad9ee95883328c59954fcde00"
_CATALOG_DATABASE_SHA256: Final = "100af6ec48bae689eb5567e66648edf96dde74a7e06e76c2c32abd195eaf7a63"

type CatalogEntityKind = Literal["release", "recording"]
type GenreFacet = Literal["musicbrainz_genre", "musicbrainz_tag"]


class _FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")


class ReleaseCreditGenreReportError(ValueError):
    """A local report input does not prove its declared source role."""


class ReleaseCreditGenreExpectedInputs(_FrozenModel):
    """Byte identities of the retained, local research inputs."""

    evidence_artifact_sha256: str = Field(pattern=_SHA256)
    evidence_database_sha256: str = Field(pattern=_SHA256)
    credit_catalog_report_sha256: str = Field(pattern=_SHA256)
    credit_catalog_database_sha256: str = Field(pattern=_SHA256)


DEFAULT_EXPECTED_INPUTS: Final = ReleaseCreditGenreExpectedInputs(
    evidence_artifact_sha256=_EVIDENCE_ARTIFACT_SHA256,
    evidence_database_sha256=_EVIDENCE_DATABASE_SHA256,
    credit_catalog_report_sha256=_CATALOG_REPORT_SHA256,
    credit_catalog_database_sha256=_CATALOG_DATABASE_SHA256,
)


class ArtistCredit(_FrozenModel):
    """One entity-level credit from the cache-verified core metadata catalog."""

    artist_mbid: str = Field(pattern=r"^[0-9a-f]{8}-[0-9a-f-]{27}$")
    artist_name: str = Field(min_length=1)
    credited_name: str = Field(min_length=1)
    credit_position: int = Field(ge=0)


class ReleaseCreditGenreRow(_FrozenModel):
    """A contextual release-group label plus an exact matching entity credit."""

    release_group_mbid: str = Field(pattern=r"^[0-9a-f]{8}-[0-9a-f-]{27}$")
    genre_id: str = Field(min_length=1)
    genre_facet: GenreFacet
    release_group_evidence_ref: str = Field(min_length=1)
    support_artist_mbid: str = Field(pattern=r"^[0-9a-f]{8}-[0-9a-f-]{27}$")
    entity_kind: CatalogEntityKind
    entity_mbid: str = Field(pattern=r"^[0-9a-f]{8}-[0-9a-f-]{27}$")
    entity_title: str = Field(min_length=1)
    entity_credit: ArtistCredit
    genre_claim_role: Literal["release_group_contextual_support"] = (
        "release_group_contextual_support"
    )
    entity_credit_role: Literal["cached_core_artist_credit"] = "cached_core_artist_credit"
    direct_artist_membership: Literal[False] = False


class ReleaseCreditGenreReport(_FrozenModel):
    """Hash-bound local-only result of the two-source exact-ID join."""

    revision: Literal["musicbrainz-release-credit-genre-report-v1"] = _REVISION
    export_allowed: Literal[False] = False
    serving_allowed: Literal[False] = False
    evidence_artifact_file_sha256: str = Field(pattern=_SHA256)
    evidence_artifact_sha256: str = Field(pattern=_SHA256)
    evidence_database_sha256: str = Field(pattern=_SHA256)
    credit_catalog_report_sha256: str = Field(pattern=_SHA256)
    credit_catalog_database_sha256: str = Field(pattern=_SHA256)
    credit_catalog_hydration_sha256: str = Field(pattern=_SHA256)
    credit_catalog_credit_sha256: str = Field(pattern=_SHA256)
    release_group_count: int = Field(ge=0)
    support_claim_count: int = Field(ge=0)
    exact_credit_match_count: int = Field(ge=0)
    rows: tuple[ReleaseCreditGenreRow, ...]
    output_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def _matches_row_count(self) -> ReleaseCreditGenreReport:
        if self.exact_credit_match_count != len(self.rows):
            raise ValueError("exact credit match count does not equal report row count")
        return self


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _logical_sha256(report: ReleaseCreditGenreReport) -> str:
    payload = report.model_dump(mode="json", exclude={"output_sha256"})
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()


def verify_release_credit_genre_report(report: ReleaseCreditGenreReport) -> None:
    """Fail closed if a persisted local report does not replay its logical hash."""
    if _logical_sha256(report) != report.output_sha256:
        raise ReleaseCreditGenreReportError("release-credit genre report hash does not replay")


def _require_file_sha256(path: Path, expected: str, label: str) -> None:
    if not path.is_file() or path.is_symlink() or _sha256_file(path) != expected:
        raise ReleaseCreditGenreReportError(f"{label} SHA-256 does not match the pinned input")


def _read_pinned_bytes(path: Path, expected: str, label: str) -> bytes:
    """Read once, then parse the exact receipt bytes whose digest was verified."""
    if not path.is_file() or path.is_symlink():
        raise ReleaseCreditGenreReportError(f"{label} is not a regular local file")
    try:
        payload = path.read_bytes()
    except OSError as error:
        raise ReleaseCreditGenreReportError(f"{label} cannot be read") from error
    if hashlib.sha256(payload).hexdigest() != expected:
        raise ReleaseCreditGenreReportError(f"{label} SHA-256 does not match the pinned input")
    return payload


def _readonly_connection(path: Path) -> sqlite3.Connection:
    if not path.is_file() or path.is_symlink():
        raise ReleaseCreditGenreReportError("report input must be a regular local file")
    return sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)


def _genre_facet(value: str) -> GenreFacet:
    if value in {"musicbrainz_genre", "musicbrainz_tag"}:
        return value
    raise ReleaseCreditGenreReportError("release-group support has an unknown genre facet")


def _catalog_entity_kind(value: str) -> CatalogEntityKind:
    if value in {"release", "recording"}:
        return value
    raise ReleaseCreditGenreReportError("credit catalog has an unknown entity kind")


def _verify_inputs(
    *,
    evidence_database: Path,
    evidence_artifact_path: Path,
    credit_catalog_database: Path,
    credit_catalog_report_path: Path,
    expected_inputs: ReleaseCreditGenreExpectedInputs,
) -> tuple[ReleaseGroupEvidenceArtifact, ArtistCreditCatalogReport]:
    evidence_artifact_bytes = _read_pinned_bytes(
        evidence_artifact_path, expected_inputs.evidence_artifact_sha256, "evidence artifact"
    )
    _require_file_sha256(
        evidence_database, expected_inputs.evidence_database_sha256, "evidence database"
    )
    credit_catalog_report_bytes = _read_pinned_bytes(
        credit_catalog_report_path,
        expected_inputs.credit_catalog_report_sha256,
        "credit catalog report",
    )
    _require_file_sha256(
        credit_catalog_database,
        expected_inputs.credit_catalog_database_sha256,
        "credit catalog database",
    )
    try:
        artifact = ReleaseGroupEvidenceArtifact.model_validate_json(evidence_artifact_bytes)
        catalog = ArtistCreditCatalogReport.model_validate_json(credit_catalog_report_bytes)
    except (OSError, ValueError) as error:
        raise ReleaseCreditGenreReportError("report receipt is invalid") from error
    verify_release_group_evidence(artifact)
    if artifact.evidence_database_sha256 != expected_inputs.evidence_database_sha256:
        raise ReleaseCreditGenreReportError("evidence database SHA-256 does not match its artifact")
    if catalog.database_sha256 != expected_inputs.credit_catalog_database_sha256:
        raise ReleaseCreditGenreReportError("credit catalog SHA-256 does not match its report")
    if (
        catalog.source_hydration_sha256 != CORE_HYDRATION_SHA256
        or catalog.source_credit_sha256 != ARTIST_CREDIT_V2_SHA256
        or catalog.content_policy != _CATALOG_CONTENT_POLICY
        or catalog.sealed_database_mutated
    ):
        raise ReleaseCreditGenreReportError(
            "credit catalog does not have the pinned core-credit role"
        )
    return artifact, catalog


def _catalog_credits(
    connection: sqlite3.Connection,
) -> tuple[tuple[str, str, str, str, ArtistCredit], ...]:
    """Return exact-ID credit rows keyed by release group and credited artist."""
    query = """
        WITH release_entities AS (
            SELECT group_identifier.normalized_value AS release_group_mbid,
                   'release' AS entity_kind,
                   release_identifier.normalized_value AS entity_mbid,
                   release_name.name AS entity_title,
                   credit.artist_credit_id
              FROM releases AS release
              JOIN entity_identifiers AS group_identifier
                ON group_identifier.entity_id = release.release_group_id
              JOIN identifier_types AS group_identifier_type
                ON group_identifier_type.id = group_identifier.identifier_type_id
              JOIN entity_identifiers AS release_identifier
                ON release_identifier.entity_id = release.id
              JOIN identifier_types AS release_identifier_type
                ON release_identifier_type.id = release_identifier.identifier_type_id
              JOIN entity_names AS release_name ON release_name.entity_id = release.id
              JOIN entity_artist_credits AS credit ON credit.entity_id = release.id
             WHERE group_identifier_type.type_key = 'musicbrainz_release_group_id'
               AND release_identifier_type.type_key = 'musicbrainz_release_id'
               AND release_name.name_kind = 'primary' AND release_name.is_preferred = 1
        ), recording_entities AS (
            SELECT group_identifier.normalized_value AS release_group_mbid,
                   'recording' AS entity_kind,
                   recording_identifier.normalized_value AS entity_mbid,
                   recording_name.name AS entity_title,
                   credit.artist_credit_id
              FROM releases AS release
              JOIN media ON media.release_id = release.id
              JOIN tracks ON tracks.medium_id = media.id
              JOIN entity_identifiers AS group_identifier
                ON group_identifier.entity_id = release.release_group_id
              JOIN identifier_types AS group_identifier_type
                ON group_identifier_type.id = group_identifier.identifier_type_id
              JOIN entity_identifiers AS recording_identifier
                ON recording_identifier.entity_id = tracks.recording_id
              JOIN identifier_types AS recording_identifier_type
                ON recording_identifier_type.id = recording_identifier.identifier_type_id
              JOIN entity_names AS recording_name ON recording_name.entity_id = tracks.recording_id
              JOIN entity_artist_credits AS credit ON credit.entity_id = tracks.recording_id
             WHERE group_identifier_type.type_key = 'musicbrainz_release_group_id'
               AND recording_identifier_type.type_key = 'musicbrainz_recording_id'
               AND recording_name.name_kind = 'primary' AND recording_name.is_preferred = 1
        )
        SELECT DISTINCT entity.release_group_mbid, entity.entity_kind, entity.entity_mbid,
               entity.entity_title, artist_identifier.normalized_value, artist_name.name,
               member.credited_name, member.position
          FROM (SELECT * FROM release_entities UNION ALL SELECT * FROM recording_entities) AS entity
          JOIN artist_credit_members AS member ON member.artist_credit_id = entity.artist_credit_id
          JOIN entity_identifiers AS artist_identifier
            ON artist_identifier.entity_id = member.artist_id
          JOIN identifier_types AS artist_identifier_type
            ON artist_identifier_type.id = artist_identifier.identifier_type_id
          JOIN entity_names AS artist_name ON artist_name.entity_id = member.artist_id
         WHERE artist_identifier_type.type_key = 'musicbrainz_artist_id'
           AND artist_name.name_kind = 'primary' AND artist_name.is_preferred = 1
         ORDER BY entity.release_group_mbid, entity.entity_kind, entity.entity_mbid, member.position
    """
    return tuple(
        (
            str(row[0]),
            str(row[1]),
            str(row[2]),
            str(row[3]),
            ArtistCredit(
                artist_mbid=str(row[4]),
                artist_name=str(row[5]),
                credited_name=str(row[6]),
                credit_position=int(row[7]),
            ),
        )
        for row in connection.execute(query)
    )


def _support_claims(
    connection: sqlite3.Connection, release_groups: Iterable[str]
) -> tuple[tuple[str, str, GenreFacet, str, str], ...]:
    groups = tuple(sorted(set(release_groups)))
    if not groups:
        return ()
    connection.execute("CREATE TEMP TABLE requested_release_group (mbid TEXT PRIMARY KEY)")
    connection.executemany(
        "INSERT INTO requested_release_group (mbid) VALUES (?)", ((group,) for group in groups)
    )
    rows = connection.execute(
        """SELECT support.release_group_id, support.artist_id, support.facet,
                  support.genre_id, support.evidence_ref
             FROM release_group_support AS support
             JOIN requested_release_group AS requested ON requested.mbid = support.release_group_id
            ORDER BY support.release_group_id, support.artist_id, support.genre_id, support.facet"""
    )
    return tuple(
        (str(row[0]), str(row[1]), _genre_facet(str(row[2])), str(row[3]), str(row[4]))
        for row in rows
    )


def build_release_credit_genre_report(
    *,
    evidence_database: Path,
    evidence_artifact_path: Path,
    credit_catalog_database: Path,
    credit_catalog_report_path: Path,
    expected_inputs: ReleaseCreditGenreExpectedInputs = DEFAULT_EXPECTED_INPUTS,
) -> ReleaseCreditGenreReport:
    """Build an exact-MBID, local-only contextual report from pinned receipts."""
    artifact, catalog = _verify_inputs(
        evidence_database=evidence_database,
        evidence_artifact_path=evidence_artifact_path,
        credit_catalog_database=credit_catalog_database,
        credit_catalog_report_path=credit_catalog_report_path,
        expected_inputs=expected_inputs,
    )
    with closing(_readonly_connection(credit_catalog_database)) as catalog_connection:
        catalog_credit_rows = _catalog_credits(catalog_connection)
    by_group_artist: dict[tuple[str, str], list[tuple[str, str, str, ArtistCredit]]] = defaultdict(
        list
    )
    for group, kind, entity, title, credit in catalog_credit_rows:
        by_group_artist[(group, credit.artist_mbid)].append((kind, entity, title, credit))
    with closing(_readonly_connection(evidence_database)) as evidence_connection:
        claims = _support_claims(evidence_connection, (group for group, *_ in catalog_credit_rows))
    _require_file_sha256(
        evidence_database, expected_inputs.evidence_database_sha256, "evidence database after query"
    )
    _require_file_sha256(
        credit_catalog_database,
        expected_inputs.credit_catalog_database_sha256,
        "credit catalog database after query",
    )
    rows = tuple(
        ReleaseCreditGenreRow(
            release_group_mbid=group,
            genre_id=genre_id,
            genre_facet=facet,
            release_group_evidence_ref=evidence_ref,
            support_artist_mbid=artist,
            entity_kind=_catalog_entity_kind(kind),
            entity_mbid=entity,
            entity_title=title,
            entity_credit=credit,
        )
        for group, artist, facet, genre_id, evidence_ref in claims
        for kind, entity, title, credit in by_group_artist.get((group, artist), ())
    )
    unsealed = ReleaseCreditGenreReport(
        evidence_artifact_file_sha256=expected_inputs.evidence_artifact_sha256,
        evidence_artifact_sha256=artifact.output_sha256,
        evidence_database_sha256=artifact.evidence_database_sha256,
        credit_catalog_report_sha256=expected_inputs.credit_catalog_report_sha256,
        credit_catalog_database_sha256=catalog.database_sha256,
        credit_catalog_hydration_sha256=catalog.source_hydration_sha256,
        credit_catalog_credit_sha256=catalog.source_credit_sha256,
        release_group_count=len({group for group, *_ in catalog_credit_rows}),
        support_claim_count=len(claims),
        exact_credit_match_count=len(rows),
        rows=rows,
        output_sha256="0" * 64,
    )
    return unsealed.model_copy(update={"output_sha256": _logical_sha256(unsealed)})
