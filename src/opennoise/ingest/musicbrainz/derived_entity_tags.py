"""Stream local MusicBrainz derived tag aggregates without genre name inference.

The derived archive supplies aggregate tag counts.  It does not by itself
identify which tags are official MusicBrainz genres, so callers get tag facts
unless they supply an exact tag-ID mapping from an official genre source.
"""

from __future__ import annotations

import hashlib
import tarfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Literal, Protocol

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping

    from opennoise.models.sources import DownloadSource

_ENTITY_KINDS = ("recording", "release", "release_group")
type EntityKind = Literal["recording", "release", "release_group"]


class DerivedEntityTagError(ValueError):
    """Report a missing, altered, malformed, or unsafe derived dump."""


@dataclass(frozen=True, slots=True)
class DerivedEntityTagLimits:
    """Keep streamed archive members and the tag lookup within local bounds."""

    max_member_bytes: int = 8 * 1024**3
    max_line_bytes: int = 2 * 1024**2
    max_tags: int = 2_000_000
    max_rows_per_member: int = 100_000_000


DEFAULT_LIMITS = DerivedEntityTagLimits()


class _LineReader(Protocol):
    def readline(self, size: int = -1, /) -> bytes: ...


@dataclass(frozen=True, slots=True)
class OfficialGenreIdentity:
    """An exact official genre identity, keyed by the numeric derived tag ID."""

    genre_id: int
    name: str


@dataclass(frozen=True, slots=True)
class DerivedEntityTagFact:
    """A positive aggregate tag count on one MusicBrainz-native entity ID."""

    entity_kind: EntityKind
    entity_id: int
    tag_id: int
    tag_name: str
    count: int


@dataclass(frozen=True, slots=True)
class DerivedEntityGenreFact:
    """A tag fact resolved through an exact supplied official genre mapping."""

    entity_kind: EntityKind
    entity_id: int
    tag_id: int
    genre_id: int
    genre_name: str
    count: int


def verify_declared_archive(path: Path, source: DownloadSource) -> None:
    """Check exact bytes and SHA-256 before any archive member is parsed."""
    if not path.is_file():
        raise DerivedEntityTagError(f"derived archive is not a file: {path}")
    byte_size = path.stat().st_size
    if byte_size != source.expected_bytes:
        raise DerivedEntityTagError(
            f"derived archive byte count {byte_size} does not match {source.expected_bytes}"
        )
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    if digest.hexdigest() != source.verified_sha256():
        raise DerivedEntityTagError("derived archive SHA-256 does not match declared source")


def _read_member_lines(
    reader: _LineReader, target: PurePosixPath, limits: DerivedEntityTagLimits
) -> Iterator[bytes]:
    for row_number in range(1, limits.max_rows_per_member + 2):
        line = reader.readline(limits.max_line_bytes + 1)
        if not line:
            return
        if len(line) > limits.max_line_bytes and not line.endswith(b"\n"):
            raise DerivedEntityTagError(f"derived row exceeds limit in {target}")
        if row_number > limits.max_rows_per_member:
            raise DerivedEntityTagError(f"derived member exceeds row limit: {target}")
        row = line.rstrip(b"\r\n")
        if row:
            yield row


def _member_lines(path: Path, member_name: str, limits: DerivedEntityTagLimits) -> Iterator[bytes]:
    target = PurePosixPath("mbdump") / member_name
    found = False
    with tarfile.open(path, mode="r|bz2") as archive:
        for member in archive:
            member_path = PurePosixPath(member.name)
            if member_path.is_absolute() or ".." in member_path.parts:
                raise DerivedEntityTagError(f"unsafe archive member path: {member.name}")
            if member_path != target:
                continue
            if found:
                raise DerivedEntityTagError(f"derived archive repeats {target}")
            found = True
            if not member.isfile() or member.size > limits.max_member_bytes:
                raise DerivedEntityTagError(f"unsafe or oversized derived member: {target}")
            stream = archive.extractfile(member)
            if stream is None:
                raise DerivedEntityTagError(f"cannot read derived member: {target}")
            try:
                yield from _read_member_lines(stream, target, limits)
            finally:
                stream.close()
    if not found:
        raise DerivedEntityTagError(f"derived archive has no {target} member")


