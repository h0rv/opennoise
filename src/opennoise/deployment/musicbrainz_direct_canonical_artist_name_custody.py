"""Create a custody-only canonical-name projection for exact direct artist MBIDs.

The projection keeps MusicBrainz direct claims separate from name facts.  Each
row contains only an exact MBID and one unambiguous nested ``artist.name``.
It does not create memberships or authorize export or serving.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import sqlite3
import tempfile
from dataclasses import dataclass
from itertools import batched
from pathlib import Path
from typing import TYPE_CHECKING, Final, Literal

import zstandard
from pydantic import Field, model_validator

from opennoise.deployment.musicbrainz_direct_proper_genre_custody import (
    DirectProperGenreCustodyReceipt,
    iter_verified_portable_direct_proper_genre_claims,
)
from opennoise.models import FrozenModel
from opennoise.serving.local.musicbrainz_artist_metadata import (
    ArtistMetadataArtifact,
    load_artist_metadata_artifact,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

_REVISION: Final = "musicbrainz-direct-canonical-artist-name-custody-v1"
_POLICY: Final = "custody_only_no_membership_or_publication_claims"
_OBJECT_PREFIX: Final = "musicbrainz-direct-canonical-artist-name-custody/sha256"
_ARTIST_NAME_SOURCE: Final = "musicbrainz_release_group_nested_artist_name_only"
_SHA256: Final = re.compile(r"^[0-9a-f]{64}$")
_MBID: Final = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_MAX_OBJECT_BYTES: Final = 30 * 1024 * 1024
_MAX_NAME_COUNT: Final = 250_000
_MAX_LINE_BYTES: Final = 4 * 1024
_MAX_UNCOMPRESSED_BYTES: Final = 64 * 1024 * 1024
_SQLITE_BATCH_SIZE: Final = 900


class DirectCanonicalArtistNameCustodyError(RuntimeError):
    """Report a broken input or a violated custody boundary."""


class CanonicalArtistName(FrozenModel):
    """One name fact from a nested MusicBrainz artist record."""

    artist_mbid: str = Field(pattern=_MBID.pattern)
    canonical_name: str = Field(min_length=1)


class DirectCanonicalArtistNameCustodyReceipt(FrozenModel):
    """Pinned receipt for a name-fact object that is not a release input."""

    revision: Literal["musicbrainz-direct-canonical-artist-name-custody-v1"] = _REVISION
    custody_policy: Literal["custody_only_no_membership_or_publication_claims"] = _POLICY
    public_export_authorized: Literal[False] = False
    serving_authorized: Literal[False] = False
    membership_claims_authorized: Literal[False] = False
    historical_assignments_read: Literal[False] = False
    credited_as_fallback_used: Literal[False] = False
    canonical_name_source: Literal["musicbrainz_release_group_nested_artist_name_only"] = (
        _ARTIST_NAME_SOURCE
    )
    canonical_name_variant_count_required: Literal[1] = 1
    direct_custody_receipt_byte_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    direct_custody_receipt_output_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    direct_claims_object_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    direct_artist_mbid_count: int = Field(ge=0)
    metadata_artifact_byte_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    metadata_artifact_output_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    metadata_database_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    metadata_database_bytes: int = Field(gt=0)
    metadata_source_archive_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    canonical_name_count: int = Field(ge=0, le=_MAX_NAME_COUNT)
    absent_direct_artist_mbid_count: int = Field(ge=0)
    names_object_key: str = Field(pattern=rf"^{_OBJECT_PREFIX}/[0-9a-f]{{64}}\.jsonl\.zst$")
    names_object_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    names_object_byte_size: int = Field(gt=0, le=_MAX_OBJECT_BYTES)
    names_uncompressed_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    output_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _counts_and_object_key_are_bound(self) -> DirectCanonicalArtistNameCustodyReceipt:
        if (
            self.canonical_name_count + self.absent_direct_artist_mbid_count
            != self.direct_artist_mbid_count
        ):
            raise ValueError("name coverage does not partition direct artist MBIDs")
        if self.names_object_key != f"{_OBJECT_PREFIX}/{self.names_object_sha256}.jsonl.zst":
            raise ValueError("name object key does not content-address its bytes")
        return self


@dataclass(frozen=True, slots=True)
class _NameStreamCounts:
    count: int
    uncompressed_sha256: str


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def _sha256_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
            size += len(block)
    return digest.hexdigest(), size


def receipt_sha256(receipt: DirectCanonicalArtistNameCustodyReceipt) -> str:
    """Return the receipt hash without trusting its embedded self-hash."""
    return hashlib.sha256(
        _canonical_json(receipt.model_dump(mode="json", exclude={"output_sha256"}))
    ).hexdigest()


def _load_direct_receipt(path: Path) -> DirectProperGenreCustodyReceipt:
    try:
        return DirectProperGenreCustodyReceipt.model_validate_json(path.read_bytes())
    except (OSError, ValueError) as error:
        raise DirectCanonicalArtistNameCustodyError("direct custody receipt is invalid") from error


def _direct_artist_mbids(
    receipt: DirectProperGenreCustodyReceipt, object_store: Path
) -> tuple[str, ...]:
    try:
        seen = {
            claim.artist_mbid
            for claim in iter_verified_portable_direct_proper_genre_claims(
                receipt, object_store=object_store
            )
        }
    except (OSError, ValueError, zstandard.ZstdError, RuntimeError) as error:
        raise DirectCanonicalArtistNameCustodyError(
            "direct custody object is unreadable"
        ) from error
    if len(seen) != receipt.artist_mbid_count:
        raise DirectCanonicalArtistNameCustodyError("direct custody MBID count does not replay")
    return tuple(sorted(seen))


def _verified_metadata_artifact(
    path: Path, database: Path
) -> tuple[ArtistMetadataArtifact, str, int]:
    try:
        artifact = load_artist_metadata_artifact(path)
    except ValueError as error:
        raise DirectCanonicalArtistNameCustodyError("metadata artifact is invalid") from error
    database_sha256, database_bytes = _sha256_file(database)
    if (database_sha256, database_bytes) != (
        artifact.metadata_database_sha256,
        artifact.metadata_database_bytes,
    ):
        raise DirectCanonicalArtistNameCustodyError("metadata database does not match its artifact")
    return artifact, database_sha256, database_bytes


def _canonical_names(
    database: Path, artist_mbids: tuple[str, ...]
) -> tuple[CanonicalArtistName, ...]:
    names: list[CanonicalArtistName] = []
    try:
        with sqlite3.connect(f"file:{database.absolute()}?mode=ro", uri=True) as connection:
            connection.execute("PRAGMA query_only = ON")
            for group in batched(artist_mbids, _SQLITE_BATCH_SIZE, strict=False):
                placeholders = ",".join("?" for _ in group)
                rows = connection.execute(
                    f"SELECT artist_mbid, canonical_name FROM artist_summary "  # noqa: S608
                    f"WHERE artist_mbid IN ({placeholders}) "
                    "AND canonical_name_variant_count = 1 AND canonical_name IS NOT NULL",
                    group,
                )
                names.extend(
                    CanonicalArtistName(artist_mbid=str(mbid), canonical_name=str(name))
                    for mbid, name in rows
                )
    except sqlite3.Error as error:
        raise DirectCanonicalArtistNameCustodyError(
            "metadata database cannot supply canonical names"
        ) from error
    names.sort(key=lambda item: item.artist_mbid)
    if len({item.artist_mbid for item in names}) != len(names):
        raise DirectCanonicalArtistNameCustodyError(
            "metadata database returned duplicate artist names"
        )
    return tuple(names)


def _write_name_object(names: tuple[CanonicalArtistName, ...], output: Path) -> _NameStreamCounts:
    digest = hashlib.sha256()
    with output.open("wb") as compressed:
        compressor = zstandard.ZstdCompressor(level=6, threads=0, write_checksum=True)
        with compressor.stream_writer(compressed, closefd=False) as writer:
            for name in names:
                line = _canonical_json(name.model_dump(mode="json")) + b"\n"
                writer.write(line)
                digest.update(line)
    return _NameStreamCounts(count=len(names), uncompressed_sha256=digest.hexdigest())


def _canonical_name_stream_sha256(names: tuple[CanonicalArtistName, ...]) -> str:
    digest = hashlib.sha256()
    for name in names:
        digest.update(_canonical_json(name.model_dump(mode="json")) + b"\n")
    return digest.hexdigest()


def build_direct_canonical_artist_name_custody(  # noqa: PLR0913 - custody inputs are explicit.
    *,
    direct_custody_receipt: Path,
    direct_object_store: Path,
    metadata_artifact: Path,
    metadata_database: Path,
    object_store: Path,
    receipt_output: Path,
) -> DirectCanonicalArtistNameCustodyReceipt:
    """Write a content-addressed name-fact object for the verified direct MBID scope."""
    if receipt_output.exists():
        raise FileExistsError(f"refusing to replace existing custody receipt: {receipt_output}")
    direct_receipt = _load_direct_receipt(direct_custody_receipt)
    direct_mbids = _direct_artist_mbids(direct_receipt, direct_object_store)
    artifact, metadata_sha256, metadata_bytes = _verified_metadata_artifact(
        metadata_artifact, metadata_database
    )
    names = _canonical_names(metadata_database, direct_mbids)
    if len(names) > _MAX_NAME_COUNT:
        raise DirectCanonicalArtistNameCustodyError("name projection exceeds count bound")
    object_store.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="musicbrainz-name-custody-", dir=object_store
    ) as directory:
        staged = Path(directory) / "names.jsonl.zst"
        counts = _write_name_object(names, staged)
        object_sha256, object_bytes = _sha256_file(staged)
        if object_bytes > _MAX_OBJECT_BYTES:
            raise DirectCanonicalArtistNameCustodyError(
                "name projection exceeds compressed-byte bound"
            )
        key = f"{_OBJECT_PREFIX}/{object_sha256}.jsonl.zst"
        destination = object_store / key
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            existing_sha256, _ = _sha256_file(destination)
            if destination.is_symlink() or existing_sha256 != object_sha256:
                raise DirectCanonicalArtistNameCustodyError("existing name object has wrong bytes")
        else:
            os.link(staged, destination)
    direct_receipt_sha256, _ = _sha256_file(direct_custody_receipt)
    artifact_sha256, _ = _sha256_file(metadata_artifact)
    base = DirectCanonicalArtistNameCustodyReceipt(
        direct_custody_receipt_byte_sha256=direct_receipt_sha256,
        direct_custody_receipt_output_sha256=direct_receipt.output_sha256,
        direct_claims_object_sha256=direct_receipt.claims_object_sha256,
        direct_artist_mbid_count=len(direct_mbids),
        metadata_artifact_byte_sha256=artifact_sha256,
        metadata_artifact_output_sha256=artifact.output_sha256,
        metadata_database_sha256=metadata_sha256,
        metadata_database_bytes=metadata_bytes,
        metadata_source_archive_sha256=artifact.source_archive_sha256,
        canonical_name_count=counts.count,
        absent_direct_artist_mbid_count=len(direct_mbids) - counts.count,
        names_object_key=key,
        names_object_sha256=object_sha256,
        names_object_byte_size=object_bytes,
        names_uncompressed_sha256=counts.uncompressed_sha256,
        output_sha256="0" * 64,
    )
    receipt = base.model_copy(update={"output_sha256": receipt_sha256(base)})
    receipt_output.parent.mkdir(parents=True, exist_ok=True)
    temporary = receipt_output.parent / f".{receipt_output.name}.{os.getpid()}.tmp"
    try:
        with temporary.open("xb") as stream:
            stream.write(_canonical_json(receipt.model_dump(mode="json")) + b"\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, receipt_output)
    except FileExistsError as error:
        raise FileExistsError(
            f"refusing to replace existing custody receipt: {receipt_output}"
        ) from error
    finally:
        temporary.unlink(missing_ok=True)
    return receipt


def _stream_names(path: Path) -> Iterator[CanonicalArtistName]:
    try:
        with (
            path.open("rb") as compressed,
            zstandard.ZstdDecompressor().stream_reader(compressed, closefd=False) as reader,
        ):
            buffered = io.BufferedReader(reader)
            decompressed_bytes = 0
            while raw_line := buffered.readline(_MAX_LINE_BYTES + 1):
                if len(raw_line) > _MAX_LINE_BYTES or not raw_line.endswith(b"\n"):
                    raise DirectCanonicalArtistNameCustodyError("name object has an oversized line")
                decompressed_bytes += len(raw_line)
                if decompressed_bytes > _MAX_UNCOMPRESSED_BYTES:
                    raise DirectCanonicalArtistNameCustodyError(
                        "name object exceeds decompressed bound"
                    )
                yield CanonicalArtistName.model_validate_json(raw_line)
    except (OSError, ValueError, zstandard.ZstdError) as error:
        if isinstance(error, DirectCanonicalArtistNameCustodyError):
            raise
        raise DirectCanonicalArtistNameCustodyError("name object is unreadable") from error


def verify_direct_canonical_artist_name_custody(
    receipt: DirectCanonicalArtistNameCustodyReceipt, *, object_store: Path
) -> None:
    """Verify the receipt and its compact name-fact object without local sources."""
    if receipt_sha256(receipt) != receipt.output_sha256:
        raise DirectCanonicalArtistNameCustodyError("name custody receipt hash does not replay")
    object_path = object_store / receipt.names_object_key
    object_sha256, object_bytes = _sha256_file(object_path)
    if (object_sha256, object_bytes) != (
        receipt.names_object_sha256,
        receipt.names_object_byte_size,
    ):
        raise DirectCanonicalArtistNameCustodyError(
            "name custody object bytes do not match receipt"
        )
    digest = hashlib.sha256()
    previous_mbid = ""
    count = 0
    for name in _stream_names(object_path):
        if name.artist_mbid <= previous_mbid:
            raise DirectCanonicalArtistNameCustodyError(
                "name object MBIDs are not strictly ordered"
            )
        previous_mbid = name.artist_mbid
        digest.update(_canonical_json(name.model_dump(mode="json")) + b"\n")
        count += 1
    if (count, digest.hexdigest()) != (
        receipt.canonical_name_count,
        receipt.names_uncompressed_sha256,
    ):
        raise DirectCanonicalArtistNameCustodyError(
            "name custody object content does not match receipt"
        )


def verify_direct_canonical_artist_name_custody_from_inputs(  # noqa: PLR0913 - replay inputs are explicit.
    receipt: DirectCanonicalArtistNameCustodyReceipt,
    *,
    object_store: Path,
    direct_custody_receipt: Path,
    direct_object_store: Path,
    metadata_artifact: Path,
    metadata_database: Path,
) -> None:
    """Verify object bytes and replay their scope and name-source bindings."""
    verify_direct_canonical_artist_name_custody(receipt, object_store=object_store)
    direct_receipt = _load_direct_receipt(direct_custody_receipt)
    direct_receipt_sha256, _ = _sha256_file(direct_custody_receipt)
    if (
        direct_receipt_sha256,
        direct_receipt.output_sha256,
        direct_receipt.claims_object_sha256,
    ) != (
        receipt.direct_custody_receipt_byte_sha256,
        receipt.direct_custody_receipt_output_sha256,
        receipt.direct_claims_object_sha256,
    ):
        raise DirectCanonicalArtistNameCustodyError(
            "direct custody receipt differs from name receipt"
        )
    direct_mbids = _direct_artist_mbids(direct_receipt, direct_object_store)
    artifact, metadata_sha256, metadata_bytes = _verified_metadata_artifact(
        metadata_artifact, metadata_database
    )
    artifact_sha256, _ = _sha256_file(metadata_artifact)
    if (
        artifact_sha256,
        artifact.output_sha256,
        metadata_sha256,
        metadata_bytes,
        artifact.source_archive_sha256,
    ) != (
        receipt.metadata_artifact_byte_sha256,
        receipt.metadata_artifact_output_sha256,
        receipt.metadata_database_sha256,
        receipt.metadata_database_bytes,
        receipt.metadata_source_archive_sha256,
    ):
        raise DirectCanonicalArtistNameCustodyError("metadata source differs from name receipt")
    names = _canonical_names(metadata_database, direct_mbids)
    if (len(direct_mbids), len(names), len(direct_mbids) - len(names)) != (
        receipt.direct_artist_mbid_count,
        receipt.canonical_name_count,
        receipt.absent_direct_artist_mbid_count,
    ):
        raise DirectCanonicalArtistNameCustodyError("name coverage does not replay from inputs")
    if _canonical_name_stream_sha256(names) != receipt.names_uncompressed_sha256:
        raise DirectCanonicalArtistNameCustodyError("name facts do not replay from inputs")
