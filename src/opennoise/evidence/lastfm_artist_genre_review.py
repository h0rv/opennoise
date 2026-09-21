"""Build a blind, source-bound review packet from Last.fm ArtistTags2007."""

from __future__ import annotations

import hashlib
import heapq
import re
import tarfile
from typing import TYPE_CHECKING, Final, Literal

from pydantic import Field, model_validator

if TYPE_CHECKING:
    from pathlib import Path

from opennoise.common import sha256_file, sha256_json
from opennoise.models import FrozenModel
from opennoise.types import Sha256  # noqa: TC001  # Pydantic resolves this alias at runtime.

_ARCHIVE_SHA256: Final = "b2b78000279c00c49ad6c0e764203dfbe4deb18a8012c1f43b7fb64933741c4f"
_DATA_MEMBER: Final = "Lastfm-ArtistTags2007/ArtistTags.dat"
_MBID_PATTERN: Final = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
_MINIMUM_SAMPLE_SIZE: Final = 2
_ROW_FIELD_COUNT: Final = 4

type _HeapEntry = tuple[int, int, LastFmReviewRow]


class LastFmReviewRow(FrozenModel):
    """One archive observation presented for human review, with no judgment."""

    review_id: str = Field(pattern=r"^lastfm2007:[0-9a-f]{64}$")
    source_row_ordinal: int = Field(ge=1)
    source_row_sha256: Sha256
    musicbrainz_artist_id: str = Field(pattern=r"^[0-9a-f-]{36}$")
    source_artist_name: str = Field(min_length=1)
    candidate_genre_name: str = Field(min_length=1)
    source_tag: str = Field(min_length=1)
    source_count: int = Field(ge=1)
    sampling_stratum: Literal["count_1", "count_gt_1"]
    review_status: Literal["unlabeled"] = "unlabeled"
    reviewer_artist_genre_member: None = None

    @model_validator(mode="after")
    def _tag_is_candidate_only(self) -> LastFmReviewRow:
        if self.candidate_genre_name != self.source_tag:
            raise ValueError("candidate genre name must remain the raw source tag")
        if (self.source_count == 1) != (self.sampling_stratum == "count_1"):
            raise ValueError("sampling stratum does not match source count")
        return self


class LastFmReviewPacket(FrozenModel):
    """A deterministic, balanced packet that contains evidence, not labels."""

    revision: Literal["lastfm-artist-genre-review-v1"] = "lastfm-artist-genre-review-v1"
    source_locator: Literal["Lastfm-ArtistTags2007/ArtistTags.dat"] = _DATA_MEMBER
    source_archive_sha256: Sha256
    source_archive_byte_count: int = Field(ge=1)
    source_row_count: int = Field(ge=0)
    accepted_positive_row_count: int = Field(ge=0)
    sample_size: int = Field(ge=2)
    stratum_counts: dict[Literal["count_1", "count_gt_1"], int]
    excluded_provenance: tuple[
        Literal["every_noise", "musicbrainz", "wikidata", "listenbrainz", "model_prediction"],
        ...,
    ] = ("every_noise", "musicbrainz", "wikidata", "listenbrainz", "model_prediction")
    source_observations_are_positive_tags: Literal[True] = True
    missing_tags_are_not_negative: Literal[True] = True
    reviewer_must_judge_membership: Literal[True] = True
    rows: tuple[LastFmReviewRow, ...]
    output_sha256: Sha256

    @model_validator(mode="after")
    def _complete(self) -> LastFmReviewPacket:
        if self.source_archive_sha256 != _ARCHIVE_SHA256:
            raise ValueError("archive hash is not the pinned Last.fm source")
        if self.sample_size != len(self.rows) or self.sample_size % 2:
            raise ValueError("sample size must equal rows and be even")
        if self.stratum_counts != {
            "count_1": self.sample_size // 2,
            "count_gt_1": self.sample_size // 2,
        }:
            raise ValueError("review packet must balance the two count strata")
        if any(row.review_status != "unlabeled" for row in self.rows):
            raise ValueError("review rows must remain unlabeled")
        if len({row.review_id for row in self.rows}) != len(self.rows):
            raise ValueError("review rows must have unique source row identities")
        if len({(row.musicbrainz_artist_id, row.source_tag) for row in self.rows}) != len(
            self.rows
        ):
            raise ValueError("review rows must have unique artist and tag questions")
        if self.output_sha256 != sha256_json(self.model_dump(exclude={"output_sha256"})):
            raise ValueError("review packet output hash does not replay")
        return self


