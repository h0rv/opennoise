"""Stream ListenBrainz dumps into bounded artist co-occurrence evidence."""

import itertools
import tarfile
from collections.abc import Iterator
from pathlib import Path, PurePosixPath
from typing import Literal, Protocol
from uuid import UUID

import zstandard
from pydantic import BaseModel, ConfigDict, Field


class ListenBrainzAdapterError(ValueError):
    """Report an invalid dump, listen, ordering, or bounded-state limit."""


class BinaryLineReader(Protocol):
    """Describe the binary operation needed by the JSONL parser."""

    def readline(self, size: int = -1, /) -> bytes:
        """Read at most one binary line."""
        ...


class BinaryMemberReader(BinaryLineReader, Protocol):
    """Describe a readable archive member that the adapter closes."""

    def close(self) -> None:
        """Close the member."""
        ...


class AdapterLimits(BaseModel):
    """Bound compressed input, expanded members, records, and aggregate state."""

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    max_archive_bytes: int = Field(default=4 * 1024 * 1024 * 1024, gt=0)
    max_decompressed_bytes: int = Field(default=64 * 1024 * 1024 * 1024, gt=0)
    max_member_bytes: int = Field(default=16 * 1024 * 1024 * 1024, gt=0)
    max_record_bytes: int = Field(default=2 * 1024 * 1024, gt=0)
    max_records: int = Field(default=100_000_000, gt=0)
    max_users_per_window: int = Field(default=2_000_000, gt=0)
    max_artists_per_user_window: int = Field(default=1_000, gt=1)
    max_pairs_per_window: int = Field(default=10_000_000, gt=0)


class ListenMbidMapping(BaseModel):
    """Parse ListenBrainz server-resolved MusicBrainz identifiers."""

    model_config = ConfigDict(frozen=True, strict=True, extra="ignore")

    artist_mbids: tuple[str, ...] = ()


class ListenAdditionalInfo(BaseModel):
    """Parse user-submitted fallback MusicBrainz identifiers."""

    model_config = ConfigDict(frozen=True, strict=True, extra="ignore")

    artist_mbids: tuple[str, ...] = ()


class ListenTrackMetadata(BaseModel):
    """Parse only identifier-bearing fields from ListenBrainz track metadata."""

    model_config = ConfigDict(frozen=True, strict=True, extra="ignore")

    mbid_mapping: ListenMbidMapping | None = None
    additional_info: ListenAdditionalInfo | None = None


class Listen(BaseModel):
    """Parse the minimum official listen JSON shape needed for aggregation."""

    model_config = ConfigDict(frozen=True, strict=True, extra="ignore")

    listened_at: int = Field(ge=0)
    user_name: str = Field(min_length=1)
    track_metadata: ListenTrackMetadata


class ResolvedListen(BaseModel):
    """Hold transient user and canonical artist keys during local aggregation."""

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    listened_at: int = Field(ge=0)
    user_key: str = Field(min_length=1)
    artist_ids: tuple[str, ...] = Field(min_length=1)


class SourceProvenance(BaseModel):
    """Identify the exact local ListenBrainz artifact behind evidence."""

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    source_key: Literal["listenbrainz"] = "listenbrainz"
    snapshot_ref: str = Field(min_length=1)
    artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class CooccurrenceConfig(BaseModel):
    """Define fixed, time-ordered evidence windows without selecting a model."""

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    window_seconds: int = Field(default=86_400, gt=0)
    minimum_distinct_users: int = Field(default=2, gt=0)


