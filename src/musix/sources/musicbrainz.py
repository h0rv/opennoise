"""Stream MusicBrainz JSON sources into bounded common projections."""

import asyncio
import hashlib
import re
import tarfile
import time
import unicodedata
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import BinaryIO, Literal, Protocol
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field

from musix.models.catalog import ArtistProjection, IdentifierClaim, NameClaim
from musix.models.pipeline import (
    ParsedSourceRecord,
    RejectedSourceRecord,
    SourceLimits,
    SourceRecord,
)
from musix.models.sources import DownloadSource
from musix.policy import require_metadata_file, require_metadata_path
from musix.sources.registry import SourceAdapterError

JSON_DUMP_SCHEMA = "1"
MUSICBRAINZ_API_BASE = "https://musicbrainz.org/ws/2"
MUSICBRAINZ_MIN_REQUEST_INTERVAL_SECONDS = 1.0
YEAR_TEXT_LENGTH = 4
MAX_YEAR = 9999


class MusicBrainzAdapterError(SourceAdapterError):
    """Report an invalid archive, record, or adapter boundary."""


class BinaryLineReader(Protocol):
    """Describe the binary operation needed by the JSONL parser."""

    def readline(self, size: int = -1, /) -> bytes:
        """Read at most one binary line."""
        ...


class BinaryMemberReader(BinaryLineReader, Protocol):
    """Describe a readable archive member that the adapter closes."""

    def read(self, size: int = -1, /) -> bytes:
        """Read binary data from the member."""
        ...

    def close(self) -> None:
        """Close the member."""
        ...


class AdapterLimits(SourceLimits):
    """Bound compressed input, expanded members, records, and lines."""

    max_unique_genres: int = Field(default=100_000, gt=0)


class MusicBrainzAlias(BaseModel):
    """Parse one alias from the MusicBrainz web service JSON shape."""

    model_config = ConfigDict(frozen=True, strict=True, extra="ignore")

    name: str = Field(min_length=1)
    locale: str | None = None


class MusicBrainzGenre(BaseModel):
    """Parse one MusicBrainz genre attached to an artist."""

    model_config = ConfigDict(frozen=True, strict=True, extra="ignore")

    id: UUID
    name: str = Field(min_length=1)
    count: int | None = None
    disambiguation: str = ""


class MusicBrainzLifeSpan(BaseModel):
    """Parse the bounded artist lifespan fields used by the catalog."""

    model_config = ConfigDict(frozen=True, strict=True, extra="ignore")

    begin: str | None = None
    end: str | None = None


class MusicBrainzArtist(BaseModel):
    """Parse the supported fields from one official artist JSON document."""

    model_config = ConfigDict(frozen=True, strict=True, extra="ignore")

    id: UUID
    name: str = Field(min_length=1)
    sort_name: str = Field(alias="sort-name", min_length=1)
    disambiguation: str = ""
    aliases: tuple[MusicBrainzAlias, ...] = ()
    genres: tuple[MusicBrainzGenre, ...] = ()
    isnis: tuple[str, ...] = ()
    ipis: tuple[str, ...] = ()
    type: str | None = None
    life_span: MusicBrainzLifeSpan | None = Field(default=None, alias="life-span")


class MusicBrainzReleaseGroupReference(BaseModel):
    """Parse the release group identity nested in a release response."""

    model_config = ConfigDict(frozen=True, strict=True, extra="ignore")

    id: UUID
    title: str = Field(min_length=1)


class MusicBrainzReleaseGroup(BaseModel):
    """Parse album identity and direct genres from a release group document."""

    model_config = ConfigDict(frozen=True, strict=True, extra="ignore")

    id: UUID
    title: str = Field(min_length=1)
    primary_type: str | None = Field(default=None, alias="primary-type")
    secondary_types: tuple[str, ...] = Field(default=(), alias="secondary-types")
    first_release_date: str | None = Field(default=None, alias="first-release-date")
    genres: tuple[MusicBrainzGenre, ...] = ()


