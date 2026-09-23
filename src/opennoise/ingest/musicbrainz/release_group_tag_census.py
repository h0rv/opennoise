"""Aggregate-only census of exact seed-name MusicBrainz release-group tags."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from itertools import pairwise
from typing import TYPE_CHECKING, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from opennoise.ingest.musicbrainz.release_group_native_census import _seed_sets
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

_REVISION: Final = "musicbrainz-release-group-tag-census-v1"
_FULL_CENSUS_RECORD_CAP: Final = 5_000_000
_SUPPORT_THRESHOLDS: Final = (1, 2, 5, 10)


class ReleaseGroupTagCensusError(ValueError):
    """A pinned aggregate-only tag census boundary failed."""


class _FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")


class TagVoteTotals(_FrozenModel):
    """Aggregate vote signs for native MusicBrainz tags."""

    observation_count: int = Field(ge=0)
    positive_vote_count: int = Field(ge=0)
    zero_vote_count: int = Field(ge=0)
    negative_vote_count: int = Field(ge=0)
    missing_vote_count: int = Field(ge=0)

    @model_validator(mode="after")
    def vote_signs_partition_observations(self) -> TagVoteTotals:
        """Require the four sign buckets to partition tag observations."""
        if self.observation_count != (
            self.positive_vote_count
            + self.zero_vote_count
            + self.negative_vote_count
            + self.missing_vote_count
        ):
            raise ValueError("tag vote signs do not partition observations")
        return self

    def does_not_exceed(self, other: TagVoteTotals) -> bool:
        """Return whether each aggregate count is within another aggregate's count."""
        return (
            self.observation_count <= other.observation_count
            and self.positive_vote_count <= other.positive_vote_count
            and self.zero_vote_count <= other.zero_vote_count
            and self.negative_vote_count <= other.negative_vote_count
            and self.missing_vote_count <= other.missing_vote_count
        )


class ExactSeedTagRow(_FrozenModel):
    """One exact normalized seed-name tag aggregate with no entity identities."""

    normalized_seed_name: str = Field(min_length=1)
    vote_totals: TagVoteTotals


class PositiveVoteSupportBin(_FrozenModel):
    """Exact matching seed names meeting one positive-tag vote threshold."""

    minimum_positive_vote_count: Literal[1, 2, 5, 10]
    matching_name_count: int = Field(ge=0)


class ReleaseGroupTagCensusReport(_FrozenModel):
    """A source-bound local tag census that cannot assert membership or placement."""

    revision: Literal["musicbrainz-release-group-tag-census-v1"] = _REVISION
    local_only: Literal[True] = True
    export_allowed: Literal[False] = False
    serving_allowed: Literal[False] = False
    model_input_allowed: Literal[False] = False
    artist_membership_asserted: Literal[False] = False
    placement_asserted: Literal[False] = False
    source_archive_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_archive_bytes: int = Field(gt=0)
    source_cache_receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    seed_reconciliation_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    layout_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    raw_records_seen: int = Field(ge=0)
    records_over_limit: int = Field(ge=0)
    malformed_records: int = Field(ge=0)
    parsed_release_group_count: int = Field(ge=0)
    all_tag_vote_totals: TagVoteTotals
    exact_seed_tag_vote_totals: TagVoteTotals
    exact_seed_tag_rows: tuple[ExactSeedTagRow, ...]
    exact_normalized_seed_overlap_count: int = Field(ge=0)
    exact_normalized_unplaced_seed_overlap_count: int = Field(ge=0)
    seed_positive_vote_support_bins: tuple[PositiveVoteSupportBin, ...]
    unplaced_positive_vote_support_bins: tuple[PositiveVoteSupportBin, ...]
    output_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def exact_rows_replay_declared_overlap(self) -> ReleaseGroupTagCensusReport:
        """Require exact seed aggregates and support bins to be internally consistent."""
        if self.raw_records_seen != (
            self.records_over_limit + self.malformed_records + self.parsed_release_group_count
        ):
            raise ValueError("raw record counts do not reconcile")
        names = {row.normalized_seed_name for row in self.exact_seed_tag_rows}
        if len(names) != len(self.exact_seed_tag_rows):
            raise ValueError("exact seed tag rows repeat a normalized seed name")
        if len(names) != self.exact_normalized_seed_overlap_count:
            raise ValueError("exact seed tag rows do not replay the seed overlap")
        _require_totals_within_all_tags(self)
        if self.exact_normalized_unplaced_seed_overlap_count > len(names):
            raise ValueError("unplaced tag overlap exceeds exact seed tag overlap")
        _require_support_bins(
            self.seed_positive_vote_support_bins, self.exact_normalized_seed_overlap_count
        )
        _require_support_bins(
            self.unplaced_positive_vote_support_bins,
            self.exact_normalized_unplaced_seed_overlap_count,
        )
        return self


@dataclass(slots=True)
class _VoteAccumulator:
    observation_count: int = 0
    positive_vote_count: int = 0
    zero_vote_count: int = 0
    negative_vote_count: int = 0
    missing_vote_count: int = 0

    def add(self, count: int | None) -> None:
        self.observation_count += 1
        if count is None:
            self.missing_vote_count += 1
        elif count > 0:
            self.positive_vote_count += 1
        elif count == 0:
            self.zero_vote_count += 1
        else:
            self.negative_vote_count += 1

    def as_model(self) -> TagVoteTotals:
        return TagVoteTotals(
            observation_count=self.observation_count,
            positive_vote_count=self.positive_vote_count,
            zero_vote_count=self.zero_vote_count,
            negative_vote_count=self.negative_vote_count,
            missing_vote_count=self.missing_vote_count,
        )


