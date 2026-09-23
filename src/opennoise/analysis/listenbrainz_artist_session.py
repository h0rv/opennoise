"""Bounded local-only artist-session approximation over retained ListenBrainz bytes."""

from __future__ import annotations

import hashlib
import io
import itertools
import tarfile
from collections import defaultdict
from collections.abc import Iterator  # noqa: TC003
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Protocol, override
from uuid import UUID

import zstandard
from pydantic import Field

from opennoise.models import FrozenModel
from opennoise.models.listenbrainz import ListenBrainzListen
from opennoise.types import Sha256  # noqa: TC001


class ArtistSessionError(ValueError):
    """The bounded local-only session approximation cannot safely continue."""


class ArtistSessionSettings(FrozenModel):
    """Fixed bounds for a non-production artist-only session approximation."""

    revision: str = "listenbrainz-artist-session-approx-settings-v1"
    maximum_records: int = Field(default=250_000, ge=1, le=500_000)
    maximum_archive_bytes: int = Field(default=300_000_000, ge=1, le=300_000_000)
    maximum_member_bytes: int = Field(default=16_000_000_000, ge=1)
    maximum_decompressed_bytes: int = Field(default=2_000_000_000, ge=1)
    maximum_line_bytes: int = Field(default=2_000_000, ge=1)
    maximum_artist_ids_per_listen: int = Field(default=16, ge=1, le=100)
    maximum_users: int = Field(default=100_000, ge=1, le=250_000)
    maximum_session_artists: int = Field(default=100, ge=2, le=500)
    maximum_candidate_pairs: int = Field(default=500_000, ge=1, le=2_000_000)
    maximum_pair_support_events: int = Field(default=2_000_000, ge=1, le=10_000_000)
    maximum_events_per_user: int = Field(default=100, ge=2, le=500)
    session_gap_seconds: int = Field(default=300, ge=1, le=3_600)
    fixed_duration_seconds: int = Field(default=180, ge=0, le=3_600)
    maximum_user_pair_contribution: int = Field(default=5, ge=1, le=20)
    minimum_pair_score_exclusive: int = Field(default=10, ge=0, le=100)
    minimum_distinct_users: int = Field(default=5, ge=5, le=100)
    top_neighbors_per_artist: int = Field(default=100, ge=1, le=100)


class ArtistSessionArtifact(FrozenModel):
    """Aggregate-only local result with no listener, artist, pair, or rank output."""

    revision: str = "listenbrainz-artist-session-approx-v1"
    local_only: bool = True
    export_allowed: bool = False
    serving_allowed: bool = False
    production_reproduction: bool = False
    source_artifact_sha256: Sha256
    source_artifact_byte_size: int = Field(ge=0)
    settings: ArtistSessionSettings
    raw_records_seen: int = Field(ge=0)
    valid_listens: int = Field(ge=0)
    listens_with_exact_artist_mbid: int = Field(ge=0)
    users_with_events: int = Field(ge=0)
    session_count: int = Field(ge=0)
    candidate_pair_count: int = Field(ge=0)
    threshold_pair_count: int = Field(ge=0)
    top_neighbor_relation_count: int = Field(ge=0)


@dataclass(slots=True)
class _State:
    events: dict[int, list[tuple[int, tuple[str, ...]]]] = field(
        default_factory=lambda: defaultdict(list)
    )
    valid: int = 0
    identified: int = 0


class _BinaryReader(Protocol):
    def read(self, size: int = -1, /) -> bytes:
        """Read a binary chunk."""


class _BoundedReader(io.RawIOBase):
    """Count every decompressed byte consumed by tarfile."""

    def __init__(self, stream: _BinaryReader, maximum_bytes: int) -> None:
        self._stream = stream
        self._maximum_bytes = maximum_bytes
        self._bytes_read = 0

    @override
    def read(self, size: int = -1, /) -> bytes:
        data = self._stream.read(size)
        self._bytes_read += len(data)
        if self._bytes_read > self._maximum_bytes:
            raise ArtistSessionError("decompressed bytes exceed bound")
        return data

    @override
    def readable(self) -> bool:
        return True