def build_lastfm_artist_genre_review(  # noqa: C901, PLR0912, PLR0915 - streaming custody accounting stays together.
    archive: Path, *, sample_size: int = 100
) -> LastFmReviewPacket:
    """Select a deterministic balanced sample without reading model data."""
    if sample_size < _MINIMUM_SAMPLE_SIZE or sample_size % _MINIMUM_SAMPLE_SIZE:
        raise ValueError("sample_size must be an even number of at least 2")
    archive_sha256, archive_byte_count = sha256_file(archive)
    if archive_sha256 != _ARCHIVE_SHA256:
        raise ValueError("Last.fm ArtistTags2007 archive hash does not match the pinned source")
    per_stratum = sample_size // 2
    heap_capacity = per_stratum * 4
    heaps: dict[str, list[_HeapEntry]] = {
        "count_1": [],
        "count_gt_1": [],
    }
    total = accepted = 0
    with tarfile.open(archive, mode="r:gz") as source:
        member = source.getmember(_DATA_MEMBER)
        stream = source.extractfile(member)
        if stream is None:
            raise ValueError("Last.fm ArtistTags2007 data member is unavailable")
        for ordinal, raw in enumerate(stream, start=1):
            total += 1
            line = raw.rstrip(b"\r\n")
            try:
                fields = line.decode("utf-8").split("<sep>")
            except UnicodeDecodeError:
                continue
            if len(fields) != _ROW_FIELD_COUNT:
                continue
            mbid, artist_name, tag, raw_count = fields
            if not _MBID_PATTERN.fullmatch(mbid) or not artist_name or not tag:
                continue
            try:
                count = int(raw_count)
            except ValueError:
                continue
            if count <= 0:
                continue
            accepted += 1
            row_hash = hashlib.sha256(raw).hexdigest()
            stratum: Literal["count_1", "count_gt_1"] = "count_1" if count == 1 else "count_gt_1"
            row = LastFmReviewRow(
                review_id=f"lastfm2007:{row_hash}",
                source_row_ordinal=ordinal,
                source_row_sha256=row_hash,
                musicbrainz_artist_id=mbid,
                source_artist_name=artist_name,
                candidate_genre_name=tag,
                source_tag=tag,
                source_count=count,
                sampling_stratum=stratum,
            )
            rank = int(hashlib.sha256(f"{row.review_id}:{stratum}".encode()).hexdigest(), 16)
            heap = heaps[stratum]
            if len(heap) < heap_capacity:
                heapq.heappush(heap, (-rank, ordinal, row))
            elif rank < -heap[0][0]:
                heapq.heapreplace(heap, (-rank, ordinal, row))
    chosen: list[LastFmReviewRow] = []
    chosen_keys: set[tuple[str, str]] = set()
    for stratum in ("count_1", "count_gt_1"):
        heap = heaps[stratum]
        unique_rows: dict[tuple[str, str], LastFmReviewRow] = {}
        for _rank, _ordinal, row in sorted(heap):
            key = (row.musicbrainz_artist_id, row.source_tag)
            if key not in chosen_keys:
                unique_rows.setdefault(key, row)
        if len(unique_rows) < per_stratum:
            raise ValueError(f"not enough unique rows for {stratum} review stratum")
        selected = list(unique_rows.values())[:per_stratum]
        chosen.extend(selected)
        chosen_keys.update((row.musicbrainz_artist_id, row.source_tag) for row in selected)
    rows = tuple(sorted(chosen, key=lambda row: row.review_id))
    fields = {
        "revision": "lastfm-artist-genre-review-v1",
        "source_locator": _DATA_MEMBER,
        "source_archive_sha256": archive_sha256,
        "source_archive_byte_count": archive_byte_count,
        "source_row_count": total,
        "accepted_positive_row_count": accepted,
        "sample_size": sample_size,
        "stratum_counts": {"count_1": per_stratum, "count_gt_1": per_stratum},
        "excluded_provenance": (
            "every_noise",
            "musicbrainz",
            "wikidata",
            "listenbrainz",
            "model_prediction",
        ),
        "source_observations_are_positive_tags": True,
        "missing_tags_are_not_negative": True,
        "reviewer_must_judge_membership": True,
        "rows": rows,
    }
    hash_payload = {**fields, "rows": [row.model_dump() for row in rows]}
    fields["output_sha256"] = sha256_json(hash_payload)
    return LastFmReviewPacket.model_validate(fields)