def _require_totals_within_all_tags(report: ReleaseGroupTagCensusReport) -> None:
    """Require exact seed rows to replay a subset of all observed tag counts."""
    if _totals(report.exact_seed_tag_rows) != report.exact_seed_tag_vote_totals:
        raise ValueError("exact seed tag rows do not sum to their declared vote totals")
    if not report.exact_seed_tag_vote_totals.does_not_exceed(report.all_tag_vote_totals):
        raise ValueError("exact seed tag totals exceed all native tag totals")


def _require_support_bins(bins: tuple[PositiveVoteSupportBin, ...], scope: int) -> None:
    """Require fixed, bounded, nonincreasing positive-observation support bins."""
    if tuple(row.minimum_positive_vote_count for row in bins) != _SUPPORT_THRESHOLDS:
        raise ValueError("positive-tag support bins do not use fixed thresholds")
    counts = tuple(row.matching_name_count for row in bins)
    if any(count > scope for count in counts):
        raise ValueError("positive-tag support bin exceeds its exact-name overlap")
    if any(left < right for left, right in pairwise(counts)):
        raise ValueError("positive-tag support bins are not nonincreasing")


def _file_sha(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while block := stream.read(1_048_576):
            digest.update(block)
            size += len(block)
    return digest.hexdigest(), size


def report_sha256(report: ReleaseGroupTagCensusReport) -> str:
    """Hash a tag census report without its self-reference."""
    return hashlib.sha256(
        json.dumps(
            report.model_dump(mode="json", exclude={"output_sha256"}),
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
    ).hexdigest()


def build_release_group_tag_census(  # noqa: C901, PLR0913, PLR0917
    archive_path: Path,
    source: DownloadSource,
    source_cache_receipt: SourceCacheReceipt,
    declared_manifest_sha256: str,
    seed_reconciliation_path: Path,
    layout_path: Path,
) -> ReleaseGroupTagCensusReport:
    """Stream all tags into exact-seed aggregates without retaining entity identities."""
    try:
        verify_source_cache_receipt(
            source_cache_receipt, (source,), declared_manifest_sha256=declared_manifest_sha256
        )
    except (RuntimeError, ValueError) as error:
        raise ReleaseGroupTagCensusError("source cache receipt does not match source") from error
    archive_sha, archive_bytes = _file_sha(archive_path)
    if archive_sha != source.verified_sha256() or archive_bytes != source.expected_bytes:
        raise ReleaseGroupTagCensusError("archive bytes do not match pinned source")
    try:
        seed_names, unplaced_names = _seed_sets(seed_reconciliation_path, layout_path)
    except ValueError as error:
        raise ReleaseGroupTagCensusError("seed inputs do not match pinned seed scope") from error
    seed_accumulators: dict[str, _VoteAccumulator] = {}
    all_tags = _VoteAccumulator()
    raw_seen = over_limit = malformed = parsed = 0
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
        for tag in group.tags:
            all_tags.add(tag.count)
            normalized = normalize_label(tag.name)
            if normalized in seed_names:
                seed_accumulators.setdefault(normalized, _VoteAccumulator()).add(tag.count)
    rows = tuple(
        ExactSeedTagRow(normalized_seed_name=name, vote_totals=accumulator.as_model())
        for name, accumulator in sorted(seed_accumulators.items())
    )
    matched_names = frozenset(seed_accumulators)
    unplaced_matches = matched_names & unplaced_names
    preliminary = ReleaseGroupTagCensusReport(
        source_archive_sha256=archive_sha,
        source_archive_bytes=archive_bytes,
        source_cache_receipt_sha256=receipt_sha256(source_cache_receipt),
        seed_reconciliation_sha256=_file_sha(seed_reconciliation_path)[0],
        layout_sha256=_file_sha(layout_path)[0],
        raw_records_seen=raw_seen,
        records_over_limit=over_limit,
        malformed_records=malformed,
        parsed_release_group_count=parsed,
        all_tag_vote_totals=all_tags.as_model(),
        exact_seed_tag_vote_totals=_totals(rows),
        exact_seed_tag_rows=rows,
        exact_normalized_seed_overlap_count=len(matched_names),
        exact_normalized_unplaced_seed_overlap_count=len(unplaced_matches),
        seed_positive_vote_support_bins=_support_bins(matched_names, seed_accumulators),
        unplaced_positive_vote_support_bins=_support_bins(unplaced_matches, seed_accumulators),
        output_sha256="0" * 64,
    )
    report = preliminary.model_copy(update={"output_sha256": report_sha256(preliminary)})
    try:
        validated = ReleaseGroupTagCensusReport.model_validate_json(report.model_dump_json())
    except ValueError as error:
        raise ReleaseGroupTagCensusError("completed tag census report does not validate") from error
    if validated.output_sha256 != report_sha256(validated):
        raise ReleaseGroupTagCensusError("completed tag census report hash does not replay")
    return validated


def _totals(rows: tuple[ExactSeedTagRow, ...]) -> TagVoteTotals:
    return TagVoteTotals(
        observation_count=sum(row.vote_totals.observation_count for row in rows),
        positive_vote_count=sum(row.vote_totals.positive_vote_count for row in rows),
        zero_vote_count=sum(row.vote_totals.zero_vote_count for row in rows),
        negative_vote_count=sum(row.vote_totals.negative_vote_count for row in rows),
        missing_vote_count=sum(row.vote_totals.missing_vote_count for row in rows),
    )


def _support_bins(
    names: frozenset[str], accumulators: dict[str, _VoteAccumulator]
) -> tuple[PositiveVoteSupportBin, ...]:
    return tuple(
        PositiveVoteSupportBin(
            minimum_positive_vote_count=threshold,
            matching_name_count=sum(
                accumulators[name].positive_vote_count >= threshold for name in names
            ),
        )
        for threshold in _SUPPORT_THRESHOLDS
    )
