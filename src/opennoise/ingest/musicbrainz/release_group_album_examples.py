"""Retain bounded local album examples from native release-group genre observations.

The rows preserve release-group facts and album credits as source context. They do
not assert artist membership, editorial status, or a representative album.
"""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from opennoise.ingest.musicbrainz.release_group_native_census import _file_sha
from opennoise.models.pipeline import SourceLimits
from opennoise.pipeline.source_cache import (
    SourceCacheReceipt,
    receipt_sha256,
    verify_source_cache_receipt,
)
from opennoise.sources.musicbrainz import MusicBrainzReleaseGroup, _iter_raw_archive
from opennoise.taxonomy.seeds.universe import normalize_label

if TYPE_CHECKING:
    from pathlib import Path

    from opennoise.models.sources import DownloadSource

_REVISION: Final = "musicbrainz-release-group-album-examples-v1"
_SEED_COUNT: Final = 6_291
_RECONCILIATION_SHA256: Final = "a9db9fb5d7a8dc1fdeae8e311b7e1d4556d98947a7d600ef4c331a86eba5bef0"
_FULL_CENSUS_RECORD_CAP: Final = 5_000_000
_MAX_EXAMPLES_PER_SEED: Final = 20


class ReleaseGroupAlbumExamplesError(ValueError):
    """The local release-group Album example candidate boundary failed."""


class _FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")


class AlbumCreditArtist(_FrozenModel):
    """One source-ordered release-group album credit component."""

    artist_mbid: str = Field(pattern=r"^[0-9a-f-]{36}$")


class AlbumExample(_FrozenModel):
    """One positive native proper-genre observation on an Album release group."""

    release_group_mbid: str = Field(pattern=r"^[0-9a-f-]{36}$")
    title: str = Field(min_length=1)
    first_release_date: str | None
    secondary_types: tuple[str, ...]
    credited_artist_mbids: tuple[AlbumCreditArtist, ...]
    record_content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_type: Literal["musicbrainz_release_group_native_proper_genre"] = (
        "musicbrainz_release_group_native_proper_genre"
    )
    genre_mbid: str = Field(pattern=r"^[0-9a-f-]{36}$")
    genre_name: str = Field(min_length=1)
    genre_vote_count: int = Field(gt=0)


class SeedAlbumExamples(_FrozenModel):
    """A bounded ordered list of Album examples for one exact seed identity."""

    seed_source_item_id: str = Field(min_length=1)
    normalized_seed_name: str = Field(min_length=1)
    examples: tuple[AlbumExample, ...]


class ReleaseGroupAlbumExamplesReport(_FrozenModel):
    """A source-bound local report that deliberately stops short of membership claims."""

    revision: Literal["musicbrainz-release-group-album-examples-v1"] = _REVISION
    local_only: Literal[True] = True
    export_allowed: Literal[False] = False
    serving_allowed: Literal[False] = False
    model_input_allowed: Literal[False] = False
    artist_membership_asserted: Literal[False] = False
    editorial_or_quintessential_status_asserted: Literal[False] = False
    source_archive_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_archive_bytes: int = Field(gt=0)
    source_cache_receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    seed_reconciliation_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    seed_count: int = Field(ge=1)
    examples_per_seed_limit: int = Field(ge=1, le=20)
    raw_records_seen: int = Field(ge=0)
    records_over_limit: int = Field(ge=0)
    malformed_records: int = Field(ge=0)
    parsed_release_group_count: int = Field(ge=0)
    album_release_group_count: int = Field(ge=0)
    positive_native_proper_genre_observation_count: int = Field(ge=0)
    exact_seed_positive_observation_count: int = Field(ge=0)
    seed_rows: tuple[SeedAlbumExamples, ...]
    output_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def ordered_bounded_exact_examples(self) -> ReleaseGroupAlbumExamplesReport:
        """Require one deterministically ordered retained example per release group."""
        _validate_report_counts(self)
        names = tuple(row.normalized_seed_name for row in self.seed_rows)
        if names != tuple(sorted(names)) or len(names) != len(set(names)):
            raise ValueError("seed rows must be uniquely sorted by normalized seed name")
        if any(len(row.examples) > self.examples_per_seed_limit for row in self.seed_rows):
            raise ValueError("seed examples exceed the configured limit")
        for row in self.seed_rows:
            if not row.examples:
                raise ValueError("seed rows must contain at least one example")
            if len({item.release_group_mbid for item in row.examples}) != len(row.examples):
                raise ValueError("seed examples repeat a release group")
            expected = tuple(
                sorted(
                    row.examples,
                    key=lambda item: (-item.genre_vote_count, item.release_group_mbid),
                )
            )
            if row.examples != expected:
                raise ValueError("seed examples are not in deterministic vote and MBID order")
        return self


