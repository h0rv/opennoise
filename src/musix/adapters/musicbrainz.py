"""Stream MusicBrainz artist JSON dumps into bounded typed records."""

import asyncio
import re
import tarfile
import time
import unicodedata
from collections.abc import Callable, Iterator
from pathlib import Path, PurePosixPath
from typing import BinaryIO, Literal, Protocol
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field

JSON_DUMP_SCHEMA = "1"
MUSICBRAINZ_API_BASE = "https://musicbrainz.org/ws/2"
MUSICBRAINZ_MIN_REQUEST_INTERVAL_SECONDS = 1.0


class MusicBrainzAdapterError(ValueError):
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


class AdapterLimits(BaseModel):
    """Bound compressed input, expanded members, records, and lines."""

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    max_archive_bytes: int = Field(default=4 * 1024 * 1024 * 1024, gt=0)
    max_member_bytes: int = Field(default=32 * 1024 * 1024 * 1024, gt=0)
    max_record_bytes: int = Field(default=2 * 1024 * 1024, gt=0)
    max_records: int = Field(default=10_000_000, gt=0)
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
    if member.size > limits.max_member_bytes:
        raise MusicBrainzAdapterError("MusicBrainz archive member exceeds max_member_bytes")
    stream = archive.extractfile(member)
    if stream is None:
        raise MusicBrainzAdapterError(f"cannot read archive member: {member.name}")
    return member_path, stream


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


def iter_artist_jsonl(stream: BinaryLineReader, limits: AdapterLimits) -> Iterator[AdaptedArtist]:
    """Parse bounded MusicBrainz artist JSON Lines from an open binary stream."""
    for line in _iter_bounded_lines(stream, limits):
        try:
            artist = MusicBrainzArtist.model_validate_json(line)
        except ValueError as error:
            raise MusicBrainzAdapterError("invalid MusicBrainz artist JSON record") from error
        yield adapt_artist(artist)


def iter_artist_archive(path: Path, limits: AdapterLimits) -> Iterator[AdaptedArtist]:
    """Stream `mbdump/artist` from an official `artist.tar.xz` archive."""
    archive_size = path.stat().st_size
    if archive_size > limits.max_archive_bytes:
        raise MusicBrainzAdapterError("MusicBrainz archive exceeds max_archive_bytes")

    found_artist = False
    schema_number: str | None = None
    with tarfile.open(path, mode="r|xz") as archive:
        for member in archive:
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
    """Fetch bounded artist records with the required identity and request rate."""

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
