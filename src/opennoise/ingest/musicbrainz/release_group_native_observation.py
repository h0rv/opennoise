"""Build a bounded local observation receipt from native release-group facts."""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from opennoise.models.pipeline import SourceLimits
from opennoise.pipeline.source_cache import receipt_sha256, verify_source_cache_receipt
from opennoise.sources.musicbrainz import MusicBrainzReleaseGroup, _iter_raw_archive

if TYPE_CHECKING:
    from pathlib import Path

    from opennoise.models.sources import DownloadSource
    from opennoise.pipeline.source_cache import SourceCacheReceipt

_REVISION: Final = "musicbrainz-release-group-native-observation-v1"
_MEMBER: Final = "mbdump/release-group"
_SHA256: Final = r"^[0-9a-f]{64}$"


class ReleaseGroupNativeObservationError(ValueError):
    """Report a failed local source or observation boundary."""


class _FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")


class ReleaseGroupNativeObservationSettings(_FrozenModel):
    """Set an explicit small, order-dependent local sample bound."""

    sample_size: int = Field(default=10_000, ge=1, le=100_000)
    max_archive_bytes: int = Field(default=2 * 1024**3, gt=0)
    max_record_bytes: int = Field(default=2 * 1024**2, gt=0)


class ReleaseGroupSampleReceipt(_FrozenModel):
    """A raw-record identity with bounded native genre and positive tag facts."""

    release_group_mbid: str = Field(pattern=r"^[0-9a-f-]{36}$")
    record_content_sha256: str = Field(pattern=_SHA256)
    record_byte_length: int = Field(gt=0)
    proper_genres: tuple[NativeGenreObservation, ...]
    positive_tags: tuple[NativeTagObservation, ...]


class NativeGenreObservation(_FrozenModel):
    """One proper native genre fact with its exact MusicBrainz identity."""

    genre_mbid: str = Field(pattern=r"^[0-9a-f-]{36}$")
    name: str = Field(min_length=1)
    vote_count: int | None = None


class NativeTagObservation(_FrozenModel):
    """One positive community tag fact with no implied genre identity."""

    name: str = Field(min_length=1)
    vote_count: int = Field(gt=0)


class ReleaseGroupNativeObservationCounters(_FrozenModel):
    """Count parsed raw records and native facets within the fixed sample."""

    raw_records_seen: int = Field(ge=0)
    records_over_limit: int = Field(ge=0)
    malformed_records: int = Field(ge=0)
    sampled_records: int = Field(ge=0)
    sampled_release_groups_with_proper_genres: int = Field(ge=0)
    proper_genre_observation_count: int = Field(ge=0)
    positive_tag_observation_count: int = Field(ge=0)


class ReleaseGroupNativeObservationReport(_FrozenModel):
    """A hash-bound, local-only release-group observation summary."""

    revision: Literal["musicbrainz-release-group-native-observation-v1"] = _REVISION
    export_allowed: Literal[False] = False
    serving_allowed: Literal[False] = False
    artist_membership_propagation_allowed: Literal[False] = False
    source_id: str = Field(min_length=1)
    source_snapshot: str = Field(min_length=1)
    source_archive_sha256: str = Field(pattern=_SHA256)
    source_archive_bytes: int = Field(gt=0)
    source_cache_receipt_sha256: str = Field(pattern=_SHA256)
    source_member_name: Literal["mbdump/release-group"] = _MEMBER
    sample_method: Literal["first_valid_records_in_archive_order"] = (
        "first_valid_records_in_archive_order"
    )
    sample_limit: int = Field(ge=1)
    sampled_member_content_sha256: str = Field(pattern=_SHA256)
    sampled_record_receipts_sha256: str = Field(pattern=_SHA256)
    counters: ReleaseGroupNativeObservationCounters
    samples: tuple[ReleaseGroupSampleReceipt, ...]
    output_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def sample_counts_match(self) -> ReleaseGroupNativeObservationReport:
        """Keep aggregate counts and the sample receipt hash internally consistent."""
        if self.counters.sampled_records != len(self.samples):
            raise ValueError("sampled record count does not match receipts")
        if self.counters.proper_genre_observation_count != sum(
            len(item.proper_genres) for item in self.samples
        ):
            raise ValueError("proper genre count does not match sample receipts")
        if self.counters.positive_tag_observation_count != sum(
            len(item.positive_tags) for item in self.samples
        ):
            raise ValueError("positive tag count does not match sample receipts")
        if self.sampled_record_receipts_sha256 != _sha(self.samples):
            raise ValueError("sample receipt hash does not match sample receipts")
        member_content = tuple(
            (item.record_content_sha256, item.record_byte_length) for item in self.samples
        )
        if self.sampled_member_content_sha256 != _sha(member_content):
            raise ValueError("sampled member content hash does not match sample receipts")
        return self


