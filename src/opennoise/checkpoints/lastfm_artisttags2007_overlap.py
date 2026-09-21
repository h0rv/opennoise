"""Local, positive-only overlap evaluation for the archived Last.fm tag snapshot."""

from __future__ import annotations

import hashlib
import tarfile
from collections import Counter
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Literal

from pydantic import Field, model_validator

from opennoise.common import sha256_file, sha256_json
from opennoise.deployment.static_discovery import StaticDiscoveryPayload
from opennoise.models import FrozenModel
from opennoise.types import Sha256  # noqa: TC001  # Pydantic resolves aliases at runtime.

_REVISION: Final = "lastfm-artisttags2007-static-overlap-v1"
_ARCHIVE_SHA256: Final = "b2b78000279c00c49ad6c0e764203dfbe4deb18a8012c1f43b7fb64933741c4f"
_DATA_MEMBER: Final = "Lastfm-ArtistTags2007/ArtistTags.dat"
_SEPARATOR: Final = b"<sep>"
_MBID_LENGTH: Final = 36
_ROW_FIELD_COUNT: Final = 4

if TYPE_CHECKING:
    from pathlib import Path


@dataclass(frozen=True, slots=True)
class _StaticTargets:
    pairs: set[tuple[str, str]]
    artists: set[str]
    names: set[str]


class LastFmArtistTags2007OverlapSettings(FrozenModel):
    """Fixed local bounds for parsing and deterministic held-out accounting."""

    revision: Literal["lastfm-artisttags2007-static-overlap-settings-v1"] = (
        "lastfm-artisttags2007-static-overlap-settings-v1"
    )
    maximum_rows: int = Field(default=1_000_000, ge=1, le=2_000_000)
    heldout_modulus: int = Field(default=5, ge=2, le=100)
    heldout_remainder: int = Field(default=0, ge=0, le=99)
    raw_count_thresholds: tuple[int, ...] = (1, 2, 5, 10)

    @model_validator(mode="after")
    def _valid_thresholds(self) -> LastFmArtistTags2007OverlapSettings:
        if self.heldout_remainder >= self.heldout_modulus:
            raise ValueError("held-out remainder must be smaller than held-out modulus")
        if not self.raw_count_thresholds or any(value < 1 for value in self.raw_count_thresholds):
            raise ValueError("raw count thresholds must be positive")
        if tuple(sorted(set(self.raw_count_thresholds))) != self.raw_count_thresholds:
            raise ValueError("raw count thresholds must be unique and sorted")
        return self


class LastFmArtistTags2007ParseCoverage(FrozenModel):
    """Account for every physical row from the archive data member."""

    data_member: Literal["Lastfm-ArtistTags2007/ArtistTags.dat"] = _DATA_MEMBER
    total_row_count: int = Field(ge=0)
    accepted_positive_row_count: int = Field(ge=0)
    malformed_row_count: int = Field(ge=0)
    invalid_utf8_row_count: int = Field(ge=0)
    invalid_mbid_row_count: int = Field(ge=0)
    invalid_count_row_count: int = Field(ge=0)
    nonpositive_count_row_count: int = Field(ge=0)
    duplicate_artist_tag_row_count: int = Field(ge=0)

    @model_validator(mode="after")
    def _partition(self) -> LastFmArtistTags2007ParseCoverage:
        if self.total_row_count != (
            self.accepted_positive_row_count
            + self.malformed_row_count
            + self.invalid_utf8_row_count
            + self.invalid_mbid_row_count
            + self.invalid_count_row_count
            + self.nonpositive_count_row_count
            + self.duplicate_artist_tag_row_count
        ):
            raise ValueError("parse coverage must partition physical archive rows")
        return self


class LastFmArtistTags2007ThresholdCoverage(FrozenModel):
    """Positive-only held-out overlap counts for one raw-tag-count threshold."""

    raw_count_threshold: int = Field(ge=1)
    source_positive_pair_count: int = Field(ge=0)
    heldout_positive_pair_count: int = Field(ge=0)
    heldout_artist_id_matched_positive_pair_count: int = Field(ge=0)
    heldout_exact_genre_name_matched_positive_pair_count: int = Field(ge=0)
    heldout_scoreable_positive_pair_count: int = Field(ge=0)
    heldout_exact_pair_overlap_count: int = Field(ge=0)
    global_positive_overlap_recall: float = Field(ge=0.0, le=1.0)
    scoreable_positive_overlap_recall: float = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _valid_counts(self) -> LastFmArtistTags2007ThresholdCoverage:
        if not (
            self.heldout_exact_pair_overlap_count
            <= self.heldout_scoreable_positive_pair_count
            <= self.heldout_artist_id_matched_positive_pair_count
            <= self.heldout_positive_pair_count
        ):
            raise ValueError("held-out overlap counts have an invalid containment order")
        if (
            self.heldout_exact_genre_name_matched_positive_pair_count
            > self.heldout_positive_pair_count
        ):
            raise ValueError("genre-name match count exceeds held-out positives")
        expected_global = (
            self.heldout_exact_pair_overlap_count / self.heldout_positive_pair_count
            if self.heldout_positive_pair_count
            else 0.0
        )
        expected_scoreable = (
            self.heldout_exact_pair_overlap_count / self.heldout_scoreable_positive_pair_count
            if self.heldout_scoreable_positive_pair_count
            else 0.0
        )
        if self.global_positive_overlap_recall != expected_global:
            raise ValueError("global positive overlap recall does not replay")
        if self.scoreable_positive_overlap_recall != expected_scoreable:
            raise ValueError("scoreable positive overlap recall does not replay")
        return self