def _columns(row: bytes, expected: int, member: str) -> tuple[str, ...]:
    try:
        columns = tuple(_copy_text(value, member) for value in row.split(b"\t"))
    except UnicodeDecodeError as error:
        raise DerivedEntityTagError(f"invalid UTF-8 in {member}") from error
    if len(columns) != expected:
        raise DerivedEntityTagError(f"unexpected column count in {member}")
    return columns


def _copy_text(value: bytes, member: str) -> str:
    """Decode the PostgreSQL COPY text escapes used by the derived dump."""
    if value == b"\\N":
        return ""
    decoded = bytearray()
    index = 0
    escapes = {
        ord("b"): b"\b",
        ord("f"): b"\f",
        ord("n"): b"\n",
        ord("r"): b"\r",
        ord("t"): b"\t",
        ord("v"): b"\v",
        ord("\\"): b"\\",
    }
    while index < len(value):
        current = value[index]
        if current != ord("\\"):
            decoded.append(current)
            index += 1
            continue
        if index + 1 >= len(value):
            raise DerivedEntityTagError(f"incomplete COPY escape in {member}")
        escaped = value[index + 1]
        replacement = escapes.get(escaped)
        if replacement is not None:
            decoded.extend(replacement)
            index += 2
            continue
        if ord("0") <= escaped <= ord("7") and index + 3 < len(value):
            octal = value[index + 1 : index + 4]
            if all(ord("0") <= digit <= ord("7") for digit in octal):
                decoded.append(int(octal, 8))
                index += 4
                continue
        raise DerivedEntityTagError(f"unsupported COPY escape in {member}")
    try:
        return decoded.decode("utf-8")
    except UnicodeDecodeError as error:
        raise DerivedEntityTagError(f"invalid UTF-8 in {member}") from error


def _positive_int(value: str, member: str) -> int:
    try:
        parsed = int(value)
    except ValueError as error:
        raise DerivedEntityTagError(f"invalid integer in {member}") from error
    if parsed <= 0:
        raise DerivedEntityTagError(f"non-positive identifier or count in {member}")
    return parsed


def _tag_lookup(path: Path, limits: DerivedEntityTagLimits) -> dict[int, str]:
    tags: dict[int, str] = {}
    for row in _member_lines(path, "tag", limits):
        tag_id, name, _reference_count = _columns(row, 3, "tag")
        parsed_id = _positive_int(tag_id, "tag")
        if not name or parsed_id in tags:
            raise DerivedEntityTagError("empty or repeated tag definition")
        tags[parsed_id] = name
        if len(tags) > limits.max_tags:
            raise DerivedEntityTagError("derived tag lookup exceeds max_tags")
    return tags


def iter_derived_entity_tag_facts(
    path: Path,
    source: DownloadSource,
    limits: DerivedEntityTagLimits = DEFAULT_LIMITS,
) -> Iterator[DerivedEntityTagFact]:
    """Verify first, then stream positive recording, release, and group tag rows."""
    verify_declared_archive(path, source)
    tags = _tag_lookup(path, limits)
    for entity_kind in _ENTITY_KINDS:
        member = f"{entity_kind}_tag"
        for row in _member_lines(path, member, limits):
            entity_id, tag_id, count, _last_updated = _columns(row, 4, member)
            parsed_count = _positive_int(count, member)
            parsed_tag_id = _positive_int(tag_id, member)
            tag_name = tags.get(parsed_tag_id)
            if tag_name is None:
                raise DerivedEntityTagError(f"{member} references an unknown tag ID")
            yield DerivedEntityTagFact(
                entity_kind=entity_kind,
                entity_id=_positive_int(entity_id, member),
                tag_id=parsed_tag_id,
                tag_name=tag_name,
                count=parsed_count,
            )


def iter_derived_entity_genre_facts(
    path: Path,
    source: DownloadSource,
    official_genres_by_tag_id: Mapping[int, OfficialGenreIdentity],
    limits: DerivedEntityTagLimits = DEFAULT_LIMITS,
) -> Iterator[DerivedEntityGenreFact]:
    """Resolve genres only from exact supplied tag-ID mappings, never tag names."""
    for tag_fact in iter_derived_entity_tag_facts(path, source, limits):
        genre = official_genres_by_tag_id.get(tag_fact.tag_id)
        if genre is not None:
            yield DerivedEntityGenreFact(
                entity_kind=tag_fact.entity_kind,
                entity_id=tag_fact.entity_id,
                tag_id=tag_fact.tag_id,
                genre_id=genre.genre_id,
                genre_name=genre.name,
                count=tag_fact.count,
            )