def _sha(value: object) -> str:
    payload = json.dumps(
        value, default=_json_default, separators=(",", ":"), sort_keys=True
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def _json_default(value: object) -> object:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, tuple):
        return list(value)
    raise TypeError(f"unsupported local receipt value: {type(value)!r}")


def _file_sha256(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def report_sha256(report: ReleaseGroupNativeObservationReport) -> str:
    """Return the deterministic logical hash excluding its self-reference."""
    return _sha(report.model_dump(mode="json", exclude={"output_sha256"}))


def verify_release_group_native_observation(
    report: ReleaseGroupNativeObservationReport,
) -> None:
    """Reject a report whose logical hash or embedded counters no longer replay."""
    if report_sha256(report) != report.output_sha256:
        raise ReleaseGroupNativeObservationError("native observation report hash does not replay")


def build_release_group_native_observation(
    archive_path: Path,
    source: DownloadSource,
    source_cache_receipt: SourceCacheReceipt,
    declared_manifest_sha256: str,
    settings: ReleaseGroupNativeObservationSettings | None = None,
) -> ReleaseGroupNativeObservationReport:
    """Verify one pinned archive and retain a bounded native release-group sample."""
    resolved = settings or ReleaseGroupNativeObservationSettings()
    if source.adapter != "musicbrainz_release_group_json_dump_v1":
        raise ReleaseGroupNativeObservationError("source is not a release-group JSON dump")
    try:
        verify_source_cache_receipt(
            source_cache_receipt, (source,), declared_manifest_sha256=declared_manifest_sha256
        )
    except (RuntimeError, ValueError) as error:
        raise ReleaseGroupNativeObservationError(
            "source cache receipt does not match source"
        ) from error
    archive_sha256, archive_bytes = _file_sha256(archive_path)
    if archive_sha256 != source.verified_sha256() or archive_bytes != source.expected_bytes:
        raise ReleaseGroupNativeObservationError("archive bytes do not match the pinned source")
    if archive_bytes > resolved.max_archive_bytes:
        raise ReleaseGroupNativeObservationError("archive exceeds max_archive_bytes")
    limits = SourceLimits(
        max_archive_bytes=resolved.max_archive_bytes,
        max_record_bytes=resolved.max_record_bytes,
    )
    samples: list[ReleaseGroupSampleReceipt] = []
    counters = dict.fromkeys(ReleaseGroupNativeObservationCounters.model_fields, 0)
    for raw in _iter_raw_archive(archive_path, limits, member_name="release-group"):
        counters["raw_records_seen"] += 1
        if raw.payload is None:
            counters["records_over_limit"] += 1
            continue
        try:
            group = MusicBrainzReleaseGroup.model_validate_json(raw.payload)
        except ValueError:
            counters["malformed_records"] += 1
            continue
        proper_genres = tuple(
            NativeGenreObservation(
                genre_mbid=str(genre.id), name=genre.name, vote_count=genre.count
            )
            for genre in group.genres
        )
        positive_tags = tuple(
            NativeTagObservation(name=tag.name, vote_count=tag.count)
            for tag in group.tags
            if tag.count is not None and tag.count > 0
        )
        sample = ReleaseGroupSampleReceipt(
            release_group_mbid=str(group.id),
            record_content_sha256=raw.sha256,
            record_byte_length=raw.byte_length,
            proper_genres=proper_genres,
            positive_tags=positive_tags,
        )
        samples.append(sample)
        counters["sampled_records"] += 1
        counters["sampled_release_groups_with_proper_genres"] += bool(sample.proper_genres)
        counters["proper_genre_observation_count"] += len(sample.proper_genres)
        counters["positive_tag_observation_count"] += len(sample.positive_tags)
        if len(samples) == resolved.sample_size:
            break
    preliminary = ReleaseGroupNativeObservationReport(
        source_id=source.id,
        source_snapshot=source.snapshot,
        source_archive_sha256=archive_sha256,
        source_archive_bytes=archive_bytes,
        source_cache_receipt_sha256=receipt_sha256(source_cache_receipt),
        sample_limit=resolved.sample_size,
        sampled_member_content_sha256=_sha(
            tuple((item.record_content_sha256, item.record_byte_length) for item in samples)
        ),
        sampled_record_receipts_sha256=_sha(tuple(samples)),
        counters=ReleaseGroupNativeObservationCounters(**counters),
        samples=tuple(samples),
        output_sha256="0" * 64,
    )
    report = preliminary.model_copy(update={"output_sha256": report_sha256(preliminary)})
    verify_release_group_native_observation(report)
    return report