class ArtistCooccurrenceEvidence(BaseModel):
    """Represent a source-qualified aggregate, not a similarity score."""

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    type: Literal["artist_cooccurrence_evidence"] = "artist_cooccurrence_evidence"
    source: SourceProvenance
    aggregation_version: Literal["fixed-window-distinct-users-v1"] = (
        "fixed-window-distinct-users-v1"
    )
    left_artist_id: str = Field(pattern=r"^musicbrainz:artist:[0-9a-f-]{36}$")
    right_artist_id: str = Field(pattern=r"^musicbrainz:artist:[0-9a-f-]{36}$")
    window_start: int = Field(ge=0)
    window_end: int = Field(gt=0)
    window_seconds: int = Field(gt=0)
    distinct_user_count: int = Field(gt=0)


def _resolve_artist_ids(listen: Listen) -> tuple[str, ...]:
    mapping = listen.track_metadata.mbid_mapping
    additional = listen.track_metadata.additional_info
    candidates = mapping.artist_mbids if mapping and mapping.artist_mbids else ()
    if not candidates and additional:
        candidates = additional.artist_mbids

    resolved: set[str] = set()
    for candidate in candidates:
        try:
            artist_id = UUID(candidate)
        except ValueError:
            continue
        resolved.add(f"musicbrainz:artist:{artist_id}")
    return tuple(sorted(resolved))


def _drain_long_line(stream: BinaryLineReader) -> None:
    while continuation := stream.readline(64 * 1024):
        if continuation.endswith(b"\n"):
            return


def iter_listens_jsonl(
    stream: BinaryLineReader,
    limits: AdapterLimits,
) -> Iterator[ResolvedListen]:
    """Stream canonical artist IDs while keeping raw user keys transient."""
    count = 0
    while line := stream.readline(limits.max_record_bytes + 1):
        if len(line) > limits.max_record_bytes and not line.endswith(b"\n"):
            _drain_long_line(stream)
            raise ListenBrainzAdapterError("ListenBrainz record exceeds max_record_bytes")
        record = line.strip()
        if not record:
            continue
        count += 1
        if count > limits.max_records:
            raise ListenBrainzAdapterError("ListenBrainz input exceeds max_records")
        try:
            listen = Listen.model_validate_json(record)
        except ValueError as error:
            raise ListenBrainzAdapterError("invalid ListenBrainz JSON record") from error
        artist_ids = _resolve_artist_ids(listen)
        if artist_ids:
            yield ResolvedListen(
                listened_at=listen.listened_at,
                user_key=listen.user_name,
                artist_ids=artist_ids,
            )


def _safe_member_name(name: str) -> PurePosixPath:
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts:
        raise ListenBrainzAdapterError(f"unsafe archive member path: {name}")
    return path


def _is_listen_member(path: PurePosixPath) -> bool:
    return path.suffix in {".listens", ".json", ".jsonl"}


def _iter_tar_listens(
    archive: tarfile.TarFile,
    limits: AdapterLimits,
) -> Iterator[ResolvedListen]:
    found = False
    decompressed_bytes = 0
    record_count = 0
    for member in archive:
        if not member.isfile():
            continue
        decompressed_bytes += member.size
        if decompressed_bytes > limits.max_decompressed_bytes:
            raise ListenBrainzAdapterError("ListenBrainz archive exceeds max_decompressed_bytes")
        member_path = _safe_member_name(member.name)
        if not _is_listen_member(member_path):
            continue
        found = True
        if member.size > limits.max_member_bytes:
            raise ListenBrainzAdapterError("ListenBrainz member exceeds max_member_bytes")
        stream = archive.extractfile(member)
        if stream is None:
            raise ListenBrainzAdapterError(f"cannot read archive member: {member.name}")
        try:
            for listen in iter_listens_jsonl(stream, limits):
                record_count += 1
                if record_count > limits.max_records:
                    raise ListenBrainzAdapterError("ListenBrainz archive exceeds max_records")
                yield listen
        finally:
            stream.close()
    if not found:
        raise ListenBrainzAdapterError("ListenBrainz archive has no listen JSONL members")


