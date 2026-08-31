"""Bounded streaming projection of official ListenBrainz listen dumps."""

import hashlib
import io
import itertools
import resource
import tarfile
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Protocol, override
from uuid import UUID

import zstandard
from pydantic import ValidationError

from musix.models.catalog import ArtistCoListenProjection, ArtistCoListenRunProjection
from musix.models.listenbrainz import ListenBrainzAggregationConfig, ListenBrainzListen
from musix.models.pipeline import (
    ParsedSourceRecord,
    RejectedSourceRecord,
    SourceLimits,
    SourceRecord,
)
from musix.models.sources import DownloadSource
from musix.sources.registry import SourceAdapterError


class ListenBrainzSourceError(SourceAdapterError):
    """Report a source shape, ordering, archive, or bounded-state violation."""


class _BinaryReader(Protocol):
    def read(self, size: int = -1, /) -> bytes:
        """Read bounded binary data."""
        ...


class _BoundedReader(io.RawIOBase):
    def __init__(self, stream: _BinaryReader, maximum_bytes: int) -> None:
        self._stream = stream
        self._maximum_bytes = maximum_bytes
        self._bytes_read = 0

    @override
    def read(self, size: int = -1, /) -> bytes:
        data = self._stream.read(size)
        self._bytes_read += len(data)
        if self._bytes_read > self._maximum_bytes:
            raise ListenBrainzSourceError("archive exceeds max_decompression_ratio")
        return data

    @override
    def readable(self) -> bool:
        """Report that tarfile may stream reads from this wrapper."""
        return True


@dataclass(slots=True)
class _Counters:
    listens_seen: int = 0
    listens_with_artist_mbid: int = 0
    user_windows: int = 0
    candidate_pairs: int = 0
    emitted_pairs: int = 0
    quarantined_records: int = 0
    minimum_listened_at: int | None = None
    maximum_listened_at: int | None = None


@dataclass(slots=True)
class _AggregationState:
    current_window: int | None = None
    output_ordinal: int = -1
    user_artists: dict[int, set[str]] = field(default_factory=dict)
    unordered_windows: dict[int, dict[int, set[str]]] = field(default_factory=dict)
    active_user_windows: int = 0
    distinct_artists: set[str] = field(default_factory=set)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _source_artist_ids(listen: ListenBrainzListen) -> tuple[str, ...]:
    metadata = listen.track_metadata
    mapping = metadata.mbid_mapping
    additional = metadata.additional_info
    candidates = mapping.artist_mbids if mapping is not None and mapping.artist_mbids else ()
    if not candidates and additional is not None:
        candidates = additional.artist_mbids
    artist_ids: set[str] = set()
    for candidate in candidates:
        try:
            artist_id = UUID(candidate)
        except ValueError:
            continue
        artist_ids.add(f"musicbrainz:artist:{artist_id}")
    return tuple(sorted(artist_ids))


def _safe_member_path(name: str) -> PurePosixPath:
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts:
        raise ListenBrainzSourceError(f"unsafe archive member path: {name}")
    return path


def _record(
    projection: ArtistCoListenProjection | ArtistCoListenRunProjection, ordinal: int
) -> ParsedSourceRecord:
    canonical = projection.model_dump_json().encode()
    return ParsedSourceRecord(
        ordinal=ordinal,
        exact_sha256=_sha256(canonical),
        byte_length=len(canonical),
        projection=projection,
    )