def _validate_report_counts(report: ReleaseGroupAlbumExamplesReport) -> None:
    if report.raw_records_seen != (
        report.records_over_limit + report.malformed_records + report.parsed_release_group_count
    ):
        raise ValueError("raw record counts do not reconcile")
    if report.album_release_group_count > report.parsed_release_group_count:
        raise ValueError("Album count exceeds parsed release-group count")
    if report.exact_seed_positive_observation_count > (
        report.positive_native_proper_genre_observation_count
    ):
        raise ValueError("exact seed observations exceed positive observations")
    if len(report.seed_rows) > report.seed_count:
        raise ValueError("seed rows exceed the exact seed scope")


def report_sha256(report: ReleaseGroupAlbumExamplesReport) -> str:
    """Return the deterministic logical hash excluding its self-reference."""
    payload = report.model_dump(mode="json", exclude={"output_sha256"})
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()


def verify_release_group_album_examples(report: ReleaseGroupAlbumExamplesReport) -> None:
    """Reject an altered local report."""
    try:
        report = ReleaseGroupAlbumExamplesReport.model_validate_json(report.model_dump_json())
    except ValueError as error:
        raise ReleaseGroupAlbumExamplesError(
            "album examples report schema does not replay"
        ) from error
    if report_sha256(report) != report.output_sha256:
        raise ReleaseGroupAlbumExamplesError("album examples report hash does not replay")


def _exact_seed_map(path: Path) -> dict[str, str]:
    if _file_sha(path)[0] != _RECONCILIATION_SHA256:
        raise ReleaseGroupAlbumExamplesError("reconciliation bytes do not match pinned seed scope")
    raw = json.loads(path.read_bytes())
    dispositions = raw.get("dispositions")
    if not isinstance(dispositions, list):
        raise ReleaseGroupAlbumExamplesError("reconciliation has no declared seed list")
    result: dict[str, str] = {}
    for item in dispositions:
        if not isinstance(item, dict):
            raise ReleaseGroupAlbumExamplesError("reconciliation disposition is invalid")
        seed_id, name = item.get("source_item_id"), item.get("normalized_name")
        if not isinstance(seed_id, str) or not isinstance(name, str):
            raise ReleaseGroupAlbumExamplesError(
                "reconciliation disposition lacks an exact seed identity"
            )
        normalized = normalize_label(name)
        if normalized in result:
            raise ReleaseGroupAlbumExamplesError("duplicate normalized seed names cannot be joined")
        result[normalized] = seed_id
    if len(result) != _SEED_COUNT:
        raise ReleaseGroupAlbumExamplesError(
            "reconciliation does not match the immutable 6291 seed scope"
        )
    return result


