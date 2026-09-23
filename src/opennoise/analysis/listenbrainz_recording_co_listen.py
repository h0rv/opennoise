"""Bounded, local-only recording co-listen coverage experiment.

The experiment reads one retained ListenBrainz archive and holds listener IDs
only while aggregating a fixed event-time window.  Its artifact contains
coverage and privacy-filtered *counts* only: never raw listens, listener IDs,
recording IDs, pairs, ranks, or a serveable neighbor index.
"""

from __future__ import annotations

import hashlib
import io
import itertools
import sqlite3
import tarfile
from collections import defaultdict
from contextlib import closing
from dataclasses import asdict, dataclass, field
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Literal, Protocol, override
from uuid import UUID

import zstandard
from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from opennoise.models import FrozenModel
from opennoise.types import Sha256  # noqa: TC001  # Pydantic resolves the alias at definition.

if TYPE_CHECKING:
    from collections.abc import Iterator

_REVISION = "listenbrainz-recording-co-listen-coverage-v1"
_RECORDING_PREFIX = "musicbrainz:recording:"


class RecordingCoListenExperimentError(ValueError):
    """Report an invalid bounded local recording experiment input."""


class RecordingCoListenExperimentSettings(FrozenModel):
    """Bound memory and explicitly identify this prefix-sample experiment."""

    revision: Literal["listenbrainz-recording-co-listen-settings-v1"] = (
        "listenbrainz-recording-co-listen-settings-v1"
    )
    sample_strategy: Literal["archive_prefix_records"] = "archive_prefix_records"
    maximum_records: int = Field(default=250_000, gt=0, le=1_000_000)
    maximum_archive_bytes: int = Field(default=300 * 1024 * 1024, gt=0)
    maximum_decompressed_bytes: int = Field(default=16 * 1024 * 1024 * 1024, gt=0)
    maximum_member_bytes: int = Field(default=16 * 1024 * 1024 * 1024, gt=0)
    maximum_record_bytes: int = Field(default=2 * 1024 * 1024, gt=0)
    window_seconds: int = Field(default=86_400, gt=0)
    minimum_distinct_users: int = Field(default=5, gt=0)
    maximum_active_windows: int = Field(default=32, gt=0, le=64)
    maximum_users_per_window: int = Field(default=100_000, gt=0)
    maximum_recordings_per_user_window: int = Field(default=100, gt=1)
    maximum_pairs_per_window: int = Field(default=500_000, gt=0)


class RecordingMbidCoverage(FrozenModel):
    """Aggregate identifier availability, separated by identifier provenance."""

    raw_records_seen: int = Field(ge=0)
    valid_listen_records: int = Field(ge=0)
    malformed_listen_records: int = Field(ge=0)
    mapping_recording_mbid_present: int = Field(ge=0)
    mapping_recording_mbid_valid_uuid: int = Field(ge=0)
    additional_recording_mbid_present: int = Field(ge=0)
    additional_recording_mbid_valid_uuid: int = Field(ge=0)
    selected_resolved_mapping_recording_count: int = Field(ge=0)
    selected_submitted_additional_recording_count: int = Field(ge=0)


class RecordingCoListenAggregation(FrozenModel):
    """Aggregate-only co-listen result after transient listener aggregation."""

    source_window_count: int = Field(ge=0)
    unique_selected_recording_count: int = Field(ge=0)
    candidate_pair_count: int = Field(ge=0)
    privacy_filtered_pair_count: int = Field(ge=0)
    catalog_recording_overlap_count: int = Field(ge=0)


class RecordingCoListenExperimentArtifact(FrozenModel):
    """A non-serving local research result with no raw identifier output."""

    revision: Literal["listenbrainz-recording-co-listen-coverage-v1"] = _REVISION
    local_only: Literal[True] = True
    export_allowed: Literal[False] = False
    serving_allowed: Literal[False] = False
    source_artifact_sha256: Sha256
    source_artifact_byte_size: int = Field(ge=0)
    catalog_database_sha256: Sha256
    catalog_recording_id_set_sha256: Sha256
    settings: RecordingCoListenExperimentSettings
    coverage: RecordingMbidCoverage
    aggregation: RecordingCoListenAggregation


class _RawMbidMapping(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True, extra="ignore")

    recording_mbid: str | None = None


class _RawAdditionalInfo(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True, extra="ignore")

    recording_mbid: str | None = None


class _RawTrackMetadata(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True, extra="ignore")

    mbid_mapping: _RawMbidMapping | None = None
    additional_info: _RawAdditionalInfo | None = None


class _RawListen(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True, extra="ignore")

    listened_at: int = Field(validation_alias=AliasChoices("timestamp", "listened_at"), ge=0)
    user_id: int = Field(ge=0)
    track_metadata: _RawTrackMetadata


@dataclass(slots=True)
class _MutableCoverage:
    raw_records_seen: int = 0
    valid_listen_records: int = 0
    malformed_listen_records: int = 0
    mapping_recording_mbid_present: int = 0
    mapping_recording_mbid_valid_uuid: int = 0
    additional_recording_mbid_present: int = 0
    additional_recording_mbid_valid_uuid: int = 0
    selected_resolved_mapping_recording_count: int = 0
    selected_submitted_additional_recording_count: int = 0

    def freeze(self) -> RecordingMbidCoverage:
        return RecordingMbidCoverage(**asdict(self))


