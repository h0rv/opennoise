"""Counts-only exact-ID overlap audit for the AcousticBrainz Discogs validation TSV.

The source's label fields are deliberately neither parsed nor retained.  This
module establishes only identifier and release-group bridge coverage.
"""

from __future__ import annotations

import bz2
import hashlib
import sqlite3
from collections import Counter
from pathlib import Path  # noqa: TC003  # Pydantic resolves this annotation at definition.
from uuid import UUID

from pydantic import Field

from opennoise.models import FrozenModel
from opennoise.types import (
    Sha256,  # noqa: TC001  # Pydantic resolves this annotation at definition.
)

_RECORDING_IDENTIFIER_TYPE = "musicbrainz_recording_id"
_RELEASE_GROUP_IDENTIFIER_TYPE = "musicbrainz_release_group_id"
_SOURCE_URL = (
    "https://zenodo.org/records/2553414/files/"
    "acousticbrainz-mediaeval-discogs-validation.tsv.bz2?download=1"
)
_PUBLISHED_MD5 = "1b9ae2055c3b4b32c5219ee93992de9e"
_MAXIMUM_COMPRESSED_BYTES = 10 * 1024 * 1024
_MAXIMUM_DECOMPRESSED_BYTES = 32 * 1024 * 1024
_MAXIMUM_SOURCE_ROWS = 200_000
_MAXIMUM_LINE_BYTES = 16 * 1024


class AcousticBrainzDiscogsOverlapError(RuntimeError):
    """Raised when either bounded source cannot support an exact-ID audit."""


class AcousticBrainzDiscogsOverlapReport(FrozenModel):
    """Source-pinned counts only; it contains no source genre labels or predictions."""

    revision: str = "acousticbrainz-discogs-validation-exact-overlap-v1"
    local_only: bool = True
    export_allowed: bool = False
    serving_allowed: bool = False
    source_url: str = _SOURCE_URL
    source_file_sha256: Sha256
    source_file_md5: str = Field(pattern=r"^[0-9a-f]{32}$")
    catalog_file_sha256: Sha256
    source_data_rows: int = Field(ge=0)
    source_duplicate_recording_id_rows: int = Field(ge=0)
    local_recording_mbid_count: int = Field(ge=0)
    exact_recording_mbid_overlap_count: int = Field(ge=0)
    exact_release_group_consistent_overlap_count: int = Field(ge=0)
    release_group_mismatch_overlap_count: int = Field(ge=0)
    one_primary_artist_overlap_count: int = Field(ge=0)
    one_primary_artist_release_group_consistent_overlap_count: int = Field(ge=0)
    label_columns_read: bool = False


def audit_acousticbrainz_discogs_validation_overlap(
    source_file: Path,
    catalog_database: Path,
) -> AcousticBrainzDiscogsOverlapReport:
    """Measure only exact IDs, refusing malformed rows or a checksum mismatch."""
    _require_bounded_regular_file(source_file, _MAXIMUM_COMPRESSED_BYTES, "source archive")
    source_md5, source_sha256 = _file_hashes(source_file)
    if source_md5 != _PUBLISHED_MD5:
        raise AcousticBrainzDiscogsOverlapError("source MD5 does not match the published checksum")
    source_rows = _read_source_identifiers(source_file)
    local_rows = _read_local_identifiers(catalog_database)
    _require_bounded_regular_file(catalog_database, 4 * 1024 * 1024 * 1024, "catalog database")
    _, catalog_sha256 = _file_hashes(catalog_database)

    source_ids = Counter(recording_id for recording_id, _ in source_rows)
    overlap = [
        (recording_id, release_group_id)
        for recording_id, release_group_id in source_rows
        if recording_id in local_rows
    ]
    consistent = [
        (recording_id, release_group_id)
        for recording_id, release_group_id in overlap
        if release_group_id in local_rows[recording_id].release_group_ids
    ]
    one_artist_recordings = {
        recording_id for recording_id, value in local_rows.items() if value.one_primary_artist
    }
    return AcousticBrainzDiscogsOverlapReport(
        source_file_sha256=source_sha256,
        source_file_md5=source_md5,
        catalog_file_sha256=catalog_sha256,
        source_data_rows=len(source_rows),
        source_duplicate_recording_id_rows=sum(
            count - 1 for count in source_ids.values() if count > 1
        ),
        local_recording_mbid_count=len(local_rows),
        exact_recording_mbid_overlap_count=len(overlap),
        exact_release_group_consistent_overlap_count=len(consistent),
        release_group_mismatch_overlap_count=len(overlap) - len(consistent),
        one_primary_artist_overlap_count=sum(
            recording_id in one_artist_recordings for recording_id, _ in overlap
        ),
        one_primary_artist_release_group_consistent_overlap_count=sum(
            recording_id in one_artist_recordings for recording_id, _ in consistent
        ),
    )


class _LocalRecording(FrozenModel):
    release_group_ids: frozenset[UUID]
    one_primary_artist: bool