class ListenBrainzIncrementalAdapter:
    """Aggregate source-qualified artist pairs once per listener and fixed window."""

    key = "listenbrainz_incremental_listens_v1"
    version = "1.0.0"
    aggregation_version = "fixed-window-distinct-users-v1"

    def __init__(self, config: ListenBrainzAggregationConfig | None = None) -> None:
        """Bind one explicit aggregation policy to this adapter instance."""
        self.config = config or ListenBrainzAggregationConfig()
        self._build_sha256 = _sha256(Path(__file__).read_bytes())

    @property
    def build_sha256(self) -> str:
        """Return the exact adapter module hash used for provenance."""
        return self._build_sha256

    def supports(self, source: DownloadSource) -> bool:
        """Accept only the declared official tar.zst incremental artifact shape."""
        return (
            source.adapter == self.key
            and source.compression == "tar.zst"
            and source.expected_content_type == "application/octet-stream"
            and source.normalize
        )

    def _window_records(
        self,
        user_artists: dict[int, set[str]],
        *,
        window_start: int,
        counters: _Counters,
    ) -> Iterator[ArtistCoListenProjection]:
        pair_counts: dict[tuple[str, str], int] = {}
        counters.user_windows += len(user_artists)
        for artist_ids in user_artists.values():
            for pair in itertools.combinations(sorted(artist_ids), 2):
                if pair not in pair_counts and len(pair_counts) >= self.config.max_pairs_per_window:
                    raise ListenBrainzSourceError("window exceeds max_pairs_per_window")
                pair_counts[pair] = pair_counts.get(pair, 0) + 1
        counters.candidate_pairs += len(pair_counts)
        for (left_artist_id, right_artist_id), distinct_users in sorted(pair_counts.items()):
            if distinct_users < self.config.minimum_distinct_users:
                continue
            counters.emitted_pairs += 1
            external_id = _sha256(f"{left_artist_id}\0{right_artist_id}\0{window_start}".encode())
            yield ArtistCoListenProjection(
                external_id=external_id,
                left_artist_source_id=left_artist_id,
                right_artist_source_id=right_artist_id,
                window_start=window_start,
                window_end=window_start + self.config.window_seconds,
                distinct_user_count=distinct_users,
            )

    def _iter_member_lines(
        self,
        archive: tarfile.TarFile,
        limits: SourceLimits,
        *,
        started: float,
    ) -> Iterator[bytes]:
        listen_members = 0
        for member in archive:
            member_path = _safe_member_path(member.name)
            if not member.isfile() or member_path.suffix != ".listens":
                continue
            listen_members += 1
            if listen_members > self.config.max_listen_members:
                raise ListenBrainzSourceError("archive exceeds max_listen_members")
            if member.size > limits.max_member_bytes:
                raise ListenBrainzSourceError("listen member exceeds max_member_bytes")
            stream = archive.extractfile(member)
            if stream is None:
                raise ListenBrainzSourceError(f"cannot read archive member: {member.name}")
            try:
                while line := stream.readline(limits.max_record_bytes + 1):
                    if time.monotonic() - started > limits.timeout_seconds:
                        raise TimeoutError("ListenBrainz adapter exceeded timeout_seconds")
                    if len(line) > limits.max_record_bytes:
                        raise ListenBrainzSourceError("listen line exceeds max_record_bytes")
                    yield line
            finally:
                stream.close()
        if listen_members == 0:
            raise ListenBrainzSourceError("archive has no .listens member")

    def _iter_lines(
        self,
        path: Path,
        limits: SourceLimits,
        *,
        started: float,
    ) -> Iterator[bytes]:
        archive_bytes = path.stat().st_size
        if archive_bytes > limits.max_archive_bytes:
            raise ListenBrainzSourceError("archive exceeds max_archive_bytes")
        maximum_decompressed = int(archive_bytes * limits.max_decompression_ratio)
        with path.open("rb") as raw_stream:
            decompressor = zstandard.ZstdDecompressor()
            with decompressor.stream_reader(raw_stream) as decompressed:
                bounded = _BoundedReader(decompressed, maximum_decompressed)
                with tarfile.open(fileobj=bounded, mode="r|") as archive:
                    yield from self._iter_member_lines(archive, limits, started=started)

    @staticmethod
    def _update_timestamp_coverage(counters: _Counters, listened_at: int) -> None:
        counters.minimum_listened_at = (
            listened_at
            if counters.minimum_listened_at is None
            else min(counters.minimum_listened_at, listened_at)
        )
        counters.maximum_listened_at = (
            listened_at
            if counters.maximum_listened_at is None
            else max(counters.maximum_listened_at, listened_at)
        )

    @staticmethod
    def _maybe_emit(
        projection: ArtistCoListenProjection | ArtistCoListenRunProjection,
        state: _AggregationState,
        *,
        start_after: int,
    ) -> ParsedSourceRecord | None:
        state.output_ordinal += 1
        if state.output_ordinal <= start_after:
            return None
        return _record(projection, state.output_ordinal)

    def _flush_window(
        self,
        state: _AggregationState,
        counters: _Counters,
        *,
        start_after: int,
    ) -> Iterator[ParsedSourceRecord]:
        if state.current_window is None:
            return
        for projection in self._window_records(
            state.user_artists,
            window_start=state.current_window,
            counters=counters,
        ):
            record = self._maybe_emit(projection, state, start_after=start_after)
            if record is not None:
                yield record
        state.user_artists.clear()

    def _consume_valid_listen(
        self,
        listen: ListenBrainzListen,
        state: _AggregationState,
        counters: _Counters,
        *,
        start_after: int,
    ) -> Iterator[ParsedSourceRecord]:
        self._update_timestamp_coverage(counters, listen.listened_at)
        artist_ids = _source_artist_ids(listen)
        if not artist_ids:
            return
        counters.listens_with_artist_mbid += 1
        window_start = listen.listened_at // self.config.window_seconds * self.config.window_seconds
        if self.config.ordering == "unordered_bounded":
            user_artists = state.unordered_windows.get(window_start)
            if user_artists is None:
                if len(state.unordered_windows) >= self.config.max_active_windows:
                    raise ListenBrainzSourceError("archive exceeds max_active_windows")
                user_artists = {}
                state.unordered_windows[window_start] = user_artists
            self._add_user_artists(listen, artist_ids, user_artists, state)
            return
        if state.current_window is not None and window_start > state.current_window:
            raise ListenBrainzSourceError("listen windows are not ordered newest_first")
        if state.current_window is not None and window_start < state.current_window:
            yield from self._flush_window(state, counters, start_after=start_after)
        state.current_window = window_start
        self._add_user_artists(listen, artist_ids, state.user_artists, state)

    def _add_user_artists(
        self,
        listen: ListenBrainzListen,
        artist_ids: tuple[str, ...],
        user_artists: dict[int, set[str]],
        state: _AggregationState,
    ) -> None:
        artists = user_artists.get(listen.user_id)
        if artists is None:
            if len(user_artists) >= self.config.max_users_per_window:
                raise ListenBrainzSourceError("window exceeds max_users_per_window")
            if state.active_user_windows >= self.config.max_total_user_windows:
                raise ListenBrainzSourceError("archive exceeds max_total_user_windows")
            artists = set()
            user_artists[listen.user_id] = artists
            state.active_user_windows += 1
        artists.update(artist_ids)
        if len(artists) > self.config.max_artists_per_user_window:
            raise ListenBrainzSourceError("user window exceeds max_artists_per_user_window")
        state.distinct_artists.update(artist_ids)
        if len(state.distinct_artists) > self.config.max_distinct_artists:
            raise ListenBrainzSourceError("archive exceeds max_distinct_artists")

    def _flush_all_windows(
        self,
        state: _AggregationState,
        counters: _Counters,
        *,
        start_after: int,
    ) -> Iterator[ParsedSourceRecord]:
        if self.config.ordering == "newest_first":
            yield from self._flush_window(state, counters, start_after=start_after)
            return
        for window_start in sorted(state.unordered_windows, reverse=True):
            state.current_window = window_start
            state.user_artists = state.unordered_windows[window_start]
            yield from self._flush_window(state, counters, start_after=start_after)
        state.unordered_windows.clear()

    def _consume_line(
        self,
        line: bytes,
        state: _AggregationState,
        counters: _Counters,
        limits: SourceLimits,
        *,
        start_after: int,
    ) -> Iterator[SourceRecord]:
        stripped = line.strip()
        if not stripped:
            return
        counters.listens_seen += 1
        if counters.listens_seen > limits.max_records:
            raise ListenBrainzSourceError("archive exceeds max_records")
        try:
            listen = ListenBrainzListen.model_validate_json(stripped)
        except ValidationError as error:
            counters.quarantined_records += 1
            state.output_ordinal += 1
            if state.output_ordinal > start_after:
                yield RejectedSourceRecord(
                    ordinal=state.output_ordinal,
                    exact_sha256=_sha256(stripped),
                    byte_length=len(stripped),
                    reason=f"invalid ListenBrainz listen: {error.title}",
                )
            return
        yield from self._consume_valid_listen(
            listen,
            state,
            counters,
            start_after=start_after,
        )

    def _completion_projection(
        self,
        state: _AggregationState,
        counters: _Counters,
        *,
        started: float,
    ) -> ArtistCoListenRunProjection:
        run_external_id = _sha256(
            f"{self.key}\0{self.version}\0{self._build_sha256}\0{self.config.model_dump_json()}".encode()
        )
        return ArtistCoListenRunProjection(
            external_id=run_external_id,
            adapter_key=self.key,
            adapter_version=self.version,
            adapter_build_sha256=self._build_sha256,
            aggregation_version=self.aggregation_version,
            configuration_sha256=_sha256(self.config.model_dump_json().encode()),
            window_seconds=self.config.window_seconds,
            minimum_distinct_users=self.config.minimum_distinct_users,
            listens_seen=counters.listens_seen,
            listens_with_artist_mbid=counters.listens_with_artist_mbid,
            distinct_artists=len(state.distinct_artists),
            user_windows=counters.user_windows,
            candidate_pairs=counters.candidate_pairs,
            emitted_pairs=counters.emitted_pairs,
            quarantined_records=counters.quarantined_records,
            minimum_listened_at=counters.minimum_listened_at,
            maximum_listened_at=counters.maximum_listened_at,
            elapsed_ms=int((time.monotonic() - started) * 1000),
            peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
        )

    def iter_records(
        self,
        path: Path,
        limits: SourceLimits,
        *,
        start_after: int,
    ) -> Iterator[SourceRecord]:
        """Stream privacy-thresholded aggregates; never emit a listener identifier."""
        started = time.monotonic()
        counters = _Counters()
        state = _AggregationState()
        for line in self._iter_lines(path, limits, started=started):
            yield from self._consume_line(
                line,
                state,
                counters,
                limits,
                start_after=start_after,
            )
        yield from self._flush_all_windows(state, counters, start_after=start_after)
        state.user_artists.clear()
        completion = self._completion_projection(
            state,
            counters,
            started=started,
        )
        record = self._maybe_emit(completion, state, start_after=start_after)
        if record is not None:
            yield record