@dataclass(slots=True)
class _TransientState:
    recordings_by_window_user: dict[int, dict[int, set[str]]] = field(default_factory=dict)
    selected_recordings: set[str] = field(default_factory=set)


class _BinaryReader(Protocol):
    def read(self, size: int = -1, /) -> bytes:
        """Read bounded binary input."""


class _BoundedReader(io.RawIOBase):
    """Bound decompressed bytes before tarfile parses a member stream."""

    def __init__(self, stream: _BinaryReader, maximum_bytes: int) -> None:
        self._stream = stream
        self._maximum_bytes = maximum_bytes
        self._bytes_read = 0

    @override
    def read(self, size: int = -1, /) -> bytes:
        data = self._stream.read(size)
        self._bytes_read += len(data)
        if self._bytes_read > self._maximum_bytes:
            raise RecordingCoListenExperimentError(
                "recording experiment exceeds decompression limit"
            )
        return data

    @override
    def readable(self) -> bool:
        return True


def load_catalog_recording_ids(catalog_path: Path) -> frozenset[str]:
    """Load exact catalog recording identifiers without retaining names or joins."""
    try:
        with closing(_read_only(catalog_path)) as connection:
            rows = connection.execute(
                """SELECT identifier.value
                   FROM recordings
                   JOIN entity_identifiers AS identifier ON identifier.entity_id = recordings.id
                   JOIN identifier_types AS identifier_type
                     ON identifier_type.id = identifier.identifier_type_id
                   WHERE identifier_type.type_key = 'musicbrainz_recording_id'
                   ORDER BY identifier.value"""
            )
            return frozenset(f"{_RECORDING_PREFIX}{recording_id}" for (recording_id,) in rows)
    except sqlite3.Error as error:
        raise RecordingCoListenExperimentError(
            "cannot load catalog recording identifiers"
        ) from error


def run_recording_co_listen_experiment(
    *,
    archive_path: Path,
    source_artifact_sha256: str,
    catalog_recording_ids: frozenset[str],
    catalog_database_sha256: str,
    settings: RecordingCoListenExperimentSettings | None = None,
) -> RecordingCoListenExperimentArtifact:
    """Measure exact recording-ID coverage and aggregate only privacy-safe pair counts."""
    resolved_settings = settings or RecordingCoListenExperimentSettings()
    if not archive_path.is_file():
        raise RecordingCoListenExperimentError("ListenBrainz archive does not exist")
    source_bytes = archive_path.stat().st_size
    if source_bytes > resolved_settings.maximum_archive_bytes:
        raise RecordingCoListenExperimentError("recording experiment exceeds archive-byte limit")
    if _sha256_file(archive_path) != source_artifact_sha256:
        raise RecordingCoListenExperimentError("ListenBrainz archive hash does not match receipt")
    coverage = _MutableCoverage()
    state = _TransientState()
    for line in _iter_listen_lines(archive_path, resolved_settings):
        if coverage.raw_records_seen >= resolved_settings.maximum_records:
            break
        coverage.raw_records_seen += 1
        _consume_line(line, coverage, state, resolved_settings)
    aggregation = _aggregate(state, resolved_settings, catalog_recording_ids)
    state.recordings_by_window_user.clear()
    state.selected_recordings.clear()
    return RecordingCoListenExperimentArtifact(
        source_artifact_sha256=source_artifact_sha256,
        source_artifact_byte_size=source_bytes,
        catalog_database_sha256=catalog_database_sha256,
        catalog_recording_id_set_sha256=recording_id_set_sha256(catalog_recording_ids),
        settings=resolved_settings,
        coverage=coverage.freeze(),
        aggregation=aggregation,
    )


def _consume_line(
    line: bytes,
    coverage: _MutableCoverage,
    state: _TransientState,
    settings: RecordingCoListenExperimentSettings,
) -> None:
    try:
        listen = _RawListen.model_validate_json(line)
    except ValueError:
        coverage.malformed_listen_records += 1
        return
    coverage.valid_listen_records += 1
    recording_id = _resolve_recording_id(listen, coverage)
    if recording_id is None:
        return
    window_start = listen.listened_at // settings.window_seconds * settings.window_seconds
    users = state.recordings_by_window_user.get(window_start)
    if users is None:
        if len(state.recordings_by_window_user) >= settings.maximum_active_windows:
            raise RecordingCoListenExperimentError(
                "recording experiment exceeds active-window limit"
            )
        users = {}
        state.recordings_by_window_user[window_start] = users
    recordings = users.get(listen.user_id)
    if recordings is None:
        if len(users) >= settings.maximum_users_per_window:
            raise RecordingCoListenExperimentError("recording experiment exceeds user-window limit")
        recordings = set()
        users[listen.user_id] = recordings
    recordings.add(recording_id)
    if len(recordings) > settings.maximum_recordings_per_user_window:
        raise RecordingCoListenExperimentError(
            "recording experiment exceeds recording-per-user limit"
        )
    state.selected_recordings.add(recording_id)