class LastFmArtistTags2007OverlapReport(FrozenModel):
    """A local research report that does not alter inputs or public output."""

    revision: Literal["lastfm-artisttags2007-static-overlap-v1"] = _REVISION
    evaluation_scope: Literal["local_research_only_positive_only_heldout_overlap"] = (
        "local_research_only_positive_only_heldout_overlap"
    )
    archive_sha256: Sha256
    archive_byte_count: int = Field(ge=1)
    static_discovery_sha256: Sha256
    static_discovery_byte_count: int = Field(ge=1)
    static_discovery_revision: Literal["static-direct-discovery-v1"]
    settings: LastFmArtistTags2007OverlapSettings
    parse_coverage: LastFmArtistTags2007ParseCoverage
    static_artist_mbid_count: int = Field(ge=0)
    static_genre_name_count: int = Field(ge=0)
    static_membership_pair_count: int = Field(ge=0)
    thresholds: tuple[LastFmArtistTags2007ThresholdCoverage, ...]
    exact_artist_matching_only: Literal[True] = True
    exact_genre_name_matching_only: Literal[True] = True
    missing_source_tags_are_negatives: Literal[False] = False
    archive_used_for_training: Literal[False] = False
    audio_used: Literal[False] = False
    public_database_used: Literal[False] = False
    public_output_mutated: Literal[False] = False
    output_sha256: Sha256

    @model_validator(mode="after")
    def _complete(self) -> LastFmArtistTags2007OverlapReport:
        if (
            tuple(item.raw_count_threshold for item in self.thresholds)
            != self.settings.raw_count_thresholds
        ):
            raise ValueError("threshold coverage must match configured thresholds")
        return self


def build_lastfm_artisttags2007_static_overlap(
    archive: Path,
    static_discovery: Path,
    settings: LastFmArtistTags2007OverlapSettings | None = None,
) -> LastFmArtistTags2007OverlapReport:
    """Measure literal MBID/tag overlap without training, negatives, or database input."""
    resolved_settings = settings or LastFmArtistTags2007OverlapSettings()
    archive_sha256, archive_byte_count = sha256_file(archive)
    if archive_sha256 != _ARCHIVE_SHA256:
        raise ValueError("Last.fm ArtistTags2007 archive hash does not match the pinned source")
    static_sha256, static_byte_count = sha256_file(static_discovery)
    payload = StaticDiscoveryPayload.model_validate_json(static_discovery.read_bytes())
    if payload.availability != "ready":
        raise ValueError("static discovery input is not ready")
    pairs, parse_coverage = _read_positive_pairs(archive, resolved_settings)
    static_targets = _static_targets(payload)
    threshold_rows = tuple(
        _threshold_coverage(
            pairs,
            static_targets,
            threshold,
            resolved_settings,
        )
        for threshold in resolved_settings.raw_count_thresholds
    )
    base = LastFmArtistTags2007OverlapReport(
        archive_sha256=archive_sha256,
        archive_byte_count=archive_byte_count,
        static_discovery_sha256=static_sha256,
        static_discovery_byte_count=static_byte_count,
        static_discovery_revision=payload.revision,
        settings=resolved_settings,
        parse_coverage=parse_coverage,
        static_artist_mbid_count=len(static_targets.artists),
        static_genre_name_count=len(static_targets.names),
        static_membership_pair_count=len(static_targets.pairs),
        thresholds=threshold_rows,
        output_sha256="0" * 64,
    )
    return base.model_copy(update={"output_sha256": _output_sha256(base)})


def verify_lastfm_artisttags2007_static_overlap(
    report: LastFmArtistTags2007OverlapReport,
) -> None:
    """Fail closed on a modified report or a claim that crosses the research boundary."""
    if report.output_sha256 != _output_sha256(report):
        raise ValueError("Last.fm ArtistTags2007 overlap output hash does not replay")
    if report.archive_sha256 != _ARCHIVE_SHA256:
        raise ValueError("Last.fm ArtistTags2007 report has an unpinned source hash")
    if report.missing_source_tags_are_negatives:
        raise ValueError("Last.fm ArtistTags2007 report must remain positive-only")


