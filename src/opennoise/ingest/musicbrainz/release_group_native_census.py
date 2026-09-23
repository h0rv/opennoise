"""Aggregate-only census of native MusicBrainz release-group proper genres."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Literal

from pydantic import BaseModel, ConfigDict, Field

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

_REVISION: Final = "musicbrainz-release-group-native-census-v1"
_SEED_COUNT: Final = 6_291
_UNPLACED_COUNT: Final = 3_346
_FULL_CENSUS_RECORD_CAP: Final = 5_000_000
_RECONCILIATION_SHA256: Final = "a9db9fb5d7a8dc1fdeae8e311b7e1d4556d98947a7d600ef4c331a86eba5bef0"
_LAYOUT_SHA256: Final = "e7723b42657451a341e92a9aefa1ced499067e673366b468fd38f84fc86f5972"


class ReleaseGroupNativeCensusError(ValueError):
    """A pinned aggregate-only census boundary failed."""


class _FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")


class NativeGenreCensusRow(_FrozenModel):
    """One aggregate native genre UUID and vote-sign census row."""

    genre_mbid: str = Field(pattern=r"^[0-9a-f-]{36}$")
    name: str = Field(min_length=1)
    observation_count: int = Field(ge=1)
    positive_vote_count: int = Field(ge=0)
    zero_vote_count: int = Field(ge=0)
    negative_vote_count: int = Field(ge=0)
    missing_vote_count: int = Field(ge=0)
    credited_artist_component_count: int = Field(ge=0)


class NamedCount(_FrozenModel):
    """One aggregate category count."""

    name: str = Field(min_length=1)
    count: int = Field(ge=1)


@dataclass(slots=True)
class _GenreAccumulator:
    name: str
    observation_count: int = 0
    positive_vote_count: int = 0
    zero_vote_count: int = 0
    negative_vote_count: int = 0
    missing_vote_count: int = 0
    credited_artist_component_count: int = 0


class ReleaseGroupNativeCensusReport(_FrozenModel):
    """A source-bound aggregate report with no release-group or artist identities."""

    revision: Literal["musicbrainz-release-group-native-census-v1"] = _REVISION
    export_allowed: Literal[False] = False
    serving_allowed: Literal[False] = False
    artist_membership_propagation_allowed: Literal[False] = False
    source_archive_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_archive_bytes: int = Field(gt=0)
    source_cache_receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    seed_reconciliation_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    layout_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    raw_records_seen: int = Field(ge=0)
    records_over_limit: int = Field(ge=0)
    malformed_records: int = Field(ge=0)
    parsed_release_group_count: int = Field(ge=0)
    proper_genre_observation_count: int = Field(ge=0)
    credited_artist_component_count: int = Field(ge=0)
    primary_type_counts: tuple[NamedCount, ...]
    genre_rows: tuple[NativeGenreCensusRow, ...]
    exact_normalized_seed_overlap_count: int = Field(ge=0)
    exact_normalized_unplaced_seed_overlap_count: int = Field(ge=0)
    output_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


def _file_sha(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while block := stream.read(1_048_576):
            digest.update(block)
            size += len(block)
    return digest.hexdigest(), size


def _sha(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()


def report_sha256(report: ReleaseGroupNativeCensusReport) -> str:
    """Hash the report excluding its self-reference."""
    return _sha(report.model_dump(mode="json", exclude={"output_sha256"}))


def _seed_sets(reconciliation_path: Path, layout_path: Path) -> tuple[set[str], set[str]]:
    if _file_sha(reconciliation_path)[0] != _RECONCILIATION_SHA256:
        raise ReleaseGroupNativeCensusError("reconciliation bytes do not match pinned seed scope")
    if _file_sha(layout_path)[0] != _LAYOUT_SHA256:
        raise ReleaseGroupNativeCensusError("layout bytes do not match pinned unplaced scope")
    reconciliation = json.loads(reconciliation_path.read_bytes())
    layout = json.loads(layout_path.read_bytes())
    dispositions = reconciliation.get("dispositions")
    unplaced = layout.get("unplaced")
    if not isinstance(dispositions, list) or not isinstance(unplaced, list):
        raise ReleaseGroupNativeCensusError("seed inputs have no declared seed lists")
    seeds = {
        normalize_label(item["normalized_name"])
        for item in dispositions
        if isinstance(item, dict) and isinstance(item.get("normalized_name"), str)
    }
    by_id = {
        item["source_item_id"]: normalize_label(item["normalized_name"])
        for item in dispositions
        if isinstance(item, dict)
        and isinstance(item.get("source_item_id"), str)
        and isinstance(item.get("normalized_name"), str)
    }
    unplaced_names = {
        by_id[item["seed_id"]]
        for item in unplaced
        if isinstance(item, dict)
        and isinstance(item.get("seed_id"), str)
        and item["seed_id"] in by_id
    }
    if len(seeds) != _SEED_COUNT or len(unplaced_names) != _UNPLACED_COUNT:
        raise ReleaseGroupNativeCensusError(
            "seed inputs do not match the immutable 6291/3346 scope"
        )
    return seeds, unplaced_names


def build_release_group_native_census(  # noqa: C901, PLR0913, PLR0917
    archive_path: Path,
    source: DownloadSource,
    source_cache_receipt: SourceCacheReceipt,
    declared_manifest_sha256: str,
    seed_reconciliation_path: Path,
    layout_path: Path,
) -> ReleaseGroupNativeCensusReport:
    """Stream all records into aggregates; no release-group or artist IDs are retained."""
    try:
        verify_source_cache_receipt(
            source_cache_receipt, (source,), declared_manifest_sha256=declared_manifest_sha256
        )
    except (RuntimeError, ValueError) as error:
        raise ReleaseGroupNativeCensusError("source cache receipt does not match source") from error
    archive_sha, archive_bytes = _file_sha(archive_path)
    if archive_sha != source.verified_sha256() or archive_bytes != source.expected_bytes:
        raise ReleaseGroupNativeCensusError("archive bytes do not match pinned source")
    seed_names, unplaced_names = _seed_sets(seed_reconciliation_path, layout_path)
    genres: dict[str, _GenreAccumulator] = {}
    types: Counter[str] = Counter()
    raw_seen = over_limit = malformed = parsed = observations = credit_components = 0
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
        component_count = len(group.artist_credit)
        credit_components += component_count
        types[group.primary_type or "<missing>"] += 1
        for genre in group.genres:
            observations += 1
            row = genres.setdefault(str(genre.id), _GenreAccumulator(name=genre.name))
            if row.name != genre.name:
                raise ReleaseGroupNativeCensusError("genre UUID has conflicting native names")
            row.observation_count += 1
            row.credited_artist_component_count += component_count
            if genre.count is None:
                row.missing_vote_count += 1
            elif genre.count > 0:
                row.positive_vote_count += 1
            elif genre.count == 0:
                row.zero_vote_count += 1
            else:
                row.negative_vote_count += 1
    rows = tuple(
        NativeGenreCensusRow(
            genre_mbid=key,
            name=value.name,
            observation_count=value.observation_count,
            positive_vote_count=value.positive_vote_count,
            zero_vote_count=value.zero_vote_count,
            negative_vote_count=value.negative_vote_count,
            missing_vote_count=value.missing_vote_count,
            credited_artist_component_count=value.credited_artist_component_count,
        )
        for key, value in sorted(genres.items())
    )
    genre_names = {normalize_label(row.name) for row in rows}
    preliminary = ReleaseGroupNativeCensusReport(
        source_archive_sha256=archive_sha,
        source_archive_bytes=archive_bytes,
        source_cache_receipt_sha256=receipt_sha256(source_cache_receipt),
        seed_reconciliation_sha256=_file_sha(seed_reconciliation_path)[0],
        layout_sha256=_file_sha(layout_path)[0],
        raw_records_seen=raw_seen,
        records_over_limit=over_limit,
        malformed_records=malformed,
        parsed_release_group_count=parsed,
        proper_genre_observation_count=observations,
        credited_artist_component_count=credit_components,
        primary_type_counts=tuple(
            NamedCount(name=name, count=count) for name, count in sorted(types.items())
        ),
        genre_rows=rows,
        exact_normalized_seed_overlap_count=len(genre_names & seed_names),
        exact_normalized_unplaced_seed_overlap_count=len(genre_names & unplaced_names),
        output_sha256="0" * 64,
    )
    return preliminary.model_copy(update={"output_sha256": report_sha256(preliminary)})