def _read_source_identifiers(source_file: Path) -> tuple[tuple[UUID, UUID], ...]:
    try:
        with bz2.open(source_file, "rb") as source:
            decoded_bytes = 0
            header = source.readline(_MAXIMUM_LINE_BYTES + 1)
            decoded_bytes += len(header)
            if len(header) > _MAXIMUM_LINE_BYTES or not header.startswith(
                b"recordingmbid\treleasegroupmbid"
            ):
                raise AcousticBrainzDiscogsOverlapError(
                    "source header does not begin with exact MBID columns"
                )
            rows: list[tuple[UUID, UUID]] = []
            for line_number, line in enumerate(source, start=2):
                decoded_bytes += len(line)
                if decoded_bytes > _MAXIMUM_DECOMPRESSED_BYTES:
                    raise AcousticBrainzDiscogsOverlapError(
                        "source exceeds decompressed-byte limit"
                    )
                if len(line) > _MAXIMUM_LINE_BYTES:
                    raise AcousticBrainzDiscogsOverlapError("source row exceeds byte limit")
                if line_number > _MAXIMUM_SOURCE_ROWS + 1:
                    raise AcousticBrainzDiscogsOverlapError("source exceeds row limit")
                first_tab = line.find(b"\t")
                second_tab = line.find(b"\t", first_tab + 1)
                if first_tab < 1 or second_tab < first_tab + 2:
                    raise AcousticBrainzDiscogsOverlapError(
                        f"source row {line_number} has no two identifier columns"
                    )
                try:
                    rows.append(
                        (
                            UUID(line[:first_tab].decode("ascii")),
                            UUID(line[first_tab + 1 : second_tab].decode("ascii")),
                        )
                    )
                except ValueError as error:
                    raise AcousticBrainzDiscogsOverlapError(
                        f"source row {line_number} has an invalid MusicBrainz UUID"
                    ) from error
    except OSError as error:
        raise AcousticBrainzDiscogsOverlapError("source archive cannot be read") from error
    return tuple(rows)


def _require_bounded_regular_file(path: Path, maximum_bytes: int, label: str) -> int:
    try:
        metadata = path.stat()
    except OSError as error:
        raise AcousticBrainzDiscogsOverlapError(f"{label} cannot be statted") from error
    if not path.is_file() or metadata.st_size > maximum_bytes:
        raise AcousticBrainzDiscogsOverlapError(f"{label} is not a bounded regular file")
    return metadata.st_size


def _file_hashes(path: Path) -> tuple[str, str]:
    md5 = hashlib.md5(usedforsecurity=False)
    sha256 = hashlib.sha256()
    try:
        with path.open("rb") as source:
            while chunk := source.read(1024 * 1024):
                md5.update(chunk)
                sha256.update(chunk)
    except OSError as error:
        raise AcousticBrainzDiscogsOverlapError("source file cannot be hashed") from error
    return md5.hexdigest(), sha256.hexdigest()


def _read_local_identifiers(catalog_database: Path) -> dict[UUID, _LocalRecording]:
    query = """
        WITH recording_ids AS (
            SELECT identifier.entity_id AS recording_id,
                   identifier.normalized_value AS recording_mbid
            FROM entity_identifiers AS identifier
            JOIN identifier_types AS type ON type.id = identifier.identifier_type_id
            JOIN recordings AS recording ON recording.id = identifier.entity_id
            WHERE type.type_key = ?
        ), release_group_ids AS (
            SELECT track.recording_id, group_identifier.normalized_value AS release_group_mbid
            FROM tracks AS track
            JOIN media ON media.id = track.medium_id
            JOIN releases ON releases.id = media.release_id
            JOIN release_groups ON release_groups.id = releases.release_group_id
            JOIN entity_identifiers AS group_identifier
              ON group_identifier.entity_id = release_groups.id
            JOIN identifier_types AS group_type
              ON group_type.id = group_identifier.identifier_type_id
            WHERE track.recording_id IS NOT NULL AND group_type.type_key = ?
        ), primary_credit_summary AS (
            SELECT credit.entity_id AS recording_id,
                   COUNT(DISTINCT credit.artist_credit_id) AS credit_relation_count,
                   COUNT(DISTINCT member.artist_id) AS artist_count,
                   COUNT(DISTINCT member.position) AS credit_position_count
            FROM entity_artist_credits AS credit
            JOIN artist_credit_members AS member
              ON member.artist_credit_id = credit.artist_credit_id
            WHERE credit.credit_kind = 'primary'
            GROUP BY credit.entity_id
        )
        SELECT recording_ids.recording_mbid, release_group_ids.release_group_mbid,
               COALESCE(primary_credit_summary.credit_relation_count, 0) = 1
               AND COALESCE(primary_credit_summary.artist_count, 0) = 1
               AND COALESCE(primary_credit_summary.credit_position_count, 0) = 1
        FROM recording_ids
        LEFT JOIN release_group_ids
          ON release_group_ids.recording_id = recording_ids.recording_id
        LEFT JOIN primary_credit_summary
          ON primary_credit_summary.recording_id = recording_ids.recording_id
    """
    try:
        with sqlite3.connect(f"file:{catalog_database}?mode=ro", uri=True) as connection:
            values = connection.execute(
                query, (_RECORDING_IDENTIFIER_TYPE, _RELEASE_GROUP_IDENTIFIER_TYPE)
            ).fetchall()
    except sqlite3.Error as error:
        raise AcousticBrainzDiscogsOverlapError(
            "local catalog cannot supply exact bridge rows"
        ) from error
    grouped: dict[UUID, tuple[set[UUID], bool]] = {}
    for recording_raw, release_group_raw, one_primary_artist in values:
        recording_id = UUID(recording_raw)
        groups, has_one_primary_artist = grouped.setdefault(recording_id, (set(), False))
        if release_group_raw is not None:
            groups.add(UUID(release_group_raw))
        grouped[recording_id] = (groups, has_one_primary_artist or bool(one_primary_artist))
    return {
        recording_id: _LocalRecording(
            release_group_ids=frozenset(release_group_ids), one_primary_artist=one_primary_artist
        )
        for recording_id, (release_group_ids, one_primary_artist) in grouped.items()
    }