def _read_positive_pairs(
    archive: Path, settings: LastFmArtistTags2007OverlapSettings
) -> tuple[dict[tuple[str, str], int], LastFmArtistTags2007ParseCoverage]:
    counts: Counter[str] = Counter()
    pairs: dict[tuple[str, str], int] = {}
    with tarfile.open(archive, mode="r:gz") as source:
        member = source.getmember(_DATA_MEMBER)
        stream = source.extractfile(member)
        if stream is None:
            raise ValueError("Last.fm ArtistTags2007 archive data member is unavailable")
        for raw in stream:
            counts["total"] += 1
            if counts["total"] > settings.maximum_rows:
                raise ValueError("Last.fm ArtistTags2007 archive exceeds configured row bound")
            try:
                row = raw.rstrip(b"\r\n").decode("utf-8")
            except UnicodeDecodeError:
                counts["invalid_utf8"] += 1
                continue
            fields = row.split("<sep>")
            if len(fields) != _ROW_FIELD_COUNT:
                counts["malformed"] += 1
                continue
            mbid, _artist_name, tag_name, raw_count = fields
            if not _is_mbid(mbid):
                counts["invalid_mbid"] += 1
                continue
            try:
                count = int(raw_count)
            except ValueError:
                counts["invalid_count"] += 1
                continue
            if count <= 0:
                counts["nonpositive"] += 1
                continue
            key = (mbid, tag_name)
            if key in pairs:
                counts["duplicate"] += 1
                continue
            pairs[key] = count
            counts["accepted"] += 1
    return pairs, LastFmArtistTags2007ParseCoverage(
        total_row_count=counts["total"],
        accepted_positive_row_count=counts["accepted"],
        malformed_row_count=counts["malformed"],
        invalid_utf8_row_count=counts["invalid_utf8"],
        invalid_mbid_row_count=counts["invalid_mbid"],
        invalid_count_row_count=counts["invalid_count"],
        nonpositive_count_row_count=counts["nonpositive"],
        duplicate_artist_tag_row_count=counts["duplicate"],
    )


def _is_mbid(value: str) -> bool:
    return (
        len(value) == _MBID_LENGTH
        and value[8] == value[13] == value[18] == value[23] == "-"
        and all(character in "0123456789abcdef" for character in value.replace("-", ""))
    )


def _static_targets(payload: StaticDiscoveryPayload) -> _StaticTargets:
    pairs: set[tuple[str, str]] = set()
    for artist in payload.artists:
        if artist.musicbrainz_url is None:
            continue
        mbid = artist.musicbrainz_url.rsplit("/", maxsplit=1)[-1]
        if not _is_mbid(mbid):
            raise ValueError("static discovery contains an invalid MusicBrainz artist identifier")
        pairs.update((mbid, membership.catalog_genre_name) for membership in artist.memberships)
    return _StaticTargets(
        pairs=pairs,
        artists={artist for artist, _ in pairs},
        names={name for _, name in pairs},
    )


def _threshold_coverage(
    pairs: dict[tuple[str, str], int],
    static_targets: _StaticTargets,
    threshold: int,
    settings: LastFmArtistTags2007OverlapSettings,
) -> LastFmArtistTags2007ThresholdCoverage:
    positives = {pair for pair, count in pairs.items() if count >= threshold}
    heldout = {pair for pair in positives if _is_heldout(pair, settings)}
    artist_matched = {pair for pair in heldout if pair[0] in static_targets.artists}
    name_matched = {pair for pair in heldout if pair[1] in static_targets.names}
    scoreable = artist_matched & name_matched
    overlap = heldout & static_targets.pairs
    return LastFmArtistTags2007ThresholdCoverage(
        raw_count_threshold=threshold,
        source_positive_pair_count=len(positives),
        heldout_positive_pair_count=len(heldout),
        heldout_artist_id_matched_positive_pair_count=len(artist_matched),
        heldout_exact_genre_name_matched_positive_pair_count=len(name_matched),
        heldout_scoreable_positive_pair_count=len(scoreable),
        heldout_exact_pair_overlap_count=len(overlap),
        global_positive_overlap_recall=len(overlap) / len(heldout) if heldout else 0.0,
        scoreable_positive_overlap_recall=len(overlap) / len(scoreable) if scoreable else 0.0,
    )


def _is_heldout(pair: tuple[str, str], settings: LastFmArtistTags2007OverlapSettings) -> bool:
    digest = hashlib.sha256(f"{pair[0]}\0{pair[1]}".encode()).digest()
    return int.from_bytes(digest[:8]) % settings.heldout_modulus == settings.heldout_remainder


def _output_sha256(report: LastFmArtistTags2007OverlapReport) -> Sha256:
    return sha256_json(report.model_dump(mode="json", exclude={"output_sha256"}))
