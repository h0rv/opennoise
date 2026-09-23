"""Aggregate local decision report for native release-group genre coverage."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from opennoise.ingest.musicbrainz.entity_genre_observation import write_local_report_once
from opennoise.ingest.musicbrainz.release_group_native_census import (
    NativeGenreCensusRow,
    ReleaseGroupNativeCensusReport,
)
from opennoise.ingest.musicbrainz.release_group_native_census import (
    report_sha256 as census_report_sha256,
)
from opennoise.taxonomy.seeds.universe import normalize_label

if TYPE_CHECKING:
    from pathlib import Path

_REVISION: Final = "musicbrainz-release-group-native-census-decision-v1"
_PINNED_CENSUS_OUTPUT_SHA256: Final = (
    "f110353535321e9f76da91a383e957753a514422142d5c6a2dbe7e6d5592d706"
)
_PINNED_RECONCILIATION_SHA256: Final = (
    "a9db9fb5d7a8dc1fdeae8e311b7e1d4556d98947a7d600ef4c331a86eba5bef0"
)
_PINNED_LAYOUT_SHA256: Final = "e7723b42657451a341e92a9aefa1ced499067e673366b468fd38f84fc86f5972"
_SEED_COUNT: Final = 6_291
_UNPLACED_COUNT: Final = 3_346
_SUPPORT_THRESHOLDS: Final = (1, 2, 5, 10)
_TOP_UNPLACED_LIMIT: Final = 20


class ReleaseGroupNativeCensusDecisionError(ValueError):
    """A pinned aggregate census decision input is invalid."""


class _FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")


class _SeedDisposition(_FrozenModel):
    model_config = ConfigDict(frozen=True, strict=True, extra="ignore")

    source_item_id: str = Field(min_length=1)
    normalized_name: str = Field(min_length=1)


class _SeedReconciliation(_FrozenModel):
    model_config = ConfigDict(frozen=True, strict=True, extra="ignore")

    dispositions: tuple[_SeedDisposition, ...]


class _UnplacedSeed(_FrozenModel):
    model_config = ConfigDict(frozen=True, strict=True, extra="ignore")

    seed_id: str = Field(min_length=1)


class _Layout(_FrozenModel):
    model_config = ConfigDict(frozen=True, strict=True, extra="ignore")

    unplaced: tuple[_UnplacedSeed, ...]


class NativeGenreVoteTotals(_FrozenModel):
    """Vote signs and aggregate artist-credit components for one name scope."""

    observation_count: int = Field(ge=0)
    positive_vote_count: int = Field(ge=0)
    zero_vote_count: int = Field(ge=0)
    negative_vote_count: int = Field(ge=0)
    missing_vote_count: int = Field(ge=0)
    credited_artist_component_count: int = Field(ge=0)

    @model_validator(mode="after")
    def _require_vote_partition(self) -> NativeGenreVoteTotals:
        if self.observation_count != (
            self.positive_vote_count
            + self.zero_vote_count
            + self.negative_vote_count
            + self.missing_vote_count
        ):
            raise ValueError("vote signs do not partition native genre observations")
        return self


class PositiveVoteSupportBin(_FrozenModel):
    """The number of matching normalized seed names at a fixed positive-vote floor."""

    minimum_positive_vote_count: Literal[1, 2, 5, 10]
    matching_name_count: int = Field(ge=0)


class NativeGenreCoverageScope(_FrozenModel):
    """Aggregate support for exact normalized seed-name matches."""

    exact_normalized_name_count: int = Field(ge=0)
    names_with_credited_artist_components_count: int = Field(ge=0)
    vote_totals: NativeGenreVoteTotals
    positive_vote_support_bins: tuple[PositiveVoteSupportBin, ...]

    @model_validator(mode="after")
    def _require_scoped_counts(self) -> NativeGenreCoverageScope:
        if self.names_with_credited_artist_components_count > self.exact_normalized_name_count:
            raise ValueError("credited-artist component coverage exceeds matching name count")
        if tuple(item.minimum_positive_vote_count for item in self.positive_vote_support_bins) != (
            1,
            2,
            5,
            10,
        ):
            raise ValueError("positive-vote support bins do not use the fixed thresholds")
        if any(
            item.matching_name_count > self.exact_normalized_name_count
            for item in self.positive_vote_support_bins
        ):
            raise ValueError("positive-vote support bin exceeds matching name count")
        return self


class TopUnplacedNativeGenreSupport(_FrozenModel):
    """One seed-name aggregate, with no release-group or artist identity."""

    normalized_seed_name: str = Field(min_length=1)
    vote_totals: NativeGenreVoteTotals


class ReleaseGroupNativeCensusDecisionReport(_FrozenModel):
    """Pinned local-only assessment of native release-group genre coverage."""

    revision: Literal["musicbrainz-release-group-native-census-decision-v1"] = _REVISION
    local_only: Literal[True] = True
    export_allowed: Literal[False] = False
    serving_allowed: Literal[False] = False
    model_input_allowed: Literal[False] = False
    artist_membership_asserted: Literal[False] = False
    placement_asserted: Literal[False] = False
    source_census_output_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    seed_reconciliation_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    layout_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    seed_coverage: NativeGenreCoverageScope
    unplaced_coverage: NativeGenreCoverageScope
    top_supported_unplaced_names: tuple[TopUnplacedNativeGenreSupport, ...]
    output_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _require_pinned_scope(self) -> ReleaseGroupNativeCensusDecisionReport:
        if self.source_census_output_sha256 != _PINNED_CENSUS_OUTPUT_SHA256:
            raise ValueError("decision report does not use the completed census")
        if self.seed_reconciliation_sha256 != _PINNED_RECONCILIATION_SHA256:
            raise ValueError("decision report does not use the pinned reconciliation")
        if self.layout_sha256 != _PINNED_LAYOUT_SHA256:
            raise ValueError("decision report does not use the pinned layout")
        if (
            self.unplaced_coverage.exact_normalized_name_count
            > self.seed_coverage.exact_normalized_name_count
        ):
            raise ValueError("unplaced coverage exceeds all-seed coverage")
        if len(self.top_supported_unplaced_names) > _TOP_UNPLACED_LIMIT:
            raise ValueError("top unplaced support list exceeds its fixed cap")
        return self


@dataclass(slots=True)
class _Totals:
    observation_count: int = 0
    positive_vote_count: int = 0
    zero_vote_count: int = 0
    negative_vote_count: int = 0
    missing_vote_count: int = 0
    credited_artist_component_count: int = 0

    def add(self, other: _Totals) -> None:
        self.observation_count += other.observation_count
        self.positive_vote_count += other.positive_vote_count
        self.zero_vote_count += other.zero_vote_count
        self.negative_vote_count += other.negative_vote_count
        self.missing_vote_count += other.missing_vote_count
        self.credited_artist_component_count += other.credited_artist_component_count

    def as_model(self) -> NativeGenreVoteTotals:
        return NativeGenreVoteTotals(
            observation_count=self.observation_count,
            positive_vote_count=self.positive_vote_count,
            zero_vote_count=self.zero_vote_count,
            negative_vote_count=self.negative_vote_count,
            missing_vote_count=self.missing_vote_count,
            credited_artist_component_count=self.credited_artist_component_count,
        )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1_048_576):
            digest.update(block)
    return digest.hexdigest()


def _totals_for_row(row: NativeGenreCensusRow) -> _Totals:
    return _Totals(
        observation_count=row.observation_count,
        positive_vote_count=row.positive_vote_count,
        zero_vote_count=row.zero_vote_count,
        negative_vote_count=row.negative_vote_count,
        missing_vote_count=row.missing_vote_count,
        credited_artist_component_count=row.credited_artist_component_count,
    )


def report_sha256(report: ReleaseGroupNativeCensusDecisionReport) -> str:
    """Hash a decision report without its self-reference."""
    return hashlib.sha256(
        json.dumps(
            report.model_dump(mode="json", exclude={"output_sha256"}),
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
    ).hexdigest()


def verify_release_group_native_census_decision(
    report: ReleaseGroupNativeCensusDecisionReport,
) -> None:
    """Fail closed if a persisted decision report does not replay its hash."""
    try:
        ReleaseGroupNativeCensusDecisionReport.model_validate(report.model_dump())
    except ValueError as error:
        raise ReleaseGroupNativeCensusDecisionError(
            "decision report does not meet its declared invariants"
        ) from error
    if report.output_sha256 != report_sha256(report):
        raise ReleaseGroupNativeCensusDecisionError("decision report hash does not replay")


def _read_seed_scopes(
    reconciliation_path: Path, layout_path: Path
) -> tuple[frozenset[str], frozenset[str]]:
    reconciliation_sha256 = _sha256_file(reconciliation_path)
    layout_sha256 = _sha256_file(layout_path)
    if reconciliation_sha256 != _PINNED_RECONCILIATION_SHA256:
        raise ReleaseGroupNativeCensusDecisionError(
            "reconciliation bytes do not match pinned scope"
        )
    if layout_sha256 != _PINNED_LAYOUT_SHA256:
        raise ReleaseGroupNativeCensusDecisionError("layout bytes do not match pinned scope")
    try:
        reconciliation = _SeedReconciliation.model_validate_json(reconciliation_path.read_bytes())
        layout = _Layout.model_validate_json(layout_path.read_bytes())
    except ValueError as error:
        raise ReleaseGroupNativeCensusDecisionError(
            "seed inputs do not match their declared shape"
        ) from error
    names_by_id = {
        row.source_item_id: normalize_label(row.normalized_name)
        for row in reconciliation.dispositions
    }
    seed_names = frozenset(names_by_id.values())
    unplaced_ids = {row.seed_id for row in layout.unplaced}
    if len(names_by_id) != len(reconciliation.dispositions):
        raise ReleaseGroupNativeCensusDecisionError("reconciliation contains repeated seed IDs")
    if len(unplaced_ids) != len(layout.unplaced):
        raise ReleaseGroupNativeCensusDecisionError("layout contains repeated unplaced seed IDs")
    if not unplaced_ids <= names_by_id.keys():
        raise ReleaseGroupNativeCensusDecisionError("layout refers to an unknown seed ID")
    unplaced_names = frozenset(names_by_id[seed_id] for seed_id in unplaced_ids)
    if len(seed_names) != _SEED_COUNT or len(unplaced_names) != _UNPLACED_COUNT:
        raise ReleaseGroupNativeCensusDecisionError(
            "seed inputs do not retain the pinned 6291/3346 scope"
        )
    return seed_names, unplaced_names


def _scope(
    matching_names: frozenset[str], totals_by_name: dict[str, _Totals]
) -> NativeGenreCoverageScope:
    scoped = [totals_by_name[name] for name in sorted(matching_names)]
    totals = _Totals()
    for item in scoped:
        totals.add(item)
    return NativeGenreCoverageScope(
        exact_normalized_name_count=len(scoped),
        names_with_credited_artist_components_count=sum(
            item.credited_artist_component_count > 0 for item in scoped
        ),
        vote_totals=totals.as_model(),
        positive_vote_support_bins=tuple(
            PositiveVoteSupportBin(
                minimum_positive_vote_count=threshold,
                matching_name_count=sum(item.positive_vote_count >= threshold for item in scoped),
            )
            for threshold in _SUPPORT_THRESHOLDS
        ),
    )


def build_release_group_native_census_decision(
    census_path: Path,
    seed_reconciliation_path: Path,
    layout_path: Path,
) -> ReleaseGroupNativeCensusDecisionReport:
    """Summarize only aggregate native genre coverage from the completed census."""
    try:
        census = ReleaseGroupNativeCensusReport.model_validate_json(census_path.read_bytes())
    except ValueError as error:
        raise ReleaseGroupNativeCensusDecisionError(
            "census report does not match its declared shape"
        ) from error
    if census.output_sha256 != census_report_sha256(census):
        raise ReleaseGroupNativeCensusDecisionError("census report hash does not replay")
    if census.output_sha256 != _PINNED_CENSUS_OUTPUT_SHA256:
        raise ReleaseGroupNativeCensusDecisionError(
            "census report is not the completed pinned census"
        )
    if census.seed_reconciliation_sha256 != _PINNED_RECONCILIATION_SHA256:
        raise ReleaseGroupNativeCensusDecisionError(
            "census report does not use the pinned reconciliation"
        )
    if census.layout_sha256 != _PINNED_LAYOUT_SHA256:
        raise ReleaseGroupNativeCensusDecisionError("census report does not use the pinned layout")
    seed_names, unplaced_names = _read_seed_scopes(seed_reconciliation_path, layout_path)
    totals_by_name: dict[str, _Totals] = defaultdict(_Totals)
    for row in census.genre_rows:
        totals_by_name[normalize_label(row.name)].add(_totals_for_row(row))
    native_names = frozenset(totals_by_name)
    seed_matches = native_names & seed_names
    unplaced_matches = native_names & unplaced_names
    if len(seed_matches) != census.exact_normalized_seed_overlap_count:
        raise ReleaseGroupNativeCensusDecisionError("census seed overlap does not replay")
    if len(unplaced_matches) != census.exact_normalized_unplaced_seed_overlap_count:
        raise ReleaseGroupNativeCensusDecisionError("census unplaced overlap does not replay")
    top_names = sorted(
        unplaced_matches,
        key=lambda name: (
            -totals_by_name[name].positive_vote_count,
            -totals_by_name[name].observation_count,
            name,
        ),
    )[:_TOP_UNPLACED_LIMIT]
    preliminary = ReleaseGroupNativeCensusDecisionReport.model_construct(
        source_census_output_sha256=census.output_sha256,
        seed_reconciliation_sha256=_PINNED_RECONCILIATION_SHA256,
        layout_sha256=_PINNED_LAYOUT_SHA256,
        seed_coverage=_scope(seed_matches, totals_by_name),
        unplaced_coverage=_scope(unplaced_matches, totals_by_name),
        top_supported_unplaced_names=tuple(
            TopUnplacedNativeGenreSupport(
                normalized_seed_name=name,
                vote_totals=totals_by_name[name].as_model(),
            )
            for name in top_names
        ),
        output_sha256="0" * 64,
    )
    payload = preliminary.model_dump()
    payload["output_sha256"] = report_sha256(preliminary)
    report = ReleaseGroupNativeCensusDecisionReport.model_validate(payload)
    verify_release_group_native_census_decision(report)
    return report


def write_release_group_native_census_decision_once(
    *, cache_root: Path, output: Path, report: ReleaseGroupNativeCensusDecisionReport
) -> None:
    """Write one verified local decision report without replacing a prior report."""
    verify_release_group_native_census_decision(report)
    write_local_report_once(
        cache_root=cache_root,
        output=output,
        payload=(report.model_dump_json() + "\n").encode(),
    )
