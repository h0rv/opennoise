"""Bind native release-group genres to credited artists as local-only support.

This deliberately preserves the release group as the observed entity. A row here is
not, and must never be converted into, an artist-to-genre membership claim.
"""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from opennoise.ingest.musicbrainz.release_group_native_observation import (
    NativeGenreObservation,
    ReleaseGroupNativeObservationReport,
    verify_release_group_native_observation,
)
from opennoise.models.pipeline import SourceLimits
from opennoise.pipeline.source_cache import (
    SourceCacheReceipt,
    receipt_sha256,
    verify_source_cache_receipt,
)
from opennoise.sources.musicbrainz import MusicBrainzReleaseGroup, _iter_raw_archive

if TYPE_CHECKING:
    from pathlib import Path

    from opennoise.models.sources import DownloadSource

_REVISION: Final = "musicbrainz-release-group-native-artist-support-v1"
_SHA256: Final = r"^[0-9a-f]{64}$"


class ReleaseGroupNativeArtistSupportError(ValueError):
    """The source replay cannot prove its exact native-observation binding."""


class _FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")


class CreditedArtist(_FrozenModel):
    """One ordered, exact MusicBrainz artist-credit component."""

    artist_mbid: str = Field(pattern=r"^[0-9a-f-]{36}$")
    artist_name: str = Field(min_length=1)
    credited_name: str = Field(min_length=1)
    joinphrase: str


class NativeReleaseGroupFact(_FrozenModel):
    """An observed release-group fact, retained independently of any support link."""

    release_group_mbid: str = Field(pattern=r"^[0-9a-f-]{36}$")
    record_content_sha256: str = Field(pattern=_SHA256)
    record_byte_length: int = Field(gt=0)
    title: str = Field(min_length=1)
    primary_type: str | None
    first_release_date: str | None
    artist_credit: tuple[CreditedArtist, ...]
    proper_genres: tuple[NativeGenreObservation, ...]


class CreditedArtistGenreSupport(_FrozenModel):
    """A contextual support link; it has no artist-membership semantics."""

    evidence_role: Literal["credited_artist_release_group_genre_support"] = (
        "credited_artist_release_group_genre_support"
    )
    artist_mbid: str = Field(pattern=r"^[0-9a-f-]{36}$")
    credit_position: int = Field(ge=0)
    release_group_mbid: str = Field(pattern=r"^[0-9a-f-]{36}$")
    genre_mbid: str = Field(pattern=r"^[0-9a-f-]{36}$")
    record_content_sha256: str = Field(pattern=_SHA256)


class ReleaseGroupNativeArtistSupportCoverage(_FrozenModel):
    """Coverage and explicit abstention denominators for this fixed sample."""

    sampled_release_group_count: int = Field(ge=0)
    groups_with_native_proper_genres: int = Field(ge=0)
    groups_with_positive_native_proper_genres: int = Field(ge=0)
    groups_with_exact_artist_credits: int = Field(ge=0)
    groups_with_positive_genres_and_credits: int = Field(ge=0)
    groups_without_exact_artist_credit_abstained: int = Field(ge=0)
    groups_without_positive_native_genre_abstained: int = Field(ge=0)
    multi_artist_credit_group_count: int = Field(ge=0)
    native_genre_observation_count: int = Field(ge=0)
    credited_artist_genre_support_count: int = Field(ge=0)

    @model_validator(mode="after")
    def _counts_are_bounded(self) -> ReleaseGroupNativeArtistSupportCoverage:
        if self.groups_with_native_proper_genres > self.sampled_release_group_count:
            raise ValueError("genre-bearing groups exceed sample")
        if self.groups_with_positive_native_proper_genres > self.groups_with_native_proper_genres:
            raise ValueError("positive-genre groups exceed native-genre groups")
        if self.groups_with_exact_artist_credits > self.sampled_release_group_count:
            raise ValueError("credited groups exceed sample")
        if (
            self.groups_with_positive_genres_and_credits
            > self.groups_with_positive_native_proper_genres
        ):
            raise ValueError("linked groups exceed genre-bearing groups")
        if self.groups_with_positive_genres_and_credits > self.groups_with_exact_artist_credits:
            raise ValueError("linked groups exceed credited groups")
        if (
            self.groups_without_exact_artist_credit_abstained
            > self.groups_with_positive_native_proper_genres
        ):
            raise ValueError("credit abstentions exceed genre-bearing groups")
        return self


