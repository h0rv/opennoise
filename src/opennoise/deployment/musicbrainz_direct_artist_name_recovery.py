"""Recover custody-only canonical names from the pinned MusicBrainz artist dump.

The output is an exact-MBID extension of the existing direct name custody
object. It carries no memberships and authorizes no public use.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final, Literal

import zstandard
from pydantic import ConfigDict, Field, model_validator

from opennoise.deployment.musicbrainz_direct_canonical_artist_name_custody import (
    DirectCanonicalArtistNameCustodyError,
    DirectCanonicalArtistNameCustodyReceipt,
    iter_verified_direct_canonical_artist_names,
    verify_direct_canonical_artist_name_custody,
)
from opennoise.deployment.musicbrainz_direct_proper_genre_custody import (
    DirectProperGenreCustodyError,
    DirectProperGenreCustodyReceipt,
    iter_verified_portable_direct_proper_genre_claims,
    verify_portable_direct_proper_genre_custody,
)
from opennoise.models import FrozenModel
from opennoise.models.pipeline import SourceLimits
from opennoise.sources.musicbrainz import iter_artist_archive_raw_records

if TYPE_CHECKING:
    from collections.abc import Iterator

_REVISION: Final = "musicbrainz-direct-artist-name-recovery-v1"
_POLICY: Final = "custody_only_no_membership_or_publication_claims"
_OBJECT_PREFIX: Final = "musicbrainz-direct-artist-name-recovery/sha256"
_SOURCE_KEY: Final = "musicbrainz_json_artist_research_20260829"
_SOURCE_SNAPSHOT: Final = "20260829-001001"
_PINNED_ARCHIVE_SHA256: Final = "396fb476984234dd68650c59219d5e0bd0d900abccd6f4e3fe1a6160918ffe1d"
_PINNED_ARCHIVE_BYTES: Final = 1_695_597_804
_MBID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_MAX_OBJECT_BYTES: Final = 12 * 1024 * 1024
_MAX_LINE_BYTES: Final = 4 * 1024
_MAX_UNCOMPRESSED_BYTES: Final = 32 * 1024 * 1024
_MAX_NAME_FACT_COUNT: Final = 40_000
_MIN_CONFLICT_VARIANTS: Final = 2
_MIN_OUTPUT_FREE_BYTES: Final = 16 * 1024 * 1024


class DirectArtistNameRecoveryError(RuntimeError):
    """Report invalid inputs or a violated direct-name recovery boundary."""


class _ArtistNameEnvelope(FrozenModel):
    """Read only identity and canonical name from an artist source record."""

    model_config = ConfigDict(frozen=True, strict=True, extra="ignore")

    id: str = Field(pattern=_MBID.pattern)
    name: object = None


class DirectArtistNameRecoveryRow(FrozenModel):
    """One unique canonical name variant and its exact source provenance."""

    artist_mbid: str = Field(pattern=_MBID.pattern)
    canonical_name: str = Field(min_length=1)
    source_record_sha256: str = Field(pattern=_SHA256.pattern)
    source_record_ordinal: int = Field(ge=0)
    source_observation_count: int = Field(gt=0)
    name_status: Literal["unique_canonical_name", "conflicting_name_variant"]


class DirectArtistNameRecoveryReceipt(FrozenModel):
    """Typed receipt for an append-only, custody-only recovery object."""

    revision: Literal["musicbrainz-direct-artist-name-recovery-v1"] = _REVISION
    custody_policy: Literal["custody_only_no_membership_or_publication_claims"] = _POLICY
    public_export_authorized: Literal[False] = False
    serving_authorized: Literal[False] = False
    membership_claims_authorized: Literal[False] = False
    historical_assignments_read: Literal[False] = False
    name_source: Literal["musicbrainz_artist_archive_top_level_id_and_name"] = (
        "musicbrainz_artist_archive_top_level_id_and_name"
    )
    name_join: Literal["exact_artist_mbid_only"] = "exact_artist_mbid_only"
    credited_as_fallback_used: Literal[False] = False
    direct_custody_receipt_byte_sha256: str = Field(pattern=_SHA256.pattern)
    direct_custody_receipt_output_sha256: str = Field(pattern=_SHA256.pattern)
    direct_claims_object_sha256: str = Field(pattern=_SHA256.pattern)
    name_custody_receipt_byte_sha256: str = Field(pattern=_SHA256.pattern)
    name_custody_receipt_output_sha256: str = Field(pattern=_SHA256.pattern)
    name_custody_object_sha256: str = Field(pattern=_SHA256.pattern)
    source_archive_key: Literal["musicbrainz_artist_json_archive"] = (
        "musicbrainz_artist_json_archive"
    )
    source_key: Literal["musicbrainz_json_artist_research_20260829"] = _SOURCE_KEY
    source_archive_snapshot: str = _SOURCE_SNAPSHOT
    source_archive_sha256: str = Field(pattern=_SHA256.pattern)
    source_archive_byte_size: int = Field(gt=0)
    source_record_count: int = Field(ge=0)
    direct_artist_mbid_count: int = Field(ge=0)
    prior_canonical_name_count: int = Field(ge=0)
    recovery_target_count: int = Field(ge=0)
    targeted_source_observation_count: int = Field(ge=0)
    recovered_unique_mbid_count: int = Field(ge=0)
    conflicting_mbid_count: int = Field(ge=0)
    conflicting_name_variant_count: int = Field(ge=0)
    invalid_name_observation_count: int = Field(ge=0)
    duplicate_same_name_observation_count: int = Field(ge=0)
    malformed_source_record_count: int = Field(ge=0)
    oversized_source_record_count: int = Field(ge=0)
    missing_mbid_count: int = Field(ge=0)
    invalid_name_only_mbid_count: int = Field(ge=0)
    recovery_object_row_count: int = Field(ge=0, le=_MAX_NAME_FACT_COUNT)
    recovery_object_key: str = Field(pattern=rf"^{_OBJECT_PREFIX}/[0-9a-f]{{64}}\.jsonl\.zst$")
    recovery_object_sha256: str = Field(pattern=_SHA256.pattern)
    recovery_object_byte_size: int = Field(gt=0, le=_MAX_OBJECT_BYTES)
    recovery_rows_uncompressed_sha256: str = Field(pattern=_SHA256.pattern)
    output_sha256: str = Field(pattern=_SHA256.pattern)

    @model_validator(mode="after")
    def _receipt_counts_partition_targets(self) -> DirectArtistNameRecoveryReceipt:
        if self.recovery_target_count != (
            self.recovered_unique_mbid_count
            + self.conflicting_mbid_count
            + self.missing_mbid_count
            + self.invalid_name_only_mbid_count
        ):
            raise ValueError("recovery counts do not partition the missing-name targets")
        if self.recovery_object_row_count != (
            self.recovered_unique_mbid_count + self.conflicting_name_variant_count
        ):
            raise ValueError("recovery object rows do not match unique and conflict accounting")
        if self.direct_artist_mbid_count != (
            self.prior_canonical_name_count + self.recovery_target_count
        ):
            raise ValueError(
                "direct artist MBIDs do not partition prior names and recovery targets"
            )
        if self.recovery_object_key != f"{_OBJECT_PREFIX}/{self.recovery_object_sha256}.jsonl.zst":
            raise ValueError("recovery object key does not content-address its bytes")
        return self


@dataclass(slots=True)
class _NameVariant:
    source_record_sha256: str
    source_record_ordinal: int
    observation_count: int = 1


@dataclass(frozen=True, slots=True)
class _WrittenRows:
    row_count: int
    unique_mbid_count: int
    conflict_mbid_count: int
    conflict_variant_count: int
    duplicate_observation_count: int
    uncompressed_sha256: str


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def _sha256_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _fsync_directory(directory: Path) -> None:
    """Persist a newly linked directory entry on platforms with directory fsync."""
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _preflight_outputs(*, object_store: Path, receipt_output: Path) -> None:
    """Create output parents and prove bounded local output capacity before input scans."""
    if receipt_output.exists() or receipt_output.is_symlink():
        raise FileExistsError(f"refusing to replace recovery receipt: {receipt_output}")
    receipt_output.parent.mkdir(parents=True, exist_ok=True)
    object_store.mkdir(parents=True, exist_ok=True)
    for directory in {receipt_output.parent, object_store}:
        if shutil.disk_usage(directory).free < _MIN_OUTPUT_FREE_BYTES:
            raise DirectArtistNameRecoveryError(
                f"insufficient free space for bounded recovery output under {directory}"
            )
        with tempfile.NamedTemporaryFile(dir=directory, prefix=".mb-name-recovery-probe-"):
            pass


def receipt_sha256(receipt: DirectArtistNameRecoveryReceipt) -> str:
    """Hash the receipt body without trusting its embedded self-hash."""
    body = receipt.model_dump(mode="json", exclude={"output_sha256"})
    return hashlib.sha256(_canonical_json(body)).hexdigest()


def _load_receipts(  # noqa: PLR0913 - custody inputs are deliberately explicit.
    *,
    direct_custody_receipt: Path,
    direct_object_store: Path,
    direct_custody_receipt_sha256: str,
    name_custody_receipt: Path,
    name_object_store: Path,
    name_custody_receipt_sha256: str,
) -> tuple[
    DirectProperGenreCustodyReceipt,
    DirectCanonicalArtistNameCustodyReceipt,
    set[str],
    set[str],
    str,
    str,
]:
    direct_bytes = direct_custody_receipt.read_bytes()
    name_bytes = name_custody_receipt.read_bytes()
    direct_byte_sha = hashlib.sha256(direct_bytes).hexdigest()
    name_byte_sha = hashlib.sha256(name_bytes).hexdigest()
    if direct_byte_sha != direct_custody_receipt_sha256:
        raise DirectArtistNameRecoveryError("direct custody receipt bytes are not the pinned input")
    if name_byte_sha != name_custody_receipt_sha256:
        raise DirectArtistNameRecoveryError("name custody receipt bytes are not the pinned input")
    try:
        direct_receipt = DirectProperGenreCustodyReceipt.model_validate_json(direct_bytes)
        name_receipt = DirectCanonicalArtistNameCustodyReceipt.model_validate_json(name_bytes)
        verify_portable_direct_proper_genre_custody(
            direct_receipt, object_store=direct_object_store
        )
        verify_direct_canonical_artist_name_custody(name_receipt, object_store=name_object_store)
        if (
            name_receipt.direct_custody_receipt_byte_sha256 != direct_byte_sha
            or name_receipt.direct_custody_receipt_output_sha256 != direct_receipt.output_sha256
            or name_receipt.direct_claims_object_sha256 != direct_receipt.claims_object_sha256
        ):
            raise DirectArtistNameRecoveryError(
                "name custody receipt does not bind the pinned direct custody receipt"
            )
        direct_ids = {
            claim.artist_mbid
            for claim in iter_verified_portable_direct_proper_genre_claims(
                direct_receipt, object_store=direct_object_store
            )
        }
        name_ids = {
            name.artist_mbid
            for name in iter_verified_direct_canonical_artist_names(
                name_receipt, object_store=name_object_store
            )
        }
    except (
        DirectProperGenreCustodyError,
        DirectCanonicalArtistNameCustodyError,
        ValueError,
    ) as error:
        raise DirectArtistNameRecoveryError(
            "pinned v1 custody inputs failed verification"
        ) from error
    if len(direct_ids) != direct_receipt.artist_mbid_count:
        raise DirectArtistNameRecoveryError("direct artist MBID set does not match its receipt")
    if len(name_ids) != name_receipt.canonical_name_count or not name_ids <= direct_ids:
        raise DirectArtistNameRecoveryError(
            "name MBID set is not an exact subset of direct artists"
        )
    return (
        direct_receipt,
        name_receipt,
        direct_ids,
        name_ids,
        direct_byte_sha,
        name_byte_sha,
    )


def _source_limits() -> SourceLimits:
    """Use the documented bounds for the 2026-08-29 artist archive."""
    return SourceLimits(
        max_archive_bytes=2 * 1024 * 1024 * 1024,
        max_member_bytes=64 * 1024 * 1024 * 1024,
        max_record_bytes=64 * 1024 * 1024,
        max_records=3_100_000,
        max_decompression_ratio=128.0,
        timeout_seconds=6 * 60 * 60,
    )


def _collect_variants(
    *, archive: Path, target_ids: set[str], limits: SourceLimits
) -> tuple[dict[str, dict[str, _NameVariant]], set[str], int, int, int, int, int]:
    variants: dict[str, dict[str, _NameVariant]] = {}
    invalid_name_ids: set[str] = set()
    source_record_count = targeted_observations = invalid_names = oversized = malformed = 0
    for raw in iter_artist_archive_raw_records(archive, limits):
        source_record_count += 1
        if raw.payload is None:
            oversized += 1
            continue
        try:
            envelope = _ArtistNameEnvelope.model_validate_json(raw.payload)
        except ValueError:
            malformed += 1
            continue
        mbid = envelope.id
        if mbid not in target_ids:
            continue
        targeted_observations += 1
        if not isinstance(envelope.name, str) or not envelope.name.strip():
            invalid_names += 1
            invalid_name_ids.add(mbid)
            continue
        artist_variants = variants.setdefault(mbid, {})
        previous = artist_variants.get(envelope.name)
        if previous is None:
            artist_variants[envelope.name] = _NameVariant(
                source_record_sha256=raw.content_sha256,
                source_record_ordinal=raw.ordinal,
            )
        else:
            previous.observation_count += 1
            if raw.ordinal < previous.source_record_ordinal:
                previous.source_record_sha256 = raw.content_sha256
                previous.source_record_ordinal = raw.ordinal
    return (
        variants,
        invalid_name_ids,
        source_record_count,
        targeted_observations,
        invalid_names,
        oversized,
        malformed,
    )


def _rows(
    variants: dict[str, dict[str, _NameVariant]],
) -> tuple[tuple[DirectArtistNameRecoveryRow, ...], int, int, int, int]:
    output: list[DirectArtistNameRecoveryRow] = []
    unique_count = conflict_mbid_count = conflict_variant_count = duplicate_count = 0
    for mbid, names in sorted(variants.items()):
        if len(names) == 1:
            unique_count += 1
            status: Literal["unique_canonical_name", "conflicting_name_variant"] = (
                "unique_canonical_name"
            )
        else:
            conflict_mbid_count += 1
            conflict_variant_count += len(names)
            status = "conflicting_name_variant"
        for canonical_name, variant in sorted(names.items()):
            duplicate_count += variant.observation_count - 1
            output.append(
                DirectArtistNameRecoveryRow(
                    artist_mbid=mbid,
                    canonical_name=canonical_name,
                    source_record_sha256=variant.source_record_sha256,
                    source_record_ordinal=variant.source_record_ordinal,
                    source_observation_count=variant.observation_count,
                    name_status=status,
                )
            )
    output.sort(key=lambda row: (row.artist_mbid, row.canonical_name))
    if len(output) > _MAX_NAME_FACT_COUNT:
        raise DirectArtistNameRecoveryError("recovery projection exceeds its row bound")
    return tuple(output), unique_count, conflict_mbid_count, conflict_variant_count, duplicate_count


def _write_object(rows: tuple[DirectArtistNameRecoveryRow, ...], path: Path) -> _WrittenRows:
    digest = hashlib.sha256()
    unique_count = conflict_variant_count = duplicate_count = 0
    with path.open("wb") as compressed:
        compressor = zstandard.ZstdCompressor(level=6, threads=0, write_checksum=True)
        with compressor.stream_writer(compressed, closefd=False) as writer:
            for row in rows:
                line = _canonical_json(row.model_dump(mode="json")) + b"\n"
                writer.write(line)
                digest.update(line)
                if row.name_status == "unique_canonical_name":
                    unique_count += 1
                else:
                    conflict_variant_count += 1
                duplicate_count += row.source_observation_count - 1
        compressed.flush()
        os.fsync(compressed.fileno())
    conflict_mbid_count = sum(
        1
        for mbid in {
            row.artist_mbid for row in rows if row.name_status == "conflicting_name_variant"
        }
        if mbid
    )
    return _WrittenRows(
        row_count=len(rows),
        unique_mbid_count=unique_count,
        conflict_mbid_count=conflict_mbid_count,
        conflict_variant_count=conflict_variant_count,
        duplicate_observation_count=duplicate_count,
        uncompressed_sha256=digest.hexdigest(),
    )


def _build_direct_artist_name_recovery(  # noqa: PLR0913 - test seam keeps fixture source bindings explicit.
    *,
    direct_custody_receipt: Path,
    direct_object_store: Path,
    direct_custody_receipt_sha256: str,
    name_custody_receipt: Path,
    name_object_store: Path,
    name_custody_receipt_sha256: str,
    source_archive: Path,
    expected_source_archive_sha256: str = _PINNED_ARCHIVE_SHA256,
    expected_source_archive_bytes: int = _PINNED_ARCHIVE_BYTES,
    source_archive_snapshot: str = _SOURCE_SNAPSHOT,
    object_store: Path,
    receipt_output: Path,
) -> DirectArtistNameRecoveryReceipt:
    """Build a fixture or pinned-source object using an explicit source binding."""
    if not _SHA256.fullmatch(expected_source_archive_sha256) or expected_source_archive_bytes <= 0:
        raise DirectArtistNameRecoveryError("source archive binding is invalid")
    _preflight_outputs(object_store=object_store, receipt_output=receipt_output)
    (
        direct_receipt,
        name_receipt,
        direct_ids,
        prior_name_ids,
        direct_receipt_byte_sha,
        name_receipt_byte_sha,
    ) = _load_receipts(
        direct_custody_receipt=direct_custody_receipt,
        direct_object_store=direct_object_store,
        direct_custody_receipt_sha256=direct_custody_receipt_sha256,
        name_custody_receipt=name_custody_receipt,
        name_object_store=name_object_store,
        name_custody_receipt_sha256=name_custody_receipt_sha256,
    )
    archive_sha256, archive_bytes = _sha256_file(source_archive)
    if (archive_sha256, archive_bytes) != (
        expected_source_archive_sha256,
        expected_source_archive_bytes,
    ):
        raise DirectArtistNameRecoveryError("artist archive does not match the pinned source bytes")
    targets = direct_ids - prior_name_ids
    (
        variants,
        invalid_name_ids,
        source_records,
        targeted_observations,
        invalid_names,
        oversized,
        malformed,
    ) = _collect_variants(archive=source_archive, target_ids=targets, limits=_source_limits())
    rows, unique_count, conflict_count, conflict_variants, duplicates = _rows(variants)
    invalid_only_ids = invalid_name_ids - variants.keys()
    invalid_only_count = len(invalid_only_ids)
    missing_count = len(targets - variants.keys() - invalid_only_ids)
    with tempfile.TemporaryDirectory(prefix="mb-direct-name-recovery-", dir=object_store) as temp:
        staged = Path(temp) / "names.jsonl.zst"
        written = _write_object(rows, staged)
        object_sha, object_bytes = _sha256_file(staged)
        if object_bytes > _MAX_OBJECT_BYTES:
            raise DirectArtistNameRecoveryError("recovery object exceeds compressed-byte bound")
        key = f"{_OBJECT_PREFIX}/{object_sha}.jsonl.zst"
        destination = object_store / key
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            existing_sha, existing_bytes = _sha256_file(destination)
            if destination.is_symlink() or (existing_sha, existing_bytes) != (
                object_sha,
                object_bytes,
            ):
                raise DirectArtistNameRecoveryError("existing recovery object has wrong bytes")
        else:
            os.link(staged, destination)
            _fsync_directory(destination.parent)
    base = DirectArtistNameRecoveryReceipt(
        direct_custody_receipt_byte_sha256=direct_receipt_byte_sha,
        direct_custody_receipt_output_sha256=direct_receipt.output_sha256,
        direct_claims_object_sha256=direct_receipt.claims_object_sha256,
        name_custody_receipt_byte_sha256=name_receipt_byte_sha,
        name_custody_receipt_output_sha256=name_receipt.output_sha256,
        name_custody_object_sha256=name_receipt.names_object_sha256,
        source_archive_snapshot=source_archive_snapshot,
        source_archive_sha256=archive_sha256,
        source_archive_byte_size=archive_bytes,
        source_record_count=source_records,
        direct_artist_mbid_count=len(direct_ids),
        prior_canonical_name_count=len(prior_name_ids),
        recovery_target_count=len(targets),
        targeted_source_observation_count=targeted_observations,
        recovered_unique_mbid_count=unique_count,
        conflicting_mbid_count=conflict_count,
        conflicting_name_variant_count=conflict_variants,
        invalid_name_observation_count=invalid_names,
        duplicate_same_name_observation_count=duplicates,
        malformed_source_record_count=malformed,
        oversized_source_record_count=oversized,
        missing_mbid_count=missing_count,
        invalid_name_only_mbid_count=invalid_only_count,
        recovery_object_row_count=written.row_count,
        recovery_object_key=key,
        recovery_object_sha256=object_sha,
        recovery_object_byte_size=object_bytes,
        recovery_rows_uncompressed_sha256=written.uncompressed_sha256,
        output_sha256="0" * 64,
    )
    receipt = base.model_copy(update={"output_sha256": receipt_sha256(base)})
    temporary = receipt_output.parent / f".{receipt_output.name}.{os.getpid()}.tmp"
    try:
        with temporary.open("xb") as stream:
            stream.write(_canonical_json(receipt.model_dump(mode="json")) + b"\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, receipt_output)
        _fsync_directory(receipt_output.parent)
    except FileExistsError as error:
        raise FileExistsError(f"refusing to replace recovery receipt: {receipt_output}") from error
    finally:
        temporary.unlink(missing_ok=True)
    return receipt


def build_direct_artist_name_recovery(  # noqa: PLR0913 - verified input paths stay explicit.
    *,
    direct_custody_receipt: Path,
    direct_object_store: Path,
    direct_custody_receipt_sha256: str,
    name_custody_receipt: Path,
    name_object_store: Path,
    name_custody_receipt_sha256: str,
    source_archive: Path,
    object_store: Path,
    receipt_output: Path,
) -> DirectArtistNameRecoveryReceipt:
    """Build against only the pinned MusicBrainz artist archive source binding."""
    return _build_direct_artist_name_recovery(
        direct_custody_receipt=direct_custody_receipt,
        direct_object_store=direct_object_store,
        direct_custody_receipt_sha256=direct_custody_receipt_sha256,
        name_custody_receipt=name_custody_receipt,
        name_object_store=name_object_store,
        name_custody_receipt_sha256=name_custody_receipt_sha256,
        source_archive=source_archive,
        expected_source_archive_sha256=_PINNED_ARCHIVE_SHA256,
        expected_source_archive_bytes=_PINNED_ARCHIVE_BYTES,
        source_archive_snapshot=_SOURCE_SNAPSHOT,
        object_store=object_store,
        receipt_output=receipt_output,
    )


def _iter_rows(path: Path) -> Iterator[DirectArtistNameRecoveryRow]:
    try:
        with (
            path.open("rb") as compressed,
            zstandard.ZstdDecompressor().stream_reader(compressed, closefd=False) as reader,
        ):
            buffered = io.BufferedReader(reader)
            decompressed_bytes = 0
            previous_key: tuple[str, str] | None = None
            while raw_line := buffered.readline(_MAX_LINE_BYTES + 1):
                if len(raw_line) > _MAX_LINE_BYTES or not raw_line.endswith(b"\n"):
                    raise DirectArtistNameRecoveryError("recovery object has an oversized line")
                decompressed_bytes += len(raw_line)
                if decompressed_bytes > _MAX_UNCOMPRESSED_BYTES:
                    raise DirectArtistNameRecoveryError(
                        "recovery object exceeds decompressed bound"
                    )
                row = DirectArtistNameRecoveryRow.model_validate_json(raw_line)
                key = (row.artist_mbid, row.canonical_name)
                if previous_key is not None and key <= previous_key:
                    raise DirectArtistNameRecoveryError("recovery rows are not strictly ordered")
                previous_key = key
                yield row
    except (OSError, ValueError, zstandard.ZstdError) as error:
        if isinstance(error, DirectArtistNameRecoveryError):
            raise
        raise DirectArtistNameRecoveryError("recovery object is unreadable") from error


def verify_direct_artist_name_recovery(  # noqa: C901 - grouped receipt invariants stay together.
    receipt: DirectArtistNameRecoveryReceipt, *, object_store: Path
) -> None:
    """Verify the receipt and compressed exact-name recovery object."""
    if receipt_sha256(receipt) != receipt.output_sha256:
        raise DirectArtistNameRecoveryError("recovery receipt hash does not replay")
    path = object_store / receipt.recovery_object_key
    object_sha, object_bytes = _sha256_file(path)
    if (object_sha, object_bytes) != (
        receipt.recovery_object_sha256,
        receipt.recovery_object_byte_size,
    ):
        raise DirectArtistNameRecoveryError("recovery object bytes do not match receipt")
    digest = hashlib.sha256()
    rows = unique = conflict_mbids = conflict_variants = duplicates = 0
    current_mbid: str | None = None
    current_status: Literal["unique_canonical_name", "conflicting_name_variant"] | None = None
    current_variant_count = 0

    def finish_group() -> None:
        nonlocal unique, conflict_mbids
        if current_mbid is None or current_status is None:
            return
        if current_status == "unique_canonical_name":
            if current_variant_count != 1:
                raise DirectArtistNameRecoveryError("unique name MBID has multiple rows")
            unique += 1
        else:
            if current_variant_count < _MIN_CONFLICT_VARIANTS:
                raise DirectArtistNameRecoveryError(
                    "conflicted MBID has fewer than two name variants"
                )
            conflict_mbids += 1

    for row in _iter_rows(path):
        line = _canonical_json(row.model_dump(mode="json")) + b"\n"
        digest.update(line)
        rows += 1
        duplicates += row.source_observation_count - 1
        if row.artist_mbid != current_mbid:
            finish_group()
            current_mbid = row.artist_mbid
            current_status = row.name_status
            current_variant_count = 0
        elif row.name_status != current_status:
            raise DirectArtistNameRecoveryError("one MBID mixes unique and conflicting name rows")
        current_variant_count += 1
        if row.name_status == "conflicting_name_variant":
            conflict_variants += 1
    finish_group()
    if (rows, unique, conflict_mbids, conflict_variants, duplicates, digest.hexdigest()) != (
        receipt.recovery_object_row_count,
        receipt.recovered_unique_mbid_count,
        receipt.conflicting_mbid_count,
        receipt.conflicting_name_variant_count,
        receipt.duplicate_same_name_observation_count,
        receipt.recovery_rows_uncompressed_sha256,
    ):
        raise DirectArtistNameRecoveryError("recovery rows do not match receipt accounting")


def iter_verified_unique_recovered_names(
    receipt: DirectArtistNameRecoveryReceipt, *, object_store: Path
) -> Iterator[DirectArtistNameRecoveryRow]:
    """Yield only canonical names after verifying the custody object and receipt."""
    verify_direct_artist_name_recovery(receipt, object_store=object_store)
    for row in _iter_rows(object_store / receipt.recovery_object_key):
        if row.name_status == "unique_canonical_name":
            yield row