def run_artist_session_approximation(  # noqa: C901, PLR0912, PLR0915
    *,
    archive_path: Path,
    source_artifact_sha256: str,
    settings: ArtistSessionSettings | None = None,
) -> ArtistSessionArtifact:
    """Build aggregate-only session counts; this intentionally is not Labs reproduction."""
    config = settings or ArtistSessionSettings()
    if archive_path.stat().st_size > config.maximum_archive_bytes:
        raise ArtistSessionError("archive exceeds bounded byte limit")
    if _sha256_file(archive_path) != source_artifact_sha256:
        raise ArtistSessionError("archive hash does not match receipt")
    state = _State()
    seen = 0
    for line in _lines(archive_path, config):
        if seen >= config.maximum_records:
            break
        seen += 1
        try:
            listen = ListenBrainzListen.model_validate_json(line)
        except ValueError:
            continue
        state.valid += 1
        artists = _artists(listen, config)
        if not artists:
            continue
        if listen.user_id not in state.events and len(state.events) >= config.maximum_users:
            raise ArtistSessionError("user count exceeds bound")
        entries = state.events[listen.user_id]
        if len(entries) >= config.maximum_events_per_user:
            raise ArtistSessionError("user exceeds bounded session-event limit")
        entries.append((listen.listened_at, artists))
        state.identified += 1
    scores: dict[tuple[str, str], int] = defaultdict(int)
    supporters: dict[tuple[str, str], set[int]] = defaultdict(set)
    support_events = 0
    sessions = 0
    for user_id, events in state.events.items():
        contributed: dict[tuple[str, str], int] = defaultdict(int)
        current: set[str] = set()
        previous: int | None = None
        for timestamp, artists in sorted(events):
            if (
                previous is not None
                and timestamp - previous - config.fixed_duration_seconds
                > config.session_gap_seconds
            ):
                sessions += _add_session(current, contributed, config)
                current.clear()
            current.update(artists)
            previous = timestamp
        sessions += _add_session(current, contributed, config)
        for pair, score in contributed.items():
            if pair not in scores and len(scores) >= config.maximum_candidate_pairs:
                raise ArtistSessionError("candidate pair count exceeds bound")
            scores[pair] += score
            if user_id not in supporters[pair]:
                support_events += 1
                if support_events > config.maximum_pair_support_events:
                    raise ArtistSessionError("pair support events exceed bound")
                supporters[pair].add(user_id)
    kept = {
        pair: score
        for pair, score in scores.items()
        if score > config.minimum_pair_score_exclusive
        and len(supporters[pair]) >= config.minimum_distinct_users
    }
    neighbors: dict[str, int] = defaultdict(int)
    for left, right in kept:
        neighbors[left] += 1
        neighbors[right] += 1
    return ArtistSessionArtifact(
        source_artifact_sha256=source_artifact_sha256,
        source_artifact_byte_size=archive_path.stat().st_size,
        settings=config,
        raw_records_seen=seen,
        valid_listens=state.valid,
        listens_with_exact_artist_mbid=state.identified,
        users_with_events=len(state.events),
        session_count=sessions,
        candidate_pair_count=len(scores),
        threshold_pair_count=len(kept),
        top_neighbor_relation_count=sum(
            min(count, config.top_neighbors_per_artist) for count in neighbors.values()
        ),
    )


def _add_session(
    artists: set[str], contributed: dict[tuple[str, str], int], config: ArtistSessionSettings
) -> int:
    if len(artists) > config.maximum_session_artists:
        raise ArtistSessionError("session artist count exceeds bound")
    for pair in itertools.combinations(sorted(artists), 2):
        if contributed[pair] < config.maximum_user_pair_contribution:
            contributed[pair] += 1
    return int(bool(artists))


def _artists(listen: ListenBrainzListen, config: ArtistSessionSettings) -> tuple[str, ...]:
    mapping = listen.track_metadata.mbid_mapping
    additional = listen.track_metadata.additional_info
    values = (
        mapping.artist_mbids
        if mapping and mapping.artist_mbids
        else (additional.artist_mbids if additional else ())
    )
    if len(values) > config.maximum_artist_ids_per_listen:
        raise ArtistSessionError("artist IDs per listen exceed bound")
    result: set[str] = set()
    for value in values:
        try:
            result.add(str(UUID(value)))
        except ValueError:
            continue
    return tuple(sorted(result))


def _lines(path: Path, config: ArtistSessionSettings) -> Iterator[bytes]:
    with (
        path.open("rb") as raw,
        zstandard.ZstdDecompressor().stream_reader(raw) as decompressed,
        tarfile.open(
            fileobj=_BoundedReader(decompressed, config.maximum_decompressed_bytes), mode="r|"
        ) as archive,
    ):
        for member in archive:
            name = PurePosixPath(member.name)
            if name.is_absolute() or ".." in name.parts:
                raise ArtistSessionError("unsafe archive member")
            if member.isfile() and name.suffix == ".listens":
                if member.size > config.maximum_member_bytes:
                    raise ArtistSessionError("member exceeds bound")
                stream = archive.extractfile(member)
                if stream:
                    try:
                        while line := stream.readline(config.maximum_line_bytes + 1):
                            if len(line) > config.maximum_line_bytes:
                                raise ArtistSessionError("listen line exceeds bound")
                            yield line
                    finally:
                        stream.close()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()