class ReleaseGroupNativeArtistSupportReport(_FrozenModel):
    """A receipt-bound, local-only projection of native release-group facts and support."""

    revision: Literal["musicbrainz-release-group-native-artist-support-v1"] = _REVISION
    export_allowed: Literal[False] = False
    serving_allowed: Literal[False] = False
    artist_membership_propagation_allowed: Literal[False] = False
    native_observation_report_sha256: str = Field(pattern=_SHA256)
    source_archive_sha256: str = Field(pattern=_SHA256)
    source_archive_bytes: int = Field(gt=0)
    source_cache_receipt_sha256: str = Field(pattern=_SHA256)
    release_group_facts: tuple[NativeReleaseGroupFact, ...]
    support: tuple[CreditedArtistGenreSupport, ...]
    coverage: ReleaseGroupNativeArtistSupportCoverage
    output_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def _support_is_only_a_verified_album_cross_product(
        self,
    ) -> ReleaseGroupNativeArtistSupportReport:
        by_group = {item.release_group_mbid: item for item in self.release_group_facts}
        if len(by_group) != len(self.release_group_facts):
            raise ValueError("release-group facts repeat a release group")
        expected = tuple(
            (
                artist.artist_mbid,
                position,
                album.release_group_mbid,
                genre.genre_mbid,
                album.record_content_sha256,
            )
            for album in self.release_group_facts
            for position, artist in enumerate(album.artist_credit)
            for genre in album.proper_genres
            if genre.vote_count is not None and genre.vote_count > 0
        )
        actual = tuple(
            (
                item.artist_mbid,
                item.credit_position,
                item.release_group_mbid,
                item.genre_mbid,
                item.record_content_sha256,
            )
            for item in self.support
        )
        if actual != expected:
            raise ValueError(
                "support must be exactly the credited release-group genre cross product"
            )
        if self.coverage.sampled_release_group_count != len(self.release_group_facts):
            raise ValueError("sample count does not match retained release-group facts")
        if self.coverage.credited_artist_genre_support_count != len(self.support):
            raise ValueError("support count does not match retained support")
        return self


def _sha(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, default=_json_default, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()


def _json_default(value: object) -> object:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, tuple):
        return list(value)
    raise TypeError(f"unsupported receipt value: {type(value)!r}")