class MusicBrainzRelease(BaseModel):
    """Parse one concrete edition and any genre claims attached to it."""

    model_config = ConfigDict(frozen=True, strict=True, extra="ignore")

    id: UUID
    title: str = Field(min_length=1)
    release_group: MusicBrainzReleaseGroupReference = Field(alias="release-group")
    status: str | None = None
    packaging: str | None = None
    country: str | None = None
    date: str | None = None
    genres: tuple[MusicBrainzGenre, ...] = ()


class Identifier(BaseModel):
    """Represent one typed identifier in the local JSONL boundary."""

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    type: Literal["source_id", "isni", "ipi"]
    namespace: Literal["musicbrainz", "isni", "ipi"]
    value: str = Field(min_length=1)


class ArtistRecord(BaseModel):
    """Represent one normalized artist for the catalog importer."""

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    type: Literal["artist"] = "artist"
    external_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    aliases: tuple[str, ...] = ()
    identifiers: tuple[Identifier, ...] = ()


class GenreRecord(BaseModel):
    """Represent one normalized genre for the catalog importer."""

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    type: Literal["genre"] = "genre"
    external_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    slug: str = Field(min_length=1)
    aliases: tuple[str, ...] = ()
    identifiers: tuple[Identifier, ...] = ()


class ArtistGenreRelationship(BaseModel):
    """Represent one weighted MusicBrainz artist to genre claim."""

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    type: Literal["artist_has_genre"] = "artist_has_genre"
    artist_external_id: str = Field(min_length=1)
    genre_external_id: str = Field(min_length=1)
    weight: int | None = None


class AdaptedArtist(BaseModel):
    """Keep one artist and its bounded genre claims together while streaming."""

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    artist: ArtistRecord
    genres: tuple[GenreRecord, ...]
    relationships: tuple[ArtistGenreRelationship, ...]


class ReleaseGroupRecord(BaseModel):
    """Represent one MusicBrainz album identity at the local adapter boundary."""

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    type: Literal["release_group"] = "release_group"
    external_id: str = Field(min_length=1)
    source_id: UUID
    title: str = Field(min_length=1)
    primary_type: str | None = None
    secondary_types: tuple[str, ...] = ()
    first_release_date: str | None = None


class ReleaseRecord(BaseModel):
    """Represent one concrete MusicBrainz release or edition."""

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    type: Literal["release"] = "release"
    external_id: str = Field(min_length=1)
    source_id: UUID
    release_group_external_id: str = Field(min_length=1)
    release_group_source_id: UUID
    title: str = Field(min_length=1)
    status: str | None = None
    packaging: str | None = None
    country: str | None = None
    date: str | None = None


class AlbumGenreEvidenceRecord(BaseModel):
    """Represent one direct MusicBrainz genre claim on an album or edition."""

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    type: Literal["album_genre_evidence"] = "album_genre_evidence"
    source_family: Literal["musicbrainz"] = "musicbrainz"
    evidence_level: Literal["release_group", "release"]
    release_group_source_id: UUID
    release_source_id: UUID | None = None
    genre_source_id: UUID
    source_genre_name: str = Field(min_length=1)
    source_count: int | None = Field(default=None, ge=0)
    source_record_id: str = Field(min_length=1)


class AdaptedReleaseGroup(BaseModel):
    """Keep one album identity and its direct genre evidence together."""

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    release_group: ReleaseGroupRecord
    evidence: tuple[AlbumGenreEvidenceRecord, ...]


class AdaptedRelease(BaseModel):
    """Keep one edition and its direct genre evidence together."""

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    release: ReleaseRecord
    evidence: tuple[AlbumGenreEvidenceRecord, ...]