def _resolve_recording_id(listen: _RawListen, coverage: _MutableCoverage) -> str | None:
    mapping = listen.track_metadata.mbid_mapping
    additional = listen.track_metadata.additional_info
    mapped = mapping.recording_mbid if mapping is not None else None
    submitted = additional.recording_mbid if additional is not None else None
    mapped_id = _valid_recording_id(mapped, coverage, "mapping")
    submitted_id = _valid_recording_id(submitted, coverage, "additional")
    if mapped_id is not None:
        coverage.selected_resolved_mapping_recording_count += 1
        return mapped_id
    if submitted_id is not None:
        coverage.selected_submitted_additional_recording_count += 1
        return submitted_id
    return None


def _valid_recording_id(
    raw_id: str | None,
    coverage: _MutableCoverage,
    source: Literal["mapping", "additional"],
) -> str | None:
    if raw_id is None or not raw_id.strip():
        return None
    if source == "mapping":
        coverage.mapping_recording_mbid_present += 1
    else:
        coverage.additional_recording_mbid_present += 1
    try:
        canonical = str(UUID(raw_id))
    except ValueError:
        return None
    if source == "mapping":
        coverage.mapping_recording_mbid_valid_uuid += 1
    else:
        coverage.additional_recording_mbid_valid_uuid += 1
    return f"{_RECORDING_PREFIX}{canonical}"


def _aggregate(
    state: _TransientState,
    settings: RecordingCoListenExperimentSettings,
    catalog_recording_ids: frozenset[str],
) -> RecordingCoListenAggregation:
    candidate_pair_count = 0
    privacy_filtered_pair_count = 0
    for users in state.recordings_by_window_user.values():
        pair_counts: dict[tuple[str, str], int] = defaultdict(int)
        for recordings in users.values():
            for pair in itertools.combinations(sorted(recordings), 2):
                if (
                    pair not in pair_counts
                    and len(pair_counts) >= settings.maximum_pairs_per_window
                ):
                    raise RecordingCoListenExperimentError(
                        "recording experiment exceeds pair-window limit"
                    )
                pair_counts[pair] += 1
        candidate_pair_count += len(pair_counts)
        privacy_filtered_pair_count += sum(
            distinct_users >= settings.minimum_distinct_users
            for distinct_users in pair_counts.values()
        )
    return RecordingCoListenAggregation(
        source_window_count=len(state.recordings_by_window_user),
        unique_selected_recording_count=len(state.selected_recordings),
        candidate_pair_count=candidate_pair_count,
        privacy_filtered_pair_count=privacy_filtered_pair_count,
        catalog_recording_overlap_count=len(state.selected_recordings & catalog_recording_ids),
    )


def _iter_listen_lines(
    path: Path, settings: RecordingCoListenExperimentSettings
) -> Iterator[bytes]:
    """Yield raw JSONL lines from safe, streaming official tar.zst members."""
    with path.open("rb") as raw_stream:
        decompressor = zstandard.ZstdDecompressor()
        with (
            decompressor.stream_reader(raw_stream) as decompressed,
            tarfile.open(
                fileobj=_BoundedReader(decompressed, settings.maximum_decompressed_bytes), mode="r|"
            ) as archive,
        ):
            declared_member_bytes = 0
            found_member = False
            for member in archive:
                member_path = _safe_member_path(member.name)
                if not member.isfile() or member_path.suffix != ".listens":
                    continue
                found_member = True
                if member.size > settings.maximum_member_bytes:
                    raise RecordingCoListenExperimentError(
                        "recording experiment exceeds member-byte limit"
                    )
                declared_member_bytes += member.size
                if declared_member_bytes > settings.maximum_decompressed_bytes:
                    raise RecordingCoListenExperimentError(
                        "recording experiment exceeds declared decompression limit"
                    )
                stream = archive.extractfile(member)
                if stream is None:
                    raise RecordingCoListenExperimentError("cannot read ListenBrainz member")
                try:
                    while line := stream.readline(settings.maximum_record_bytes + 1):
                        if len(line) > settings.maximum_record_bytes:
                            raise RecordingCoListenExperimentError(
                                "recording experiment exceeds JSONL record-byte limit"
                            )
                        if line.strip():
                            yield line
                finally:
                    stream.close()
            if not found_member:
                raise RecordingCoListenExperimentError("ListenBrainz archive has no listen member")


def _safe_member_path(name: str) -> PurePosixPath:
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts:
        raise RecordingCoListenExperimentError("unsafe ListenBrainz archive member")
    return path


def _read_only(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)
    connection.execute("PRAGMA query_only = ON")
    return connection


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_file(path: Path) -> str:
    """Hash a receipt-bound local artifact without retaining its contents."""
    return _sha256_file(path)


def recording_id_set_sha256(recording_ids: frozenset[str]) -> str:
    """Hash the canonical exact-ID set used for catalog-overlap accounting."""
    return hashlib.sha256("\n".join(sorted(recording_ids)).encode()).hexdigest()