def build_release_group_album_examples(  # noqa: C901, PLR0913
    archive_path: Path,
    source: DownloadSource,
    source_cache_receipt: SourceCacheReceipt,
    declared_manifest_sha256: str,
    seed_reconciliation_path: Path,
    *,
    examples_per_seed_limit: int = 5,
) -> ReleaseGroupAlbumExamplesReport:
    """Stream the pinned archive and select only exact positive proper-genre Album contexts."""
    if not 1 <= examples_per_seed_limit <= _MAX_EXAMPLES_PER_SEED:
        raise ReleaseGroupAlbumExamplesError(
            f"examples_per_seed_limit must be from 1 to {_MAX_EXAMPLES_PER_SEED}"
        )
    try:
        verify_source_cache_receipt(
            source_cache_receipt, (source,), declared_manifest_sha256=declared_manifest_sha256
        )
    except (RuntimeError, ValueError) as error:
        raise ReleaseGroupAlbumExamplesError(
            "source cache receipt does not match source"
        ) from error
    archive_sha, archive_bytes = _file_sha(archive_path)
    if archive_sha != source.verified_sha256() or archive_bytes != source.expected_bytes:
        raise ReleaseGroupAlbumExamplesError("archive bytes do not match the pinned source")
    seed_map = _exact_seed_map(seed_reconciliation_path)
    selected: dict[str, dict[str, AlbumExample]] = {}
    raw_seen = over_limit = malformed = parsed = albums = positives = matched = 0
    for raw in _iter_raw_archive(
        archive_path,
        SourceLimits(
            max_archive_bytes=archive_bytes,
            max_record_bytes=2 * 1024**2,
            max_records=_FULL_CENSUS_RECORD_CAP,
        ),
        member_name="release-group",
    ):
        raw_seen += 1
        if raw.payload is None:
            over_limit += 1
            continue
        try:
            group = MusicBrainzReleaseGroup.model_validate_json(raw.payload)
        except ValueError:
            malformed += 1
            continue
        parsed += 1
        if group.primary_type != "Album":
            continue
        albums += 1
        artist_credits = tuple(
            AlbumCreditArtist(artist_mbid=str(item.artist.id)) for item in group.artist_credit
        )
        for genre in group.genres:
            if genre.count is None or genre.count <= 0:
                continue
            positives += 1
            normalized = normalize_label(genre.name)
            if normalized not in seed_map:
                continue
            matched += 1
            example = AlbumExample(
                release_group_mbid=str(group.id),
                title=group.title,
                first_release_date=group.first_release_date,
                secondary_types=group.secondary_types,
                credited_artist_mbids=artist_credits,
                record_content_sha256=raw.sha256,
                genre_mbid=str(genre.id),
                genre_name=genre.name,
                genre_vote_count=genre.count,
            )
            candidates = selected.setdefault(normalized, {})
            prior = candidates.get(example.release_group_mbid)
            if prior is None or (-example.genre_vote_count, example.genre_mbid) < (
                -prior.genre_vote_count,
                prior.genre_mbid,
            ):
                candidates[example.release_group_mbid] = example
            if len(candidates) > examples_per_seed_limit:
                discarded = max(
                    candidates.values(),
                    key=lambda item: (-item.genre_vote_count, item.release_group_mbid),
                )
                del candidates[discarded.release_group_mbid]
    rows = tuple(
        SeedAlbumExamples(
            seed_source_item_id=seed_map[name],
            normalized_seed_name=name,
            examples=tuple(
                sorted(
                    examples.values(),
                    key=lambda item: (-item.genre_vote_count, item.release_group_mbid),
                )
            ),
        )
        for name, examples in sorted(selected.items())
    )
    preliminary = ReleaseGroupAlbumExamplesReport(
        source_archive_sha256=archive_sha,
        source_archive_bytes=archive_bytes,
        source_cache_receipt_sha256=receipt_sha256(source_cache_receipt),
        seed_reconciliation_sha256=_file_sha(seed_reconciliation_path)[0],
        seed_count=len(seed_map),
        examples_per_seed_limit=examples_per_seed_limit,
        raw_records_seen=raw_seen,
        records_over_limit=over_limit,
        malformed_records=malformed,
        parsed_release_group_count=parsed,
        album_release_group_count=albums,
        positive_native_proper_genre_observation_count=positives,
        exact_seed_positive_observation_count=matched,
        seed_rows=rows,
        output_sha256="0" * 64,
    )
    report = preliminary.model_copy(update={"output_sha256": report_sha256(preliminary)})
    verify_release_group_album_examples(report)
    return report