def _file_sha256(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def report_sha256(report: ReleaseGroupNativeArtistSupportReport) -> str:
    """Return the deterministic hash excluding the self-referential output field."""
    return _sha(report.model_dump(mode="json", exclude={"output_sha256"}))


def verify_release_group_native_artist_support(
    report: ReleaseGroupNativeArtistSupportReport,
) -> None:
    """Fail closed when a report or its support-only semantics were altered."""
    if report_sha256(report) != report.output_sha256:
        raise ReleaseGroupNativeArtistSupportError(
            "native artist-support report hash does not replay"
        )


def build_release_group_native_artist_support(  # noqa: C901
    archive_path: Path,
    source: DownloadSource,
    source_cache_receipt: SourceCacheReceipt,
    declared_manifest_sha256: str,
    native_observation: ReleaseGroupNativeObservationReport,
) -> ReleaseGroupNativeArtistSupportReport:
    """Replay exactly the prior bounded sample and attach only exact artist credits."""
    verify_release_group_native_observation(native_observation)
    if source.adapter != "musicbrainz_release_group_json_dump_v1":
        raise ReleaseGroupNativeArtistSupportError("source is not a release-group JSON dump")
    try:
        verify_source_cache_receipt(
            source_cache_receipt, (source,), declared_manifest_sha256=declared_manifest_sha256
        )
    except (RuntimeError, ValueError) as error:
        raise ReleaseGroupNativeArtistSupportError(
            "source cache receipt does not match source"
        ) from error
    archive_sha256, archive_bytes = _file_sha256(archive_path)
    if archive_sha256 != source.verified_sha256() or archive_bytes != source.expected_bytes:
        raise ReleaseGroupNativeArtistSupportError("archive bytes do not match pinned source")
    if (
        archive_sha256 != native_observation.source_archive_sha256
        or archive_bytes != native_observation.source_archive_bytes
        or receipt_sha256(source_cache_receipt) != native_observation.source_cache_receipt_sha256
    ):
        raise ReleaseGroupNativeArtistSupportError(
            "source does not match native observation receipt"
        )

    expected = iter(native_observation.samples)
    next_expected = next(expected, None)
    release_group_facts: list[NativeReleaseGroupFact] = []
    for raw in _iter_raw_archive(
        archive_path,
        SourceLimits(max_archive_bytes=archive_bytes, max_record_bytes=2 * 1024**2),
        member_name="release-group",
    ):
        if next_expected is None:
            break
        if raw.payload is None:
            continue
        try:
            group = MusicBrainzReleaseGroup.model_validate_json(raw.payload)
        except ValueError:
            continue
        if (
            raw.sha256 != next_expected.record_content_sha256
            or raw.byte_length != next_expected.record_byte_length
        ):
            raise ReleaseGroupNativeArtistSupportError(
                "archive valid-record order differs from native receipt"
            )
        if str(group.id) != next_expected.release_group_mbid:
            raise ReleaseGroupNativeArtistSupportError(
                "release-group identity differs from native receipt"
            )
        genres = tuple(
            NativeGenreObservation(genre_mbid=str(item.id), name=item.name, vote_count=item.count)
            for item in group.genres
        )
        if genres != next_expected.proper_genres:
            raise ReleaseGroupNativeArtistSupportError("native genres differ from native receipt")
        release_group_facts.append(
            NativeReleaseGroupFact(
                release_group_mbid=str(group.id),
                record_content_sha256=raw.sha256,
                record_byte_length=raw.byte_length,
                title=group.title,
                primary_type=group.primary_type,
                first_release_date=group.first_release_date,
                artist_credit=tuple(
                    CreditedArtist(
                        artist_mbid=str(item.artist.id),
                        artist_name=item.artist.name,
                        credited_name=item.name,
                        joinphrase=item.joinphrase,
                    )
                    for item in group.artist_credit
                ),
                proper_genres=genres,
            )
        )
        next_expected = next(expected, None)
    if next_expected is not None or len(release_group_facts) != len(native_observation.samples):
        raise ReleaseGroupNativeArtistSupportError(
            "archive cannot replay every native sample receipt"
        )
    support = tuple(
        CreditedArtistGenreSupport(
            artist_mbid=artist.artist_mbid,
            credit_position=credit_position,
            release_group_mbid=album.release_group_mbid,
            genre_mbid=genre.genre_mbid,
            record_content_sha256=album.record_content_sha256,
        )
        for album in release_group_facts
        for credit_position, artist in enumerate(album.artist_credit)
        for genre in album.proper_genres
        if genre.vote_count is not None and genre.vote_count > 0
    )
    native_genre_groups = tuple(item for item in release_group_facts if item.proper_genres)
    positive_genre_groups = tuple(
        item
        for item in release_group_facts
        if any(
            genre.vote_count is not None and genre.vote_count > 0 for genre in item.proper_genres
        )
    )
    coverage = ReleaseGroupNativeArtistSupportCoverage(
        sampled_release_group_count=len(release_group_facts),
        groups_with_native_proper_genres=len(native_genre_groups),
        groups_with_positive_native_proper_genres=len(positive_genre_groups),
        groups_with_exact_artist_credits=sum(
            bool(item.artist_credit) for item in release_group_facts
        ),
        groups_with_positive_genres_and_credits=sum(
            bool(item.artist_credit) for item in positive_genre_groups
        ),
        groups_without_exact_artist_credit_abstained=sum(
            not item.artist_credit for item in positive_genre_groups
        ),
        groups_without_positive_native_genre_abstained=sum(
            not any(
                genre.vote_count is not None and genre.vote_count > 0
                for genre in item.proper_genres
            )
            for item in release_group_facts
        ),
        multi_artist_credit_group_count=sum(
            len(item.artist_credit) > 1 for item in release_group_facts
        ),
        native_genre_observation_count=sum(len(item.proper_genres) for item in release_group_facts),
        credited_artist_genre_support_count=len(support),
    )
    preliminary = ReleaseGroupNativeArtistSupportReport(
        native_observation_report_sha256=native_observation.output_sha256,
        source_archive_sha256=archive_sha256,
        source_archive_bytes=archive_bytes,
        source_cache_receipt_sha256=receipt_sha256(source_cache_receipt),
        release_group_facts=tuple(release_group_facts),
        support=support,
        coverage=coverage,
        output_sha256="0" * 64,
    )
    report = preliminary.model_copy(update={"output_sha256": report_sha256(preliminary)})
    verify_release_group_native_artist_support(report)
    return report
