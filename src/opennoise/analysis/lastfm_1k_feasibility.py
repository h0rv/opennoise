"""One-pass, counts-only feasibility receipt for a supplied Last.fm 1K archive.

This module never downloads or extracts an archive. It keeps source IDs only
while a scan is running, and its returned receipt contains counts and hashes.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import tarfile
from collections.abc import Iterator  # noqa: TC003
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime
from typing import IO, TYPE_CHECKING, Literal
from uuid import UUID

from pydantic import Field, model_validator

from opennoise.models import FrozenModel
from opennoise.types import Sha256  # noqa: TC001

if TYPE_CHECKING:
    from pathlib import Path

_PUBLISHED_ARCHIVE_MD5 = "a79a6808f54f73354789a9fb02cb1e41"
_ARCHIVE_MD5 = _PUBLISHED_ARCHIVE_MD5
_LISTENS_MEMBER_BASENAME = "userid-timestamp-artid-artname-traid-traname.tsv"
_ISO_UTC_TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_TSV_FIELD_COUNT = 6
_SHA256_HEX_LENGTH = 64


class LastFm1kFeasibilityError(ValueError):
    """The local feasibility scan cannot safely continue."""


class LastFm1kFeasibilitySettings(FrozenModel):
    """Predeclared bounds for one archive scan."""

    revision: Literal["lastfm-1k-feasibility-settings-v1"] = "lastfm-1k-feasibility-settings-v1"
    maximum_archive_bytes: int = Field(default=800_000_000, ge=1, le=800_000_000)
    maximum_rows: int = Field(default=19_150_868, ge=1, le=19_150_868)
    maximum_line_bytes: int = Field(default=1_000_000, ge=64, le=2_000_000)
    maximum_unique_artist_mbids: int = Field(default=2_000_000, ge=1, le=2_000_000)


class LastFm1kFeasibilityReceipt(FrozenModel):
    """A create-only local receipt that contains no source row values."""

    revision: Literal["lastfm-1k-feasibility-receipt-v1"] = "lastfm-1k-feasibility-receipt-v1"
    local_only: Literal[True] = True
    export_allowed: Literal[False] = False
    serving_allowed: Literal[False] = False
    graph_input_allowed: Literal[False] = False
    model_input_allowed: Literal[False] = False
    public_use_allowed: Literal[False] = False
    source_archive_md5: Literal["a79a6808f54f73354789a9fb02cb1e41"] = _PUBLISHED_ARCHIVE_MD5
    source_archive_sha256: Sha256
    source_archive_byte_size: int = Field(ge=0)
    supplied_archive_sha256: Sha256
    source_member: str = Field(min_length=1, max_length=500)
    settings: LastFm1kFeasibilitySettings
    raw_rows_seen: int = Field(ge=0)
    valid_tsv_rows: int = Field(ge=0)
    malformed_rows: int = Field(ge=0)
    abstained_rows: int = Field(ge=0)
    valid_canonical_artist_mbid_rows: int = Field(ge=0)
    valid_canonical_track_mbid_rows: int = Field(ge=0)
    valid_timestamp_rows: int = Field(ge=0)
    valid_exact_artist_track_timestamp_rows: int = Field(ge=0)
    unique_valid_canonical_artist_mbid_count: int = Field(ge=0)
    catalog_supplied: bool
    catalog_database_sha256: Sha256 | None = None
    catalog_exact_artist_mbid_count: int | None = Field(default=None, ge=0)
    catalog_exact_artist_overlap_count: int | None = Field(default=None, ge=0)
    output_sha256: Sha256

    @model_validator(mode="after")
    def _verify_row_partitions(self) -> LastFm1kFeasibilityReceipt:
        if self.valid_tsv_rows + self.malformed_rows != self.raw_rows_seen:
            raise ValueError("raw row count is not partitioned by TSV parsing")
        if self.abstained_rows > self.valid_tsv_rows:
            raise ValueError("abstained rows exceed valid TSV rows")
        if self.catalog_supplied != (self.catalog_database_sha256 is not None):
            raise ValueError("catalog hash presence does not match catalog mode")
        if self.output_sha256 != _receipt_hash(self):
            raise ValueError("receipt hash does not match receipt content")
        return self


@dataclass(slots=True)
class _Counts:
    raw_rows_seen: int = 0
    valid_tsv_rows: int = 0
    malformed_rows: int = 0
    abstained_rows: int = 0
    valid_artist_rows: int = 0
    valid_track_rows: int = 0
    valid_timestamp_rows: int = 0
    complete_rows: int = 0


@dataclass(slots=True)
class _ScanState:
    counts: _Counts
    observed_artist_ids: set[str]
    overlapping_artist_ids: set[str]


def run_lastfm_1k_feasibility_scan(
    *,
    archive_path: Path,
    supplied_archive_sha256: str,
    catalog_path: Path | None = None,
    settings: LastFm1kFeasibilitySettings | None = None,
) -> LastFm1kFeasibilityReceipt:
    """Read the listens member once and return a counts-only local receipt."""
    config = settings or LastFm1kFeasibilitySettings()
    archive_sha256 = _verify_archive(archive_path, supplied_archive_sha256, config)
    catalog_ids = _catalog_artist_ids(catalog_path) if catalog_path is not None else None
    catalog_sha256 = _sha256_file(catalog_path) if catalog_path is not None else None
    state = _ScanState(_Counts(), set(), set())

    source_member: str | None = None
    for member_name, raw_line in iter_lastfm_1k_listens_rows(
        archive_path, maximum_line_bytes=config.maximum_line_bytes
    ):
        source_member = member_name
        _process_row(state, raw_line, catalog_ids, config)

    counts = state.counts
    placeholder = LastFm1kFeasibilityReceipt.model_construct(
        source_archive_sha256=archive_sha256,
        source_archive_byte_size=archive_path.stat().st_size,
        supplied_archive_sha256=supplied_archive_sha256,
        source_member=_required_member_name(source_member),
        settings=config,
        raw_rows_seen=counts.raw_rows_seen,
        valid_tsv_rows=counts.valid_tsv_rows,
        malformed_rows=counts.malformed_rows,
        abstained_rows=counts.abstained_rows,
        valid_canonical_artist_mbid_rows=counts.valid_artist_rows,
        valid_canonical_track_mbid_rows=counts.valid_track_rows,
        valid_timestamp_rows=counts.valid_timestamp_rows,
        valid_exact_artist_track_timestamp_rows=counts.complete_rows,
        unique_valid_canonical_artist_mbid_count=len(state.observed_artist_ids),
        catalog_supplied=catalog_path is not None,
        catalog_database_sha256=catalog_sha256,
        catalog_exact_artist_mbid_count=len(catalog_ids) if catalog_ids is not None else None,
        catalog_exact_artist_overlap_count=(
            len(state.overlapping_artist_ids) if catalog_ids is not None else None
        ),
        output_sha256="0" * _SHA256_HEX_LENGTH,
    )
    payload = placeholder.model_dump(mode="json")
    payload["output_sha256"] = _receipt_hash(placeholder)
    return LastFm1kFeasibilityReceipt.model_validate(payload)


def iter_lastfm_1k_listens_rows(
    archive_path: Path, *, maximum_line_bytes: int
) -> Iterator[tuple[str, bytes | None]]:
    """Yield only bounded lines from one unambiguous listens TSV member, once."""
    found_member_name: str | None = None
    with tarfile.open(archive_path, mode="r|gz") as archive:
        for member in archive:
            if member.name.rsplit("/", maxsplit=1)[-1] != _LISTENS_MEMBER_BASENAME:
                continue
            if found_member_name is not None:
                raise LastFm1kFeasibilityError("archive has multiple listens TSV members")
            if not member.isfile():
                raise LastFm1kFeasibilityError("listens member is not a regular file")
            found_member_name = member.name
            stream = archive.extractfile(member)
            if stream is None:
                raise LastFm1kFeasibilityError("listens member cannot be opened")
            try:
                for line in _bounded_lines(stream, maximum_line_bytes):
                    yield member.name, line
            finally:
                stream.close()
    if found_member_name is None:
        raise LastFm1kFeasibilityError("listens member is unavailable")


def _bounded_lines(stream: IO[bytes], maximum_line_bytes: int) -> Iterator[bytes | None]:
    while line := stream.readline(maximum_line_bytes + 1):
        if len(line) <= maximum_line_bytes and line.endswith(b"\n"):
            yield line
            continue
        if len(line) < maximum_line_bytes + 1:
            yield line
            continue
        while not line.endswith(b"\n"):
            line = stream.readline(maximum_line_bytes + 1)
            if not line:
                break
        yield None


def _parse_tsv_row(raw_line: bytes) -> tuple[str, str, str] | None:
    try:
        fields = raw_line.rstrip(b"\r\n").decode("utf-8").split("\t")
    except UnicodeDecodeError:
        return None
    if len(fields) != _TSV_FIELD_COUNT:
        return None
    return fields[2], fields[4], fields[1]


def _canonical_uuid(value: str) -> str | None:
    try:
        parsed = UUID(value)
    except ValueError:
        return None
    canonical = str(parsed)
    return canonical if value == canonical else None


def _timestamp(value: str) -> bool:
    if not _ISO_UTC_TIMESTAMP.fullmatch(value):
        return False
    try:
        datetime.fromisoformat(value)
    except ValueError:
        return False
    return True


def _required_member_name(value: str | None) -> str:
    if value is None:
        raise LastFm1kFeasibilityError("listens member has no rows")
    return value


def _process_row(
    state: _ScanState,
    raw_line: bytes | None,
    catalog_ids: frozenset[str] | None,
    config: LastFm1kFeasibilitySettings,
) -> None:
    state.counts.raw_rows_seen += 1
    if state.counts.raw_rows_seen > config.maximum_rows:
        raise LastFm1kFeasibilityError("source row count exceeds bound")
    if raw_line is None:
        state.counts.malformed_rows += 1
        return
    parsed = _parse_tsv_row(raw_line)
    if parsed is None:
        state.counts.malformed_rows += 1
        return
    state.counts.valid_tsv_rows += 1
    artist_id, track_id, timestamp = parsed
    artist_valid = _canonical_uuid(artist_id)
    track_valid = _canonical_uuid(track_id)
    timestamp_valid = _timestamp(timestamp)
    if artist_valid is not None:
        state.counts.valid_artist_rows += 1
        state.observed_artist_ids.add(artist_valid)
        if len(state.observed_artist_ids) > config.maximum_unique_artist_mbids:
            raise LastFm1kFeasibilityError("unique artist MBID count exceeds bound")
        if catalog_ids is not None and artist_valid in catalog_ids:
            state.overlapping_artist_ids.add(artist_valid)
    if track_valid is not None:
        state.counts.valid_track_rows += 1
    if timestamp_valid:
        state.counts.valid_timestamp_rows += 1
    if artist_valid is not None and track_valid is not None and timestamp_valid:
        state.counts.complete_rows += 1
    else:
        state.counts.abstained_rows += 1


def _catalog_artist_ids(path: Path) -> frozenset[str]:
    try:
        with closing(sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)) as database:
            rows = database.execute(
                """SELECT DISTINCT identifier.normalized_value
                   FROM entity_identifiers AS identifier
                   JOIN identifier_types AS identifier_type
                     ON identifier_type.id = identifier.identifier_type_id
                   WHERE identifier_type.type_key = 'musicbrainz_artist_id'"""
            )
            return frozenset(str(value) for (value,) in rows)
    except sqlite3.Error as error:
        raise LastFm1kFeasibilityError("cannot load local catalog artist identifiers") from error


def _verify_archive(path: Path, supplied_sha256: str, config: LastFm1kFeasibilitySettings) -> str:
    if not path.is_file() or path.stat().st_size > config.maximum_archive_bytes:
        raise LastFm1kFeasibilityError("archive is unavailable or exceeds byte limit")
    if len(supplied_sha256) != _SHA256_HEX_LENGTH or any(
        character not in "0123456789abcdef" for character in supplied_sha256
    ):
        raise LastFm1kFeasibilityError("supplied archive SHA-256 is not canonical lowercase hex")
    md5_digest = hashlib.md5(usedforsecurity=False)
    sha256_digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            md5_digest.update(chunk)
            sha256_digest.update(chunk)
    if md5_digest.hexdigest() != _ARCHIVE_MD5:
        raise LastFm1kFeasibilityError("archive MD5 does not match the published source pin")
    archive_sha256 = sha256_digest.hexdigest()
    if archive_sha256 != supplied_sha256:
        raise LastFm1kFeasibilityError(
            "archive SHA-256 does not match the independently supplied pin"
        )
    return archive_sha256


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _receipt_hash(receipt: LastFm1kFeasibilityReceipt) -> str:
    payload = receipt.model_dump(mode="json", exclude={"output_sha256"})
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