def _deduplicate(values: Iterator[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        normalized = value.strip()
        key = normalized.casefold()
        if normalized and key not in seen:
            seen.add(key)
            result.append(normalized)
    return tuple(result)


def _slug(value: str, fallback: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    slug = re.sub(r"[^\w]+", "-", normalized, flags=re.UNICODE).strip("-")
    return slug or fallback


def adapt_artist(artist: MusicBrainzArtist) -> AdaptedArtist:
    """Convert one parsed MusicBrainz artist into stable local records."""
    artist_id = str(artist.id)
    external_id = f"musicbrainz:artist:{artist_id}"
    aliases = _deduplicate(
        iter(
            alias.name
            for alias in artist.aliases
            if alias.name.strip().casefold() != artist.name.strip().casefold()
        )
    )
    identifiers = [
        Identifier(type="source_id", namespace="musicbrainz", value=artist_id),
    ]
    identifiers.extend(
        Identifier(type="isni", namespace="isni", value=value) for value in artist.isnis
    )
    identifiers.extend(
        Identifier(type="ipi", namespace="ipi", value=value) for value in artist.ipis
    )

    genres: list[GenreRecord] = []
    relationships: list[ArtistGenreRelationship] = []
    seen_genres: set[UUID] = set()
    for genre in artist.genres:
        if genre.id in seen_genres:
            continue
        seen_genres.add(genre.id)
        genre_id = str(genre.id)
        genre_external_id = f"musicbrainz:genre:{genre_id}"
        genres.append(
            GenreRecord(
                external_id=genre_external_id,
                name=genre.name,
                slug=_slug(genre.name, genre_id),
                identifiers=(
                    Identifier(type="source_id", namespace="musicbrainz", value=genre_id),
                ),
            )
        )
        relationships.append(
            ArtistGenreRelationship(
                artist_external_id=external_id,
                genre_external_id=genre_external_id,
                weight=genre.count,
            )
        )

    return AdaptedArtist(
        artist=ArtistRecord(
            external_id=external_id,
            name=artist.name,
            aliases=aliases,
            identifiers=tuple(identifiers),
        ),
        genres=tuple(genres),
        relationships=tuple(relationships),
    )


def adapt_release_group(release_group: MusicBrainzReleaseGroup) -> AdaptedReleaseGroup:
    """Convert one release group and retain only direct official genre claims."""
    source_id = release_group.id
    evidence = tuple(
        AlbumGenreEvidenceRecord(
            evidence_level="release_group",
            release_group_source_id=source_id,
            genre_source_id=genre.id,
            source_genre_name=genre.name,
            source_count=genre.count,
            source_record_id=f"musicbrainz:release-group:{source_id}:genre:{genre.id}",
        )
        for genre in release_group.genres
    )
    return AdaptedReleaseGroup(
        release_group=ReleaseGroupRecord(
            external_id=f"musicbrainz:release-group:{source_id}",
            source_id=source_id,
            title=release_group.title,
            primary_type=release_group.primary_type,
            secondary_types=release_group.secondary_types,
            first_release_date=release_group.first_release_date,
        ),
        evidence=evidence,
    )


def adapt_release(release: MusicBrainzRelease) -> AdaptedRelease:
    """Convert one edition and retain its release level genre claims."""
    source_id = release.id
    release_group_id = release.release_group.id
    evidence = tuple(
        AlbumGenreEvidenceRecord(
            evidence_level="release",
            release_group_source_id=release_group_id,
            release_source_id=source_id,
            genre_source_id=genre.id,
            source_genre_name=genre.name,
            source_count=genre.count,
            source_record_id=f"musicbrainz:release:{source_id}:genre:{genre.id}",
        )
        for genre in release.genres
    )
    return AdaptedRelease(
        release=ReleaseRecord(
            external_id=f"musicbrainz:release:{source_id}",
            source_id=source_id,
            release_group_external_id=f"musicbrainz:release-group:{release_group_id}",
            release_group_source_id=release_group_id,
            title=release.title,
            status=release.status,
            packaging=release.packaging,
            country=release.country,
            date=release.date,
        ),
        evidence=evidence,
    )


def _safe_member_name(name: str) -> PurePosixPath:
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts:
        raise MusicBrainzAdapterError(f"unsafe archive member path: {name}")
    return path


def _open_regular_member(
    archive: tarfile.TarFile,
    member: tarfile.TarInfo,
    limits: AdapterLimits,
) -> tuple[PurePosixPath, BinaryMemberReader] | None:
    if not member.isfile():
        return None
    member_path = _safe_member_name(member.name)
    require_metadata_path(member_path)
    if member.size > limits.max_member_bytes:
        raise MusicBrainzAdapterError("MusicBrainz archive member exceeds max_member_bytes")
    stream = archive.extractfile(member)
    if stream is None:
        raise MusicBrainzAdapterError(f"cannot read archive member: {member.name}")
    return member_path, stream


def _check_expansion(member: tarfile.TarInfo, archive_size: int, limits: AdapterLimits) -> None:
    if member.size > archive_size * limits.max_decompression_ratio:
        raise MusicBrainzAdapterError("MusicBrainz archive exceeds max_decompression_ratio")


def _iter_bounded_lines(stream: BinaryLineReader, limits: AdapterLimits) -> Iterator[bytes]:
    count = 0
    while line := stream.readline(limits.max_record_bytes + 1):
        if len(line) > limits.max_record_bytes and not line.endswith(b"\n"):
            while continuation := stream.readline(64 * 1024):
                if continuation.endswith(b"\n"):
                    break
            raise MusicBrainzAdapterError("MusicBrainz JSON record exceeds max_record_bytes")
        record = line.strip()
        if not record:
            continue
        count += 1
        if count > limits.max_records:
            raise MusicBrainzAdapterError("MusicBrainz dump exceeds max_records")
        yield record


@dataclass(frozen=True, slots=True)
class _RawRecord:
    payload: bytes | None
    byte_length: int
    sha256: str


def _iter_raw_records(stream: BinaryLineReader, limits: SourceLimits) -> Iterator[_RawRecord]:
    count = 0
    while first := stream.readline(limits.max_record_bytes + 2):
        digest = hashlib.sha256()
        captured = bytearray(first[: limits.max_record_bytes])
        first_has_newline = first.endswith(b"\n")
        first_record = first[:-1] if first_has_newline else first
        digest.update(first_record)
        byte_length = len(first_record)
        if not first_has_newline:
            while continuation := stream.readline(64 * 1024):
                has_newline = continuation.endswith(b"\n")
                record_chunk = continuation[:-1] if has_newline else continuation
                digest.update(record_chunk)
                byte_length += len(record_chunk)
                if has_newline:
                    break
        if not byte_length:
            continue
        count += 1
        if count > limits.max_records:
            raise MusicBrainzAdapterError("MusicBrainz dump exceeds max_records")
        yield _RawRecord(
            payload=bytes(captured) if byte_length <= limits.max_record_bytes else None,
            byte_length=byte_length,
            sha256=digest.hexdigest(),
        )


def _iter_raw_artist_archive(path: Path, limits: SourceLimits) -> Iterator[_RawRecord]:
    require_metadata_file(path)
    archive_size = path.stat().st_size
    if archive_size > limits.max_archive_bytes:
        raise MusicBrainzAdapterError("MusicBrainz archive exceeds max_archive_bytes")
    found_artist = False
    schema_number: str | None = None
    adapter_limits = AdapterLimits.model_validate(limits.model_dump())
    with tarfile.open(path, mode="r|xz") as archive:
        for member in archive:
            _check_expansion(member, archive_size, adapter_limits)
            opened = _open_regular_member(archive, member, adapter_limits)
            if opened is None:
                continue
            member_path, stream = opened
            try:
                if member_path == PurePosixPath("JSON_DUMPS_SCHEMA_NUMBER"):
                    schema_number = stream.read(32).decode("ascii").strip()
                elif member_path == PurePosixPath("mbdump/artist"):
                    if found_artist:
                        raise MusicBrainzAdapterError("MusicBrainz archive repeats mbdump/artist")
                    found_artist = True
                    yield from _iter_raw_records(stream, limits)
            finally:
                stream.close()
    if not found_artist:
        raise MusicBrainzAdapterError("MusicBrainz archive has no mbdump/artist member")
    if schema_number != JSON_DUMP_SCHEMA:
        raise MusicBrainzAdapterError(
            f"unsupported MusicBrainz JSON dump schema: {schema_number!r}"
        )


def iter_artist_jsonl(stream: BinaryLineReader, limits: AdapterLimits) -> Iterator[AdaptedArtist]:
    """Parse bounded MusicBrainz artist JSON Lines from an open binary stream."""
    for line in _iter_bounded_lines(stream, limits):
        try:
            artist = MusicBrainzArtist.model_validate_json(line)
        except ValueError as error:
            raise MusicBrainzAdapterError("invalid MusicBrainz artist JSON record") from error
        yield adapt_artist(artist)


def iter_release_group_jsonl(
    stream: BinaryLineReader,
    limits: AdapterLimits,
) -> Iterator[AdaptedReleaseGroup]:
    """Parse bounded MusicBrainz release group JSON Lines."""
    for line in _iter_bounded_lines(stream, limits):
        try:
            release_group = MusicBrainzReleaseGroup.model_validate_json(line)
        except ValueError as error:
            raise MusicBrainzAdapterError("invalid MusicBrainz release group record") from error
        yield adapt_release_group(release_group)


def iter_release_jsonl(
    stream: BinaryLineReader,
    limits: AdapterLimits,
) -> Iterator[AdaptedRelease]:
    """Parse bounded MusicBrainz release JSON Lines."""
    for line in _iter_bounded_lines(stream, limits):
        try:
            release = MusicBrainzRelease.model_validate_json(line)
        except ValueError as error:
            raise MusicBrainzAdapterError("invalid MusicBrainz release record") from error
        yield adapt_release(release)


def iter_artist_archive(path: Path, limits: AdapterLimits) -> Iterator[AdaptedArtist]:
    """Stream `mbdump/artist` from an official `artist.tar.xz` archive."""
    require_metadata_file(path)
    archive_size = path.stat().st_size
    if archive_size > limits.max_archive_bytes:
        raise MusicBrainzAdapterError("MusicBrainz archive exceeds max_archive_bytes")

    found_artist = False
    schema_number: str | None = None
    with tarfile.open(path, mode="r|xz") as archive:
        for member in archive:
            _check_expansion(member, archive_size, limits)
            opened = _open_regular_member(archive, member, limits)
            if opened is None:
                continue
            member_path, stream = opened
            try:
                if member_path == PurePosixPath("JSON_DUMPS_SCHEMA_NUMBER"):
                    schema_number = stream.read(32).decode("ascii").strip()
                elif member_path == PurePosixPath("mbdump/artist"):
                    if found_artist:
                        raise MusicBrainzAdapterError("MusicBrainz archive repeats mbdump/artist")
                    found_artist = True
                    yield from iter_artist_jsonl(stream, limits)
            finally:
                stream.close()

    if not found_artist:
        raise MusicBrainzAdapterError("MusicBrainz archive has no mbdump/artist member")
    if schema_number != JSON_DUMP_SCHEMA:
        raise MusicBrainzAdapterError(
            f"unsupported MusicBrainz JSON dump schema: {schema_number!r}"
        )


def _iter_json_archive[T](
    path: Path,
    limits: AdapterLimits,
    *,
    member_name: str,
    parser: Callable[[BinaryLineReader, AdapterLimits], Iterator[T]],
) -> Iterator[T]:
    """Stream one named member from an official MusicBrainz JSON archive."""
    require_metadata_file(path)
    if path.stat().st_size > limits.max_archive_bytes:
        raise MusicBrainzAdapterError("MusicBrainz archive exceeds max_archive_bytes")
    expected_member = PurePosixPath("mbdump") / member_name
    found_member = False
    schema_number: str | None = None
    with tarfile.open(path, mode="r|xz") as archive:
        for member in archive:
            _check_expansion(member, path.stat().st_size, limits)
            opened = _open_regular_member(archive, member, limits)
            if opened is None:
                continue
            member_path, stream = opened
            try:
                if member_path == PurePosixPath("JSON_DUMPS_SCHEMA_NUMBER"):
                    schema_number = stream.read(32).decode("ascii").strip()
                elif member_path == expected_member:
                    if found_member:
                        raise MusicBrainzAdapterError(
                            f"MusicBrainz archive repeats {expected_member}"
                        )
                    found_member = True
                    yield from parser(stream, limits)
            finally:
                stream.close()
    if not found_member:
        raise MusicBrainzAdapterError(f"MusicBrainz archive has no {expected_member} member")
    if schema_number != JSON_DUMP_SCHEMA:
        raise MusicBrainzAdapterError(
            f"unsupported MusicBrainz JSON dump schema: {schema_number!r}"
        )


def iter_json_archive_lines(
    path: Path,
    limits: AdapterLimits,
    *,
    member_name: str,
) -> Iterator[bytes]:
    """Stream bounded raw JSON lines from one verified official archive member."""
    yield from _iter_json_archive(
        path,
        limits,
        member_name=member_name,
        parser=_iter_bounded_lines,
    )


def iter_release_group_archive(
    path: Path,
    limits: AdapterLimits,
) -> Iterator[AdaptedReleaseGroup]:
    """Stream release groups from an official `release-group.tar.xz` archive."""
    yield from _iter_json_archive(
        path,
        limits,
        member_name="release-group",
        parser=iter_release_group_jsonl,
    )


def iter_release_archive(path: Path, limits: AdapterLimits) -> Iterator[AdaptedRelease]:
    """Stream concrete editions from an official `release.tar.xz` archive."""
    yield from _iter_json_archive(
        path,
        limits,
        member_name="release",
        parser=iter_release_jsonl,
    )


def _write_line(stream: BinaryIO, model: BaseModel) -> None:
    stream.write(model.model_dump_json().encode("utf-8"))
    stream.write(b"\n")


def write_artist_outputs(
    source: Path,
    entities_destination: Path,
    relationships_destination: Path,
    limits: AdapterLimits,
) -> tuple[int, int]:
    """Atomically write importer JSONL and a relationship JSONL sidecar."""
    entities_destination.parent.mkdir(parents=True, exist_ok=True)
    relationships_destination.parent.mkdir(parents=True, exist_ok=True)
    entities_temporary = entities_destination.with_name(f".{entities_destination.name}.tmp")
    relationships_temporary = relationships_destination.with_name(
        f".{relationships_destination.name}.tmp"
    )
    entity_count = 0
    relationship_count = 0
    seen_genres: set[str] = set()
    try:
        with (
            entities_temporary.open("xb") as entities_stream,
            relationships_temporary.open("xb") as relationships_stream,
        ):
            for adapted in iter_artist_archive(source, limits):
                _write_line(entities_stream, adapted.artist)
                entity_count += 1
                for genre in adapted.genres:
                    if genre.external_id in seen_genres:
                        continue
                    seen_genres.add(genre.external_id)
                    if len(seen_genres) > limits.max_unique_genres:
                        raise MusicBrainzAdapterError("MusicBrainz dump exceeds max_unique_genres")
                    _write_line(entities_stream, genre)
                    entity_count += 1
                for relationship in adapted.relationships:
                    _write_line(relationships_stream, relationship)
                    relationship_count += 1
        entities_temporary.replace(entities_destination)
        relationships_temporary.replace(relationships_destination)
    finally:
        entities_temporary.unlink(missing_ok=True)
        relationships_temporary.unlink(missing_ok=True)
    return entity_count, relationship_count


class MusicBrainzClient:
    """Fetch bounded typed records with the required identity and request rate."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        user_agent: str,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """Store the caller-owned HTTP client and a descriptive user agent."""
        if not user_agent.strip() or "/" not in user_agent or "(" not in user_agent:
            raise ValueError("MusicBrainz user_agent must include an app version and contact")
        self._client = client
        self._user_agent = user_agent
        self._clock = clock
        self._next_request_at = 0.0
        self._rate_lock = asyncio.Lock()

    async def _wait_for_rate_limit(self) -> None:
        async with self._rate_lock:
            now = self._clock()
            delay = self._next_request_at - now
            if delay > 0:
                await asyncio.sleep(delay)
                now = self._clock()
            self._next_request_at = now + MUSICBRAINZ_MIN_REQUEST_INTERVAL_SECONDS

    async def fetch_artist(self, artist_id: UUID) -> MusicBrainzArtist:
        """Fetch one official artist response with aliases and genres."""
        await self._wait_for_rate_limit()
        response = await self._client.get(
            f"{MUSICBRAINZ_API_BASE}/artist/{artist_id}",
            params={"fmt": "json", "inc": "aliases+genres"},
            headers={"User-Agent": self._user_agent, "Accept": "application/json"},
        )
        response.raise_for_status()
        return MusicBrainzArtist.model_validate_json(response.content)

    async def fetch_release_group(self, release_group_id: UUID) -> MusicBrainzReleaseGroup:
        """Fetch one release group with direct genres."""
        await self._wait_for_rate_limit()
        response = await self._client.get(
            f"{MUSICBRAINZ_API_BASE}/release-group/{release_group_id}",
            params={"fmt": "json", "inc": "genres"},
            headers={"User-Agent": self._user_agent, "Accept": "application/json"},
        )
        response.raise_for_status()
        return MusicBrainzReleaseGroup.model_validate_json(response.content)

    async def fetch_release(self, release_id: UUID) -> MusicBrainzRelease:
        """Fetch one concrete release with its release group and direct genres."""
        await self._wait_for_rate_limit()
        response = await self._client.get(
            f"{MUSICBRAINZ_API_BASE}/release/{release_id}",
            params={"fmt": "json", "inc": "release-groups+genres"},
            headers={"User-Agent": self._user_agent, "Accept": "application/json"},
        )
        response.raise_for_status()
        return MusicBrainzRelease.model_validate_json(response.content)


def _year(value: str | None) -> int | None:
    if value is None or len(value) < YEAR_TEXT_LENGTH or not value[:YEAR_TEXT_LENGTH].isdigit():
        return None
    parsed = int(value[:YEAR_TEXT_LENGTH])
    return parsed if 1 <= parsed <= MAX_YEAR else None


def _artist_projection(artist: MusicBrainzArtist) -> ArtistProjection:
    artist_id = str(artist.id)
    primary_key = artist.name.strip().casefold()
    names = [NameClaim(kind="primary", value=artist.name)]
    if artist.sort_name.strip().casefold() != primary_key:
        names.append(NameClaim(kind="sort", value=artist.sort_name))
    seen_names = {primary_key, artist.sort_name.strip().casefold()}
    for alias in artist.aliases:
        key = alias.name.strip().casefold()
        if key in seen_names:
            continue
        seen_names.add(key)
        names.append(NameClaim(kind="alias", value=alias.name, language_tag=alias.locale or "und"))
    identifiers = [IdentifierClaim(type_key="source_id", namespace="musicbrainz", value=artist_id)]
    identifiers.extend(
        IdentifierClaim(type_key="isni", namespace="isni", value=value) for value in artist.isnis
    )
    identifiers.extend(
        IdentifierClaim(type_key="ipi", namespace="ipi", value=value) for value in artist.ipis
    )
    return ArtistProjection(
        external_id=artist_id,
        names=tuple(names),
        identifiers=tuple(identifiers),
        artist_kind=artist.type,
        disambiguation=artist.disambiguation or None,
        begin_year=_year(artist.life_span.begin if artist.life_span is not None else None),
        end_year=_year(artist.life_span.end if artist.life_span is not None else None),
    )


class MusicBrainzArtistDumpAdapter:
    """Project the official artist JSON archive into common source claims."""

    @property
    def key(self) -> str:
        """Return the manifest adapter key."""
        return "musicbrainz_artist_json_dump_v1"

    @property
    def version(self) -> str:
        """Return the immutable projection version."""
        return "2"

    def supports(self, source: DownloadSource) -> bool:
        """Require the official archive format understood by this adapter."""
        return source.compression == "tar.xz" and source.expected_content_type == (
            "application/octet-stream"
        )

    def iter_records(
        self,
        path: Path,
        limits: SourceLimits,
        *,
        start_after: int,
    ) -> Iterator[SourceRecord]:
        """Stream all raw records while skipping already committed ordinals."""
        for ordinal, raw in enumerate(_iter_raw_artist_archive(path, limits)):
            if ordinal <= start_after:
                continue
            if raw.payload is None:
                yield RejectedSourceRecord(
                    ordinal=ordinal,
                    exact_sha256=raw.sha256,
                    byte_length=raw.byte_length,
                    reason="MusicBrainz artist record exceeds max_record_bytes",
                )
                continue
            try:
                artist = MusicBrainzArtist.model_validate_json(raw.payload)
                yield ParsedSourceRecord(
                    ordinal=ordinal,
                    exact_sha256=raw.sha256,
                    byte_length=raw.byte_length,
                    projection=_artist_projection(artist),
                )
            except ValueError as error:
                yield RejectedSourceRecord(
                    ordinal=ordinal,
                    exact_sha256=raw.sha256,
                    byte_length=raw.byte_length,
                    reason=f"invalid MusicBrainz artist JSON: {error}",
                )
