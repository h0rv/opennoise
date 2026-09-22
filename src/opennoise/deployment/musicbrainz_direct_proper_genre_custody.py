"""Portable, custody-only replay of exact MusicBrainz proper-genre rows.

This module deliberately preserves source observations for review.  It does
not produce memberships, alter static data, or authorize publication.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final, Literal

import ijson
import zstandard
from pydantic import Field, model_validator

from opennoise.models import FrozenModel

if TYPE_CHECKING:
    from collections.abc import Iterator

_REVISION: Final = "musicbrainz-direct-proper-genre-custody-v1"
_POLICY: Final = "custody_only_no_membership_or_publication_claims"
_OBJECT_PREFIX: Final = "musicbrainz-direct-proper-genre-custody/sha256"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_MBID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_ARTIST_PREFIX: Final = "musicbrainz:artist:"
_MAX_CLAIM_COUNT: Final = 1_000_000
_MAX_OBJECT_BYTES: Final = 50 * 1024 * 1024
_MAX_LINE_BYTES: Final = 4096
_MAX_UNCOMPRESSED_BYTES: Final = 256 * 1024 * 1024


class DirectProperGenreCustodyError(RuntimeError):
    """Report a broken custody boundary or unsupported compressor."""


class DirectProperGenreClaim(FrozenModel):
    """One literal, exact artist-record genre observation from the retained input."""

    seed_id: str = Field(min_length=1)
    artist_mbid: str = Field(pattern=_MBID.pattern)
    musicbrainz_genre_id: str = Field(pattern=_MBID.pattern)
    source_record_id: str = Field(min_length=1)
    source_record_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_evidence_ref: str = Field(min_length=1)

    @model_validator(mode="after")
    def exact_artist_record(self) -> DirectProperGenreClaim:
        """Bind the claim to its exact MusicBrainz artist record."""
        if self.source_record_id != f"{_ARTIST_PREFIX}{self.artist_mbid}":
            raise ValueError("claim source record is not its exact artist record")
        return self


class DirectProperGenreCustodyReceipt(FrozenModel):
    """Pinned receipt for a compressed source-observation stream, never a release input."""

    revision: Literal["musicbrainz-direct-proper-genre-custody-v1"] = _REVISION
    custody_policy: Literal["custody_only_no_membership_or_publication_claims"] = _POLICY
    public_export_authorized: Literal[False] = False
    historical_assignments_read: Literal[False] = False
    release_or_peer_rows_used: Literal[0] = 0
    tag_rows_used: Literal[0] = 0
    source_seed_target_byte_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_seed_target_output_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    reconciliation_byte_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    reconciliation_output_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    claims_object_key: str = Field(pattern=rf"^{_OBJECT_PREFIX}/[0-9a-f]{{64}}\.jsonl\.zst$")
    claims_object_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    claims_object_byte_size: int = Field(gt=0, le=_MAX_OBJECT_BYTES)
    claims_uncompressed_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    claim_count: int = Field(ge=0, le=_MAX_CLAIM_COUNT)
    seed_count: int = Field(ge=0)
    artist_mbid_count: int = Field(ge=0)
    source_record_sha256_count: int = Field(ge=0)
    output_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def source_object_is_content_addressed(self) -> DirectProperGenreCustodyReceipt:
        """Bind the object key to the exact compressed object bytes."""
        if self.claims_object_key != f"{_OBJECT_PREFIX}/{self.claims_object_sha256}.jsonl.zst":
            raise ValueError("custody receipt does not content-address its claims object")
        return self


@dataclass(frozen=True, slots=True)
class _BuildCounts:
    claim_count: int
    seed_count: int
    artist_mbid_count: int
    source_record_count: int
    uncompressed_sha256: str


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def _output_sha256(path: Path, *, label: str) -> str:
    with path.open("rb") as stream:
        for prefix, event, value in ijson.parse(stream):
            if prefix == "output_sha256" and event == "string":
                if isinstance(value, str) and _SHA256.fullmatch(value):
                    return value
                break
    raise DirectProperGenreCustodyError(f"{label} lacks a lowercase output_sha256")


def _reconciled_genres(path: Path) -> dict[str, frozenset[str]]:
    raw = json.loads(path.read_bytes())
    if not isinstance(raw, dict) or not isinstance(rows := raw.get("dispositions"), list):
        raise DirectProperGenreCustodyError("reconciliation must contain dispositions")
    result: dict[str, frozenset[str]] = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(seed_id := row.get("source_item_id"), str):
            raise DirectProperGenreCustodyError("reconciliation disposition lacks source_item_id")
        identities = row.get("musicbrainz_identities")
        if not isinstance(identities, list) or seed_id in result:
            raise DirectProperGenreCustodyError(
                "reconciliation identities are invalid or duplicated"
            )
        result[seed_id] = frozenset(
            identity["identifier"]
            for identity in identities
            if isinstance(identity, dict)
            and identity.get("namespace") == "musicbrainz_genre_id"
            and isinstance(identity.get("identifier"), str)
        )
    return result


def _claim_from_source(
    row: object, genres: dict[str, frozenset[str]]
) -> DirectProperGenreClaim | None:
    if not isinstance(row, dict):
        return None
    match (
        row.get("seed_source_item_id"),
        row.get("seed_name"),
        row.get("artist_id"),
        row.get("facet"),
        row.get("match_kind"),
        row.get("target_identity"),
        row.get("target_name"),
        row.get("target_namespace"),
        row.get("source_record_id"),
        row.get("source_record_sha256"),
        row.get("evidence_ref"),
    ):
        case (
            str() as seed_id,
            str() as seed_name,
            str() as artist_mbid,
            "genre",
            "exact",
            str() as genre_id,
            str() as target_name,
            "musicbrainz_genre_id",
            str() as record_id,
            str() as record_sha,
            str() as evidence_ref,
        ):
            if (
                target_name != seed_name
                or _MBID.fullmatch(artist_mbid) is None
                or str(uuid.UUID(artist_mbid)) != artist_mbid
                or _SHA256.fullmatch(record_sha) is None
                or _MBID.fullmatch(genre_id) is None
                or str(uuid.UUID(genre_id)) != genre_id
                or not evidence_ref
                or genre_id not in genres.get(seed_id, frozenset())
            ):
                return None
            return DirectProperGenreClaim(
                seed_id=seed_id,
                artist_mbid=artist_mbid,
                musicbrainz_genre_id=genre_id,
                source_record_id=record_id,
                source_record_sha256=record_sha,
                source_evidence_ref=evidence_ref,
            )
        case _:
            return None


def _iter_claims(
    seed_target: Path, genres: dict[str, frozenset[str]]
) -> Iterator[DirectProperGenreClaim]:
    seen: set[bytes] = set()
    with seed_target.open("rb") as stream:
        for row in ijson.items(stream, "evidence.item"):
            claim = _claim_from_source(row, genres)
            if claim is None:
                continue
            encoded = _canonical_json(claim.model_dump(mode="json"))
            key = hashlib.sha256(encoded).digest()
            if key not in seen:
                seen.add(key)
                yield claim


def _write_claim_stream(
    seed_target: Path, genres: dict[str, frozenset[str]], output: Path
) -> _BuildCounts:
    digest = hashlib.sha256()
    seeds: set[str] = set()
    artists: set[str] = set()
    records: set[str] = set()
    count = 0
    with output.open("wb") as compressed:
        compressor = zstandard.ZstdCompressor(level=6, threads=0, write_checksum=True)
        with compressor.stream_writer(compressed, closefd=False) as writer:
            for claim in _iter_claims(seed_target, genres):
                if count >= _MAX_CLAIM_COUNT:
                    raise DirectProperGenreCustodyError(
                        "custody projection exceeds claim-count bound"
                    )
                line = _canonical_json(claim.model_dump(mode="json")) + b"\n"
                writer.write(line)
                digest.update(line)
                count += 1
                seeds.add(claim.seed_id)
                artists.add(claim.artist_mbid)
                records.add(claim.source_record_sha256)
    return _BuildCounts(count, len(seeds), len(artists), len(records), digest.hexdigest())


def receipt_sha256(receipt: DirectProperGenreCustodyReceipt) -> str:
    """Hash a receipt without trusting its embedded self-hash."""
    payload = receipt.model_dump(mode="json", exclude={"output_sha256"})
    return hashlib.sha256(_canonical_json(payload)).hexdigest()


def build_portable_direct_proper_genre_custody(  # noqa: C901, PLR0912, PLR0913, PLR0915 - explicit custody boundary.
    *,
    seed_target: Path,
    seed_target_byte_sha256: str,
    seed_target_output_sha256: str,
    reconciliation: Path,
    object_store: Path,
    receipt_output: Path,
) -> DirectProperGenreCustodyReceipt:
    """Stream the ignored source into one compact, content-addressed custody object."""
    if any(
        _SHA256.fullmatch(value) is None
        for value in (seed_target_byte_sha256, seed_target_output_sha256)
    ):
        raise DirectProperGenreCustodyError("seed target SHA-256 values must be lowercase hex")
    preflight_byte_sha256 = _sha256_file(seed_target)
    preflight_output_sha256 = _output_sha256(seed_target, label="seed target")
    if (preflight_byte_sha256, preflight_output_sha256) != (
        seed_target_byte_sha256,
        seed_target_output_sha256,
    ):
        raise DirectProperGenreCustodyError("seed target differs from declared SHA-256 inputs")
    genres = _reconciled_genres(reconciliation)
    object_store.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="musicbrainz-direct-custody-", dir=object_store
    ) as directory:
        staged = Path(directory) / "claims.jsonl.zst"
        counts = _write_claim_stream(seed_target, genres, staged)
        object_sha = _sha256_file(staged)
        object_byte_size = staged.stat().st_size
        if object_byte_size > _MAX_OBJECT_BYTES:
            raise DirectProperGenreCustodyError("custody projection exceeds compressed-byte bound")
        if _sha256_file(seed_target) != preflight_byte_sha256:
            raise DirectProperGenreCustodyError("seed target changed during custody projection")
        key = f"{_OBJECT_PREFIX}/{object_sha}.jsonl.zst"
        destination = object_store / key
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            if destination.is_symlink():
                raise DirectProperGenreCustodyError(
                    "content-addressed object path must not be a symlink"
                )
            if _sha256_file(destination) != object_sha:
                raise DirectProperGenreCustodyError(
                    "existing content-addressed object has wrong bytes"
                )
        else:
            try:
                os.link(staged, destination)
            except FileExistsError:
                if destination.is_symlink():
                    raise DirectProperGenreCustodyError(
                        "racing content-addressed object path must not be a symlink"
                    ) from None
                if _sha256_file(destination) != object_sha:
                    raise DirectProperGenreCustodyError(
                        "racing content-addressed object has wrong bytes"
                    ) from None
    base = DirectProperGenreCustodyReceipt(
        source_seed_target_byte_sha256=preflight_byte_sha256,
        source_seed_target_output_sha256=preflight_output_sha256,
        reconciliation_byte_sha256=_sha256_file(reconciliation),
        reconciliation_output_sha256=_output_sha256(reconciliation, label="reconciliation"),
        claims_object_key=key,
        claims_object_sha256=object_sha,
        claims_object_byte_size=object_byte_size,
        claims_uncompressed_sha256=counts.uncompressed_sha256,
        claim_count=counts.claim_count,
        seed_count=counts.seed_count,
        artist_mbid_count=counts.artist_mbid_count,
        source_record_sha256_count=counts.source_record_count,
        output_sha256="0" * 64,
    )
    receipt = base.model_copy(update={"output_sha256": receipt_sha256(base)})
    receipt_output.parent.mkdir(parents=True, exist_ok=True)
    payload = _canonical_json(receipt.model_dump(mode="json")) + b"\n"
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{receipt_output.name}.", dir=receipt_output.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, receipt_output)
        except FileExistsError as error:
            raise FileExistsError(
                f"refusing to replace existing custody receipt: {receipt_output}"
            ) from error
    finally:
        temporary.unlink(missing_ok=True)
    return receipt


def _stream_object_claims(path: Path) -> Iterator[DirectProperGenreClaim]:
    with path.open("rb") as compressed:
        decompressor = zstandard.ZstdDecompressor()
        with decompressor.stream_reader(compressed, closefd=False) as reader:
            buffered = io.BufferedReader(reader)
            decompressed_bytes = 0
            while raw_line := buffered.readline(_MAX_LINE_BYTES + 1):
                if len(raw_line) > _MAX_LINE_BYTES or not raw_line.endswith(b"\n"):
                    raise DirectProperGenreCustodyError(
                        "custody claims object has an oversized line"
                    )
                decompressed_bytes += len(raw_line)
                if decompressed_bytes > _MAX_UNCOMPRESSED_BYTES:
                    raise DirectProperGenreCustodyError(
                        "custody claims object exceeds decompressed-byte bound"
                    )
                yield DirectProperGenreClaim.model_validate_json(raw_line)


def verify_portable_direct_proper_genre_custody(
    receipt: DirectProperGenreCustodyReceipt, *, object_store: Path
) -> None:
    """Verify compressed bytes, typed claims, ordering, uniqueness, and aggregate receipt counts."""
    DirectProperGenreCustodyReceipt.model_validate_json(receipt.model_dump_json())
    if receipt.output_sha256 != receipt_sha256(receipt):
        raise DirectProperGenreCustodyError("custody receipt self-hash does not replay")
    path = object_store / receipt.claims_object_key
    if (
        not path.is_file()
        or path.is_symlink()
        or path.stat().st_size != receipt.claims_object_byte_size
        or _sha256_file(path) != receipt.claims_object_sha256
    ):
        raise DirectProperGenreCustodyError("custody claims object is missing or byte-mutated")
    digest = hashlib.sha256()
    keys: set[bytes] = set()
    seeds: set[str] = set()
    artists: set[str] = set()
    records: set[str] = set()
    for claim in _stream_object_claims(path):
        if len(keys) >= receipt.claim_count:
            raise DirectProperGenreCustodyError(
                "custody claims object exceeds declared claim count"
            )
        line = _canonical_json(claim.model_dump(mode="json")) + b"\n"
        key = hashlib.sha256(line[:-1]).digest()
        if key in keys:
            raise DirectProperGenreCustodyError("custody claims object has duplicate observation")
        keys.add(key)
        digest.update(line)
        seeds.add(claim.seed_id)
        artists.add(claim.artist_mbid)
        records.add(claim.source_record_sha256)
    if (digest.hexdigest(), len(keys), len(seeds), len(artists), len(records)) != (
        receipt.claims_uncompressed_sha256,
        receipt.claim_count,
        receipt.seed_count,
        receipt.artist_mbid_count,
        receipt.source_record_sha256_count,
    ):
        raise DirectProperGenreCustodyError("custody claims object does not replay receipt counts")


def iter_verified_portable_direct_proper_genre_claims(
    receipt: DirectProperGenreCustodyReceipt, *, object_store: Path
) -> Iterator[DirectProperGenreClaim]:
    """Yield typed source observations only after the complete portable object verifies."""
    verify_portable_direct_proper_genre_custody(receipt, object_store=object_store)
    yield from _stream_object_claims(object_store / receipt.claims_object_key)


def verify_portable_direct_proper_genre_custody_from_inputs(
    receipt: DirectProperGenreCustodyReceipt,
    *,
    object_store: Path,
    seed_target: Path,
    reconciliation: Path,
) -> None:
    """Independently replay the retained inputs and prove the portable stream is exact."""
    verify_portable_direct_proper_genre_custody(receipt, object_store=object_store)
    if (_sha256_file(seed_target), _output_sha256(seed_target, label="seed target")) != (
        receipt.source_seed_target_byte_sha256,
        receipt.source_seed_target_output_sha256,
    ) or (
        _sha256_file(reconciliation),
        _output_sha256(reconciliation, label="reconciliation"),
    ) != (
        receipt.reconciliation_byte_sha256,
        receipt.reconciliation_output_sha256,
    ):
        raise DirectProperGenreCustodyError("replay inputs differ from the pinned custody inputs")
    digest = hashlib.sha256()
    count = 0
    for claim in _iter_claims(seed_target, _reconciled_genres(reconciliation)):
        digest.update(_canonical_json(claim.model_dump(mode="json")) + b"\n")
        count += 1
    if (digest.hexdigest(), count) != (receipt.claims_uncompressed_sha256, receipt.claim_count):
        raise DirectProperGenreCustodyError(
            "retained input replay differs from portable custody stream"
        )
