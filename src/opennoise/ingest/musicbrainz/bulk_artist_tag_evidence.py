"""Bounded exact-UUID projection of official MusicBrainz bulk artist tags.

Core artist identity is CC0. The derived aggregate tag tables are local-only
CC-BY-NC-SA research evidence. User-specific ``artist_tag_raw`` is excluded.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tarfile
import tempfile
from collections import Counter
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING
from uuid import UUID

from pydantic import HttpUrl, TypeAdapter

from opennoise.common import canonical_json, sha256_file, sha256_json
from opennoise.ingest.musicbrainz.derived_entity_tags import (
    DEFAULT_LIMITS,
    DerivedEntityTagError,
    DerivedEntityTagLimits,
    _columns,
    _member_lines,
    _positive_int,
    _tag_lookup,
    verify_declared_archive,
)
from opennoise.models.sources import DownloadSource

if TYPE_CHECKING:
    from collections.abc import Iterator

_ARTIST_MEMBER = PurePosixPath("mbdump/artist")
_COPY_COLUMNS = 19
_JOIN_BATCH_ROWS = 20_000
_SHA256 = frozenset("0123456789abcdef")
_SHA256_LENGTH = 64
_PRESENT_SOURCE_REFERENCE_COUNT = 2
_LICENSE_URL = "https://musicbrainz.org/doc/About/Data_License"


class BulkArtistTagError(ValueError):
    """A bounded MusicBrainz bulk tag projection failed source verification."""


def _require_integer(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise BulkArtistTagError("bulk source integer fields must be JSON integers")
    return value


@dataclass(frozen=True, slots=True)
class CoreArtistPrefixReceipt:
    """Published whole-archive facts plus the independently hashed HTTP prefix."""

    snapshot: str
    archive_url: str
    archive_bytes: int
    archive_sha256: str
    prefix_bytes: int
    prefix_sha256: str
    artist_member_bytes: int
    artist_member_sha256: str
    artist_row_count: int
    schema_sequence: str
    observed_at: str
    whole_archive_sha256_verified: bool = False


def _verify_file(path: Path, expected_bytes: int, expected_sha256: str, role: str) -> None:
    if not path.is_file() or path.is_symlink():
        raise BulkArtistTagError(f"{role} source is not a regular file")
    actual_bytes = path.stat().st_size
    if actual_bytes != expected_bytes:
        raise BulkArtistTagError(f"{role} byte count {actual_bytes} != {expected_bytes}")
    digest, _ = sha256_file(path)
    if digest != expected_sha256:
        raise BulkArtistTagError(f"{role} SHA-256 differs from the pinned receipt")


def _source_captures(
    derived_archive: Path,
    derived_source: DownloadSource,
    core_receipt: CoreArtistPrefixReceipt,
) -> dict[str, object]:
    source_dir = derived_archive.parent
    checksum_path = source_dir / "SHA256SUMS"
    snapshot_path = source_dir / "snapshot-index.html"
    license_path = source_dir / "license.html"
    for path, role in (
        (checksum_path, "official SHA256SUMS capture"),
        (snapshot_path, "official snapshot listing capture"),
        (license_path, "official license page capture"),
    ):
        if not path.is_file() or path.is_symlink():
            raise BulkArtistTagError(f"{role} is absent or unsafe")
    checksums = checksum_path.read_text(encoding="ascii")
    if (
        f"{derived_source.verified_sha256()} *mbdump-derived.tar.bz2" not in checksums
        or f"{core_receipt.archive_sha256} *mbdump.tar.bz2" not in checksums
    ):
        raise BulkArtistTagError("official SHA256SUMS capture lacks the derived archive hash")
    snapshot_html = snapshot_path.read_text(encoding="utf-8")
    if (
        f"{derived_source.snapshot}/" not in snapshot_html
        or "mbdump.tar.bz2" not in snapshot_html
        or "mbdump-derived.tar.bz2" not in snapshot_html
    ):
        raise BulkArtistTagError(
            "official snapshot listing capture differs from the declared snapshot"
        )
    license_html = license_path.read_bytes()
    if b"Attribution-NonCommercial-ShareAlike" not in license_html or b"CC0" not in license_html:
        raise BulkArtistTagError("official license capture does not establish both field scopes")
    return {
        "checksum_manifest_capture": {
            "path": checksum_path.name,
            "bytes": checksum_path.stat().st_size,
            "sha256": sha256_file(checksum_path)[0],
            "url": f"{str(derived_source.url).rsplit('/', 1)[0]}/SHA256SUMS",
        },
        "snapshot_listing_capture": {
            "path": snapshot_path.name,
            "bytes": snapshot_path.stat().st_size,
            "sha256": sha256_file(snapshot_path)[0],
        },
        "license_page_capture": {
            "path": license_path.name,
            "bytes": license_path.stat().st_size,
            "sha256": sha256_file(license_path)[0],
            "url": _LICENSE_URL,
        },
    }


def _source_paths(
    *,
    derived_archive: Path,
    core_prefix: Path,
    selection_source_path: Path,
    output_directory: Path,
) -> dict[str, str]:
    root = output_directory.resolve()
    return {
        "derived_archive": Path(os.path.relpath(derived_archive.resolve(), root)).as_posix(),
        "core_prefix": Path(os.path.relpath(core_prefix.resolve(), root)).as_posix(),
        "selection_source": Path(os.path.relpath(selection_source_path.resolve(), root)).as_posix(),
        "sha256sums": Path(
            os.path.relpath((derived_archive.parent / "SHA256SUMS").resolve(), root)
        ).as_posix(),
        "snapshot_index": Path(
            os.path.relpath((derived_archive.parent / "snapshot-index.html").resolve(), root)
        ).as_posix(),
        "license_page": Path(
            os.path.relpath((derived_archive.parent / "license.html").resolve(), root)
        ).as_posix(),
    }


def _read_targets(path: Path, *, expected_count: int) -> tuple[set[str], str, str]:
    if not path.is_file() or path.is_symlink():
        raise BulkArtistTagError("selection artifact is not a regular file")
    input_sha256, _ = sha256_file(path)
    normalized: set[str] = set()
    with path.open("rb") as stream:
        for raw in stream:
            try:
                row = json.loads(raw)
                identity = row["artist_mbid"]
            except (json.JSONDecodeError, KeyError, TypeError) as error:
                raise BulkArtistTagError("selection artifact row lacks artist_mbid") from error
            if not isinstance(identity, str):
                raise BulkArtistTagError("selection artist ID must be text")
            try:
                canonical = str(UUID(identity))
            except (ValueError, AttributeError) as error:
                raise BulkArtistTagError(
                    "selection contains an invalid MusicBrainz UUID"
                ) from error
            if canonical != identity or identity in normalized:
                raise BulkArtistTagError("selection UUIDs must be canonical and unique")
            normalized.add(identity)
    if len(normalized) != expected_count:
        raise BulkArtistTagError("selection artist count differs from its receipt")
    hash_input = bytearray()
    for identity in sorted(normalized):
        hash_input.extend(identity.encode("ascii"))
        hash_input.append(10)
    return normalized, hashlib.sha256(hash_input).hexdigest(), input_sha256


def _core_artist_rows(  # noqa: C901, PLR0912, PLR0915 - bounded COPY and tar-member verification.
    path: Path,
    receipt: CoreArtistPrefixReceipt,
    target_ids: set[str],
) -> tuple[dict[int, tuple[str, str, int, str]], set[str], dict[str, object]]:
    """Read only the complete artist member from a verified bounded prefix."""
    _verify_file(path, receipt.prefix_bytes, receipt.prefix_sha256, "core prefix")
    mapped: dict[int, tuple[str, str, int, str]] = {}
    found: set[str] = set()
    table_digest = hashlib.sha256()
    row_count = 0
    seen_members = 0
    with tarfile.open(path, mode="r|bz2") as archive:
        for member in archive:
            member_path = PurePosixPath(member.name)
            if member_path.is_absolute() or ".." in member_path.parts:
                raise BulkArtistTagError(f"unsafe core archive member {member.name}")
            if member_path != _ARTIST_MEMBER:
                continue
            seen_members += 1
            if seen_members != 1 or not member.isfile():
                raise BulkArtistTagError("core archive repeats or corrupts its artist member")
            if member.size != receipt.artist_member_bytes:
                raise BulkArtistTagError("core artist member size differs from its receipt")
            stream = archive.extractfile(member)
            if stream is None:
                raise BulkArtistTagError("core artist member cannot be read")
            remaining = member.size
            with stream:
                while remaining:
                    raw = stream.readline(min(2 * 1024 * 1024, remaining + 1))
                    if not raw or len(raw) > remaining:
                        raise BulkArtistTagError("core artist table ended inside a row")
                    remaining -= len(raw)
                    table_digest.update(raw)
                    row_count += 1
                    if not raw.endswith(b"\n"):
                        raise BulkArtistTagError("core artist row is not newline terminated")
                    columns = _columns(raw[:-1], _COPY_COLUMNS, "artist")
                    try:
                        numeric_id = int(columns[0])
                        mbid = str(UUID(columns[1]))
                    except (ValueError, IndexError) as error:
                        raise BulkArtistTagError(
                            "invalid exact identity in core artist row"
                        ) from error
                    if numeric_id <= 0 or columns[1] != mbid:
                        raise BulkArtistTagError("core artist ID or UUID is not canonical")
                    if mbid not in target_ids:
                        continue
                    if mbid in found or numeric_id in mapped:
                        raise BulkArtistTagError("core artist member repeats a selected identity")
                    found.add(mbid)
                    mapped[numeric_id] = (
                        mbid,
                        columns[2],
                        row_count,
                        hashlib.sha256(raw).hexdigest(),
                    )
            break
    if seen_members != 1:
        raise BulkArtistTagError("core prefix has no complete mbdump/artist member")
    actual_table_sha = table_digest.hexdigest()
    if row_count != receipt.artist_row_count or actual_table_sha != receipt.artist_member_sha256:
        raise BulkArtistTagError("core artist member row count or SHA-256 differs")
    facts = {
        "member": str(_ARTIST_MEMBER),
        "member_bytes": receipt.artist_member_bytes,
        "member_sha256": actual_table_sha,
        "row_count": row_count,
        "selected_uuid_match_count": len(found),
    }
    return mapped, found, facts


def _iter_artist_tag_rows(
    path: Path,
    limits: DerivedEntityTagLimits,
) -> Iterator[tuple[int, int, str, int, int, str]]:
    tags = _tag_lookup(path, limits)
    for ordinal, row in enumerate(_member_lines(path, "artist_tag", limits), start=1):
        artist_id_text, tag_id_text, count_text, _last_updated = _columns(row, 4, "artist_tag")
        artist_id = _positive_int(artist_id_text, "artist_tag")
        tag_id = _positive_int(tag_id_text, "artist_tag")
        try:
            count = int(count_text)
        except ValueError as error:
            raise DerivedEntityTagError("invalid aggregate count in artist_tag") from error
        if tag_id not in tags:
            raise DerivedEntityTagError("artist_tag references an unknown tag ID")
        yield (
            artist_id,
            tag_id,
            tags[tag_id],
            count,
            ordinal,
            hashlib.sha256(row).hexdigest(),
        )


def _write_projection(  # noqa: C901, PLR0913, PLR0915 - bounded source replay boundary.
    *,
    derived_archive: Path,
    derived_source: DownloadSource,
    core_prefix: Path,
    core_receipt: CoreArtistPrefixReceipt,
    target_ids: set[str],
    output_path: Path,
    limits: DerivedEntityTagLimits,
) -> dict[str, object]:
    verify_declared_archive(derived_archive, derived_source)
    if derived_source.snapshot != core_receipt.snapshot:
        raise BulkArtistTagError("core and derived archive snapshots differ")
    if core_receipt.whole_archive_sha256_verified:
        raise BulkArtistTagError("a bounded core prefix cannot claim whole-archive verification")
    artist_map, found_ids, core_facts = _core_artist_rows(core_prefix, core_receipt, target_ids)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    counts: Counter[str] = Counter()
    # A disk-backed join keeps memory bounded even when the aggregate has many rows.
    with tempfile.TemporaryDirectory(prefix="mb-artist-tags-") as temporary:
        db_path = Path(temporary) / "join.sqlite"
        with closing(sqlite3.connect(db_path)) as connection:
            connection.execute(
                "CREATE TABLE selected_artist (numeric_id INTEGER PRIMARY KEY, mbid TEXT UNIQUE, "
                "name TEXT NOT NULL, source_row INTEGER NOT NULL, source_row_sha256 TEXT NOT NULL)"
            )
            connection.executemany(
                "INSERT INTO selected_artist VALUES (?, ?, ?, ?, ?)",
                (
                    (numeric, mbid, name, row, row_sha)
                    for numeric, (mbid, name, row, row_sha) in artist_map.items()
                ),
            )
            connection.execute("CREATE TABLE selected_target (mbid TEXT PRIMARY KEY)")
            connection.executemany(
                "INSERT INTO selected_target VALUES (?)", ((mbid,) for mbid in sorted(target_ids))
            )
            connection.execute(
                "CREATE TABLE selected_tag (numeric_id INTEGER NOT NULL, tag_id INTEGER NOT NULL, "
                "tag_name TEXT NOT NULL, vote_count INTEGER NOT NULL, source_row INTEGER NOT NULL, "
                "source_row_sha256 TEXT NOT NULL, PRIMARY KEY(numeric_id, tag_id))"
            )
            batch: list[tuple[int, int, str, int, int, str]] = []
            all_rows = 0
            for numeric_id, tag_id, tag_name, count, row, row_sha in _iter_artist_tag_rows(
                derived_archive, limits
            ):
                all_rows += 1
                category = "positive" if count > 0 else "zero" if count == 0 else "negative"
                counts[f"source_artist_tag_{category}_row_count"] += 1
                if numeric_id in artist_map:
                    counts[f"primary_artist_tag_{category}_row_count"] += 1
                    batch.append((numeric_id, tag_id, tag_name, count, row, row_sha))
                if len(batch) >= _JOIN_BATCH_ROWS:
                    connection.executemany(
                        "INSERT INTO selected_tag VALUES (?, ?, ?, ?, ?, ?)", batch
                    )
                    batch.clear()
            if batch:
                connection.executemany("INSERT INTO selected_tag VALUES (?, ?, ?, ?, ?, ?)", batch)
            connection.commit()
            counts["source_artist_tag_row_count"] = all_rows
            digest = hashlib.sha256()
            byte_size = 0
            with output_path.open("wb") as output:
                rows = connection.execute(
                    "SELECT a.numeric_id,s.mbid,a.name,a.source_row,a.source_row_sha256,"
                    "t.tag_id,t.tag_name,t.vote_count,t.source_row,t.source_row_sha256 "
                    "FROM selected_target s LEFT JOIN selected_artist a USING(mbid) "
                    "LEFT JOIN selected_tag t USING(numeric_id) ORDER BY s.mbid,t.source_row"
                )
                current_mbid: str | None = None
                current_record: dict[str, object] | None = None
                current_tags: list[dict[str, object]] = []
                for row in rows:
                    (
                        numeric_id,
                        mbid,
                        name,
                        artist_row,
                        artist_sha,
                        tag_id,
                        tag_name,
                        vote_count,
                        tag_row,
                        tag_sha,
                    ) = row
                    if current_mbid != mbid:
                        if current_record is not None:
                            payload = canonical_json(current_record) + b"\n"
                            output.write(payload)
                            digest.update(payload)
                            byte_size += len(payload)
                        current_mbid = str(mbid)
                        current_tags = []
                        is_present = name is not None
                        current_record = {
                            "artist_mbid": str(mbid),
                            "name": str(name) if is_present else None,
                            "tags": current_tags,
                            "genres": [],
                            "source_document": "mbdump/artist + mbdump/artist_tag + mbdump/tag",
                            "source_response_sha256": derived_source.verified_sha256(),
                            "source_role": "bulk_musicbrainz_aggregate_artist_tag",
                            "source_refs": (
                                [
                                    f"mbdump/artist:row:{artist_row}:sha256:{artist_sha}",
                                    f"mbdump/artist_tag:sha256:{derived_source.verified_sha256()}",
                                ]
                                if is_present
                                else []
                            ),
                            "source_state": (
                                "present_in_artist_dump"
                                if is_present
                                else "absent_from_current_artist_dump"
                            ),
                        }
                    if tag_name is not None:
                        current_tags.append(
                            {
                                "name": str(tag_name),
                                "count": int(vote_count),
                                "tag_id": int(tag_id),
                                "source_row": int(tag_row),
                                "source_row_sha256": str(tag_sha),
                            }
                        )
                if current_record is not None:
                    payload = canonical_json(current_record) + b"\n"
                    output.write(payload)
                    digest.update(payload)
                    byte_size += len(payload)
            counts["projected_artist_count"] = len(target_ids)
            counts["projected_artist_present_in_dump_count"] = len(artist_map)
            counts["projected_artist_absent_from_dump_count"] = len(target_ids - found_ids)
            counts["projected_artist_with_any_tag_count"] = connection.execute(
                "SELECT COUNT(DISTINCT numeric_id) FROM selected_tag"
            ).fetchone()[0]
    return {
        "rows_sha256": digest.hexdigest(),
        "rows_bytes": byte_size,
        "counts": dict(sorted(counts.items())),
        "matched_primary_artist_count": len(found_ids),
        "absent_primary_artist_ids": sorted(target_ids - found_ids),
        "core_artist_member": core_facts,
    }


def build_bulk_artist_tag_artifact(  # noqa: PLR0913 - all bounded source receipts are required inputs.
    *,
    derived_archive: Path,
    derived_source: DownloadSource,
    core_prefix: Path,
    core_receipt: CoreArtistPrefixReceipt,
    selection_source_path: Path,
    selection_artist_count: int,
    derived_observed_at: str,
    output_directory: Path,
    limits: DerivedEntityTagLimits = DEFAULT_LIMITS,
) -> dict[str, object]:
    """Build a replayable, UUID-joined research JSONL for exact selected artists."""
    target_ids, selection_hash, selection_input_sha256 = _read_targets(
        selection_source_path, expected_count=selection_artist_count
    )
    if output_directory.is_symlink():
        raise BulkArtistTagError("output directory must not be a symlink")
    output_directory.mkdir(parents=True, exist_ok=True)
    rows_path = output_directory / "artist-tags.jsonl"
    result = _write_projection(
        derived_archive=derived_archive,
        derived_source=derived_source,
        core_prefix=core_prefix,
        core_receipt=core_receipt,
        target_ids=target_ids,
        output_path=rows_path,
        limits=limits,
    )
    source = _receipt_payload(
        result=result,
        derived_source=derived_source,
        core_receipt=core_receipt,
        selection_path=str(selection_source_path),
        selection_input_sha256=selection_input_sha256,
        selection_hash=selection_hash,
        selection_count=len(target_ids),
        derived_observed_at=derived_observed_at,
        source_captures=_source_captures(derived_archive, derived_source, core_receipt),
        source_paths=_source_paths(
            derived_archive=derived_archive,
            core_prefix=core_prefix,
            selection_source_path=selection_source_path,
            output_directory=output_directory,
        ),
    )
    (output_directory / "receipt.json").write_bytes(canonical_json(source) + b"\n")
    return verify_bulk_artist_tag_artifact(
        derived_archive=derived_archive,
        derived_source=derived_source,
        core_prefix=core_prefix,
        core_receipt=core_receipt,
        selection_source_path=selection_source_path,
        selection_artist_count=selection_artist_count,
        derived_observed_at=derived_observed_at,
        directory=output_directory,
        limits=limits,
    )


def verify_bulk_artist_tag_artifact(  # noqa: PLR0913 - replay binds every source and selection receipt.
    *,
    derived_archive: Path,
    derived_source: DownloadSource,
    core_prefix: Path,
    core_receipt: CoreArtistPrefixReceipt,
    selection_source_path: Path,
    selection_artist_count: int,
    derived_observed_at: str,
    directory: Path,
    limits: DerivedEntityTagLimits = DEFAULT_LIMITS,
) -> dict[str, object]:
    """Independently replay both raw tables and require byte-identical JSONL."""
    target_ids, selection_hash, selection_input_sha256 = _read_targets(
        selection_source_path, expected_count=selection_artist_count
    )
    actual_rows = directory / "artist-tags.jsonl"
    if not actual_rows.is_file() or actual_rows.is_symlink():
        raise BulkArtistTagError("bulk artist-tag JSONL is absent or unsafe")
    with tempfile.TemporaryDirectory(prefix="mb-artist-tags-replay-") as temporary:
        expected = Path(temporary) / "artist-tags.jsonl"
        replay = _write_projection(
            derived_archive=derived_archive,
            derived_source=derived_source,
            core_prefix=core_prefix,
            core_receipt=core_receipt,
            target_ids=target_ids,
            output_path=expected,
            limits=limits,
        )
        actual_sha256, actual_bytes = sha256_file(actual_rows)
        if actual_sha256 != replay["rows_sha256"] or actual_bytes != replay["rows_bytes"]:
            raise BulkArtistTagError("bulk artist-tag JSONL does not replay from raw tables")
        receipt = TypeAdapter(dict[str, object]).validate_json(
            (directory / "receipt.json").read_bytes()
        )
        expected_receipt = _receipt_payload(
            result=replay,
            derived_source=derived_source,
            core_receipt=core_receipt,
            selection_path=str(selection_source_path),
            selection_input_sha256=selection_input_sha256,
            selection_hash=selection_hash,
            selection_count=selection_artist_count,
            derived_observed_at=derived_observed_at,
            source_captures=_source_captures(derived_archive, derived_source, core_receipt),
            source_paths=_source_paths(
                derived_archive=derived_archive,
                core_prefix=core_prefix,
                selection_source_path=selection_source_path,
                output_directory=directory,
            ),
        )
        if receipt != expected_receipt:
            raise BulkArtistTagError("bulk artist-tag receipt does not replay from source facts")
        return receipt


def _receipt_payload(  # noqa: PLR0913 - receipt fields are explicit lineage inputs.
    *,
    result: dict[str, object],
    derived_source: DownloadSource,
    core_receipt: CoreArtistPrefixReceipt,
    selection_path: str,
    selection_input_sha256: str,
    selection_hash: str,
    selection_count: int,
    derived_observed_at: str,
    source_captures: dict[str, object],
    source_paths: dict[str, str],
) -> dict[str, object]:
    payload = {
        "revision": "musicbrainz-bulk-artist-tag-primary-v2",
        "scope": "local_noncommercial_research",
        "public_export_authorized": False,
        "research_model_input_authorized": True,
        "research_model_scope": "local_noncommercial_research",
        "identity_join": "exact_musicbrainz_artist_uuid_to_artist_numeric_id",
        "snapshot": core_receipt.snapshot,
        "core_archive_url": core_receipt.archive_url,
        "core_archive_bytes": core_receipt.archive_bytes,
        "core_archive_published_sha256": core_receipt.archive_sha256,
        "core_archive_sha256_verified": core_receipt.whole_archive_sha256_verified,
        "core_prefix_bytes": core_receipt.prefix_bytes,
        "core_prefix_sha256": core_receipt.prefix_sha256,
        "core_prefix_observed_at": core_receipt.observed_at,
        "core_schema_sequence": core_receipt.schema_sequence,
        "derived_archive_url": str(derived_source.url),
        "derived_archive_bytes": derived_source.expected_bytes,
        "derived_archive_sha256": derived_source.verified_sha256(),
        "derived_observed_at": derived_observed_at,
        "selection_path": selection_path,
        "selection_input_sha256": selection_input_sha256,
        "selection_sha256": selection_hash,
        "selection_artist_count": selection_count,
        "tables_consumed": ["mbdump/artist", "mbdump/artist_tag", "mbdump/tag"],
        "tables_excluded": ["mbdump/artist_tag_raw"],
        "core_metadata_license": "CC0-1.0",
        "tag_associations_license": "CC-BY-NC-SA-3.0",
        "license_url": _LICENSE_URL,
        "license_obligations": "Attribution, NonCommercial, ShareAlike for derived tag evidence",
        "attribution": "MusicBrainz contributors; https://musicbrainz.org/",
        "positive_counts_are_research_observations": True,
        "zero_and_negative_counts_preserved_as_raw_only": True,
        "source_captures": source_captures,
        "source_paths": source_paths,
        "source_tables": result["core_artist_member"],
        "rows_sha256": result["rows_sha256"],
        "rows_bytes": result["rows_bytes"],
        "counts": result["counts"],
        "matched_primary_artist_count": result["matched_primary_artist_count"],
        "absent_primary_artist_ids": result["absent_primary_artist_ids"],
    }
    payload["output_sha256"] = sha256_json(payload)
    return payload


def iter_bulk_artist_tag_rows(  # noqa: C901, PLR0912, PLR0915 - validate complete sealed receipt and rows.
    *, directory: Path, expected_count: int = 198_409
) -> Iterator[dict[str, object]]:
    """Read a sealed bulk-tag JSONL after validating its self-contained receipt."""
    rows_path = directory / "artist-tags.jsonl"
    receipt_path = directory / "receipt.json"
    if rows_path.is_symlink() or receipt_path.is_symlink():
        raise BulkArtistTagError("bulk artist-tag artifact must not follow symlinks")
    receipt = TypeAdapter(dict[str, object]).validate_json(receipt_path.read_bytes())
    if receipt.get("revision") != "musicbrainz-bulk-artist-tag-primary-v2":
        raise BulkArtistTagError("bulk artist-tag artifact has an unsupported revision")
    if receipt.get("scope") != "local_noncommercial_research":
        raise BulkArtistTagError("bulk artist-tag artifact has an unsupported scope")
    if receipt.get("public_export_authorized") is not False:
        raise BulkArtistTagError("bulk artist-tag artifact cannot authorize public export")
    if receipt.get("research_model_input_authorized") is not True:
        raise BulkArtistTagError("bulk artist-tag artifact does not authorize local research input")
    if receipt.get("core_archive_sha256_verified") is not False:
        raise BulkArtistTagError("a bounded core prefix cannot claim whole-archive verification")
    if receipt.get("selection_artist_count") != expected_count:
        raise BulkArtistTagError("bulk artist-tag selection count differs from the expected cohort")
    if receipt.get("tables_excluded") != ["mbdump/artist_tag_raw"]:
        raise BulkArtistTagError("bulk artist-tag artifact does not exclude user-specific raw tags")
    if receipt.get("output_sha256") != sha256_json(
        {key: value for key, value in receipt.items() if key != "output_sha256"}
    ):
        raise BulkArtistTagError("bulk artist-tag receipt digest is invalid")
    source_paths = TypeAdapter(dict[str, str]).validate_python(receipt.get("source_paths"))
    if set(source_paths) != {
        "derived_archive",
        "core_prefix",
        "selection_source",
        "sha256sums",
        "snapshot_index",
        "license_page",
    }:
        raise BulkArtistTagError("bulk artist-tag receipt has an incomplete source path map")
    resolved_paths: dict[str, Path] = {}
    for key, relative in source_paths.items():
        if Path(relative).is_absolute():
            raise BulkArtistTagError("bulk artist-tag source references must be relative")
        resolved = (directory / relative).resolve()
        if not resolved.is_relative_to(directory.resolve().parent):
            raise BulkArtistTagError("bulk artist-tag source reference escapes the research cache")
        if not resolved.is_file() or resolved.is_symlink():
            raise BulkArtistTagError("bulk artist-tag source reference is absent or unsafe")
        resolved_paths[key] = resolved
    _verify_file(
        resolved_paths["derived_archive"],
        _require_integer(receipt["derived_archive_bytes"]),
        str(receipt["derived_archive_sha256"]),
        "derived archive",
    )
    _verify_file(
        resolved_paths["core_prefix"],
        _require_integer(receipt["core_prefix_bytes"]),
        str(receipt["core_prefix_sha256"]),
        "core prefix",
    )
    selected_ids, selection_hash, selection_input_hash = _read_targets(
        resolved_paths["selection_source"], expected_count=expected_count
    )
    if (
        selection_hash != receipt.get("selection_sha256")
        or selection_input_hash != receipt.get("selection_input_sha256")
        or str(resolved_paths["selection_source"])
        != str(Path(str(receipt["selection_path"])).resolve())
    ):
        raise BulkArtistTagError("bulk artist-tag selection source does not match its receipt")
    absent_values = TypeAdapter(list[str]).validate_python(receipt["absent_primary_artist_ids"])
    absent = set(absent_values)
    if len(absent) != len(absent_values) or not absent <= selected_ids:
        raise BulkArtistTagError("bulk artist-tag receipt has invalid absent UUIDs")
    derived_dir = resolved_paths["derived_archive"].parent
    if any(
        resolved_paths[key] != (derived_dir / filename).resolve()
        for key, filename in (
            ("sha256sums", "SHA256SUMS"),
            ("snapshot_index", "snapshot-index.html"),
            ("license_page", "license.html"),
        )
    ):
        raise BulkArtistTagError("bulk artist-tag capture paths do not match the source archive")
    source_tables = TypeAdapter(dict[str, object]).validate_python(receipt.get("source_tables"))
    source = DownloadSource(
        id="musicbrainz_bulk_derived_capture",
        adapter="musicbrainz_postgres_derived_v1",
        snapshot=str(receipt["snapshot"]),
        url=HttpUrl(str(receipt["derived_archive_url"])),
        discovery_url=HttpUrl("https://musicbrainz.org/doc/MusicBrainz_Database/Download"),
        expected_content_type="application/octet-stream",
        compression="tar.bz2",
        expected_bytes=_require_integer(receipt["derived_archive_bytes"]),
        checksum_algorithm="sha256",
        checksum=str(receipt["derived_archive_sha256"]),
        data_license="CC-BY-NC-SA-3.0",
        license_url=_LICENSE_URL,
        rights_classification="restricted_research",
        local_only=True,
        normalize=True,
        local_search=True,
        display=True,
        embed=True,
        train=True,
        export_metadata=False,
    )
    if source.snapshot != receipt.get("snapshot"):
        raise BulkArtistTagError("bulk core and derived source snapshots differ")
    captures = _source_captures(
        resolved_paths["derived_archive"],
        source,
        CoreArtistPrefixReceipt(
            snapshot=str(receipt["snapshot"]),
            archive_url=str(receipt["core_archive_url"]),
            archive_bytes=_require_integer(receipt["core_archive_bytes"]),
            archive_sha256=str(receipt["core_archive_published_sha256"]),
            prefix_bytes=_require_integer(receipt["core_prefix_bytes"]),
            prefix_sha256=str(receipt["core_prefix_sha256"]),
            artist_member_bytes=_require_integer(source_tables["member_bytes"]),
            artist_member_sha256=str(source_tables["member_sha256"]),
            artist_row_count=_require_integer(source_tables["row_count"]),
            schema_sequence=str(receipt["core_schema_sequence"]),
            observed_at=str(receipt["core_prefix_observed_at"]),
        ),
    )
    if captures != receipt.get("source_captures"):
        raise BulkArtistTagError("bulk artist-tag license or source listing captures changed")
    core_receipt = CoreArtistPrefixReceipt(
        snapshot=str(receipt["snapshot"]),
        archive_url=str(receipt["core_archive_url"]),
        archive_bytes=_require_integer(receipt["core_archive_bytes"]),
        archive_sha256=str(receipt["core_archive_published_sha256"]),
        prefix_bytes=_require_integer(receipt["core_prefix_bytes"]),
        prefix_sha256=str(receipt["core_prefix_sha256"]),
        artist_member_bytes=_require_integer(source_tables["member_bytes"]),
        artist_member_sha256=str(source_tables["member_sha256"]),
        artist_row_count=_require_integer(source_tables["row_count"]),
        schema_sequence=str(receipt["core_schema_sequence"]),
        observed_at=str(receipt["core_prefix_observed_at"]),
    )
    _artist_map, found_ids, core_facts = _core_artist_rows(
        resolved_paths["core_prefix"], core_receipt, selected_ids
    )
    if core_facts != source_tables or found_ids != selected_ids - absent:
        raise BulkArtistTagError("core artist UUID join does not match the source receipt")
    rows_sha, rows_bytes = sha256_file(rows_path)
    if rows_sha != receipt.get("rows_sha256") or rows_bytes != receipt.get("rows_bytes"):
        raise BulkArtistTagError("bulk artist-tag JSONL bytes differ from its receipt")
    observed_ids: set[str] = set()
    count_categories: Counter[str] = Counter()
    previous_id = ""
    row_count = 0
    with rows_path.open("rb") as stream:
        for raw in stream:
            row = TypeAdapter(dict[str, object]).validate_json(raw)
            identity = row.get("artist_mbid")
            if not isinstance(identity, str):
                raise BulkArtistTagError("bulk artist-tag row has no UUID")
            try:
                canonical_identity = str(UUID(identity))
            except ValueError:
                raise BulkArtistTagError("bulk artist-tag row has an invalid UUID") from None
            if canonical_identity != identity or identity <= previous_id:
                raise BulkArtistTagError("bulk artist-tag UUID rows are invalid or unordered")
            previous_id = identity
            if identity not in selected_ids or identity in observed_ids:
                raise BulkArtistTagError("bulk artist-tag rows do not match exact selected UUIDs")
            observed_ids.add(identity)
            row_count += 1
            state = row.get("source_state")
            tags = TypeAdapter(list[dict[str, object]]).validate_python(row.get("tags"))
            if identity in absent:
                if (
                    state != "absent_from_current_artist_dump"
                    or row.get("name") is not None
                    or tags
                ):
                    raise BulkArtistTagError("absent UUID row must retain an explicit empty status")
            elif state != "present_in_artist_dump" or not isinstance(row.get("name"), str):
                raise BulkArtistTagError("present UUID row lacks source-native artist identity")
            if (
                row.get("source_role") != "bulk_musicbrainz_aggregate_artist_tag"
                or row.get("source_response_sha256") != receipt.get("derived_archive_sha256")
                or row.get("genres") != []
            ):
                raise BulkArtistTagError("bulk aggregate tags cannot claim a native genre identity")
            source_refs = TypeAdapter(list[str]).validate_python(row.get("source_refs"))
            if identity in absent and source_refs:
                raise BulkArtistTagError("absent UUID row cannot claim MusicBrainz source rows")
            if identity not in absent and len(source_refs) != _PRESENT_SOURCE_REFERENCE_COUNT:
                raise BulkArtistTagError("present UUID row lacks its exact source table references")
            seen_tag_ids: set[int] = set()
            previous_tag_row = 0
            for tag in tags:
                if (
                    not isinstance(tag.get("name"), str)
                    or not tag.get("name")
                    or not isinstance(tag.get("count"), int)
                    or isinstance(tag.get("count"), bool)
                    or not isinstance(tag.get("tag_id"), int)
                    or isinstance(tag.get("tag_id"), bool)
                    or _require_integer(tag["tag_id"]) <= 0
                    or not isinstance(tag.get("source_row"), int)
                    or isinstance(tag.get("source_row"), bool)
                    or _require_integer(tag["source_row"]) <= previous_tag_row
                    or not isinstance(tag.get("source_row_sha256"), str)
                    or len(str(tag["source_row_sha256"])) != _SHA256_LENGTH
                    or not set(str(tag["source_row_sha256"])) <= _SHA256
                ):
                    raise BulkArtistTagError("raw tag evidence lacks an exact name, ID, or count")
                tag_id = _require_integer(tag["tag_id"])
                if tag_id in seen_tag_ids:
                    raise BulkArtistTagError("bulk artist-tag row repeats an exact tag ID")
                seen_tag_ids.add(tag_id)
                previous_tag_row = _require_integer(tag["source_row"])
                count = _require_integer(tag["count"])
                category = "positive" if count > 0 else "zero" if count == 0 else "negative"
                count_categories[f"primary_artist_tag_{category}_row_count"] += 1
            yield row
    counts = TypeAdapter(dict[str, int]).validate_python(receipt.get("counts"))
    if (
        row_count != expected_count
        or observed_ids != selected_ids
        or count_categories
        != Counter(
            {
                key: counts[key]
                for key in (
                    "primary_artist_tag_positive_row_count",
                    "primary_artist_tag_zero_row_count",
                    "primary_artist_tag_negative_row_count",
                )
                if counts.get(key, 0)
            }
        )
        or len(absent) != counts.get("projected_artist_absent_from_dump_count")
        or counts.get("projected_artist_count") != expected_count
    ):
        raise BulkArtistTagError("bulk artist-tag rows do not partition the complete selection")


def verify_bulk_artist_tag_artifact_receipt(
    *, directory: Path, expected_count: int = 198_409
) -> dict[str, object]:
    """Verify retained source bindings and the complete JSONL partition for a consumer."""
    for _row in iter_bulk_artist_tag_rows(directory=directory, expected_count=expected_count):
        pass
    return TypeAdapter(dict[str, object]).validate_json((directory / "receipt.json").read_bytes())