def iter_listen_archive(
    path: Path,
    limits: AdapterLimits,
    *,
    compression: Literal["tar", "tar.zst"],
) -> Iterator[ResolvedListen]:
    """Stream local official tar or tar.zst dump members without extraction."""
    if path.stat().st_size > limits.max_archive_bytes:
        raise ListenBrainzAdapterError("ListenBrainz archive exceeds max_archive_bytes")
    with path.open("rb") as raw_stream:
        if compression == "tar":
            with tarfile.open(fileobj=raw_stream, mode="r|") as archive:
                yield from _iter_tar_listens(archive, limits)
            return
        decompressor = zstandard.ZstdDecompressor()
        with (
            decompressor.stream_reader(raw_stream) as decompressed_stream,
            tarfile.open(fileobj=decompressed_stream, mode="r|") as archive,
        ):
            yield from _iter_tar_listens(archive, limits)


def _window_evidence(
    user_artists: dict[str, set[str]],
    *,
    window_start: int,
    config: CooccurrenceConfig,
    provenance: SourceProvenance,
    limits: AdapterLimits,
) -> Iterator[ArtistCooccurrenceEvidence]:
    pair_counts: dict[tuple[str, str], int] = {}
    for artist_ids in user_artists.values():
        for pair in itertools.combinations(sorted(artist_ids), 2):
            if pair not in pair_counts and len(pair_counts) >= limits.max_pairs_per_window:
                raise ListenBrainzAdapterError("ListenBrainz window exceeds max_pairs_per_window")
            pair_counts[pair] = pair_counts.get(pair, 0) + 1
    for (left_artist_id, right_artist_id), distinct_users in sorted(pair_counts.items()):
        if distinct_users < config.minimum_distinct_users:
            continue
        yield ArtistCooccurrenceEvidence(
            source=provenance,
            left_artist_id=left_artist_id,
            right_artist_id=right_artist_id,
            window_start=window_start,
            window_end=window_start + config.window_seconds,
            window_seconds=config.window_seconds,
            distinct_user_count=distinct_users,
        )


def aggregate_artist_cooccurrence(
    listens: Iterator[ResolvedListen],
    config: CooccurrenceConfig,
    provenance: SourceProvenance,
    limits: AdapterLimits,
) -> Iterator[ArtistCooccurrenceEvidence]:
    """Aggregate ordered listens with bounded in-memory state and no user output."""
    current_window: int | None = None
    user_artists: dict[str, set[str]] = {}
    for listen in listens:
        window_start = listen.listened_at // config.window_seconds * config.window_seconds
        if current_window is not None and window_start < current_window:
            raise ListenBrainzAdapterError("ListenBrainz input must be ordered by listened_at")
        if current_window is not None and window_start > current_window:
            yield from _window_evidence(
                user_artists,
                window_start=current_window,
                config=config,
                provenance=provenance,
                limits=limits,
            )
            user_artists.clear()
        current_window = window_start
        artists = user_artists.get(listen.user_key)
        if artists is None:
            if len(user_artists) >= limits.max_users_per_window:
                raise ListenBrainzAdapterError("ListenBrainz window exceeds max_users_per_window")
            artists = set()
            user_artists[listen.user_key] = artists
        artists.update(listen.artist_ids)
        if len(artists) > limits.max_artists_per_user_window:
            raise ListenBrainzAdapterError(
                "ListenBrainz user window exceeds max_artists_per_user_window"
            )
    if current_window is not None:
        yield from _window_evidence(
            user_artists,
            window_start=current_window,
            config=config,
            provenance=provenance,
            limits=limits,
        )


def write_cooccurrence_evidence(
    evidence: Iterator[ArtistCooccurrenceEvidence],
    destination: Path,
) -> int:
    """Atomically write aggregate evidence JSONL without raw listen data."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.tmp")
    count = 0
    try:
        with temporary.open("xb") as stream:
            for record in evidence:
                stream.write(record.model_dump_json().encode("utf-8"))
                stream.write(b"\n")
                count += 1
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    return count
