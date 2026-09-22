"""Build a local-only, unreviewed Last.fm packet for literal v2 genre candidates."""

from __future__ import annotations

import hashlib
import heapq
import re
import tarfile
from typing import TYPE_CHECKING, Final, Literal

from pydantic import Field, model_validator

from opennoise.common import sha256_file, sha256_json
from opennoise.deployment.public_static_discovery_v2 import (
    PublicStaticDiscoveryV2Genre,
    PublicStaticDiscoveryV2Payload,
    public_static_discovery_v2_sha256,
)
from opennoise.models import FrozenModel
from opennoise.types import Sha256  # noqa: TC001 - Pydantic resolves this alias at runtime.

if TYPE_CHECKING:
    from pathlib import Path

_ARCHIVE_SHA256: Final = "b2b78000279c00c49ad6c0e764203dfbe4deb18a8012c1f43b7fb64933741c4f"
_STATIC_DISCOVERY_SHA256: Final = "4d8adac6b3a929addf4413b41ffcf13de10633f57b2a784bfbe0449f3bcede1c"
_DATA_MEMBER: Final = "Lastfm-ArtistTags2007/ArtistTags.dat"
_MBID_PATTERN: Final = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
_ROW_FIELD_COUNT: Final = 4
_MAX_SAMPLE_SIZE: Final = 100

type _HeapEntry = tuple[int, int, LastFmStaticGenreReviewRow]


class LastFmStaticGenreReviewRow(FrozenModel):
    """One literal candidate, deliberately without a membership judgment."""

    question_id: str = Field(pattern=r"^lastfm2007-static-v2:[0-9a-f]{64}$")
    source_row_ordinal: int = Field(ge=1)
    source_row_sha256: Sha256
    musicbrainz_artist_id: str = Field(pattern=r"^[0-9a-f-]{36}$")
    source_artist_name: str = Field(min_length=1)
    source_tag: str = Field(min_length=1)
    source_count: int = Field(ge=1)
    catalog_genre_id: int = Field(gt=0)
    catalog_genre_name: str = Field(min_length=1)
    catalog_genre_node_id: str = Field(pattern=r"^item[1-9][0-9]*$")
    review_state: Literal["unreviewed_abstain"] = "unreviewed_abstain"
    reviewer_artist_genre_member: None = None

    @model_validator(mode="after")
    def require_literal_candidate_without_label(self) -> LastFmStaticGenreReviewRow:
        """Keep matching and review status strictly non-semantic."""
        if self.source_tag != self.catalog_genre_name:
            raise ValueError("candidate genre name must exactly equal the raw source tag")
        return self


class LastFmStaticGenreReviewPacket(FrozenModel):
    """A bounded source-custodied packet, not a gold set or prediction input."""

    revision: Literal["lastfm-artisttags2007-static-genre-review-v1"] = (
        "lastfm-artisttags2007-static-genre-review-v1"
    )
    source_locator: Literal["Lastfm-ArtistTags2007/ArtistTags.dat"] = _DATA_MEMBER
    source_archive_sha256: Sha256
    source_archive_byte_count: int = Field(ge=1)
    static_discovery_revision: Literal["static-direct-discovery-v2"]
    static_discovery_sha256: Sha256
    static_discovery_logical_sha256: Sha256
    static_discovery_byte_count: int = Field(ge=1)
    static_artist_mbid_count: int = Field(ge=1)
    source_row_count: int = Field(ge=0)
    accepted_positive_row_count: int = Field(ge=0)
    literal_candidate_pair_count: int = Field(ge=0)
    sample_size: int = Field(ge=1, le=_MAX_SAMPLE_SIZE)
    exact_musicbrainz_artist_id_matching_only: Literal[True] = True
    literal_genre_name_candidate_matching_only: Literal[True] = True
    automatic_tag_to_genre_approval: Literal[False] = False
    negative_labels_present: Literal[False] = False
    predictions_read: Literal[False] = False
    rows: tuple[LastFmStaticGenreReviewRow, ...]
    output_sha256: Sha256

    @model_validator(mode="after")
    def require_complete_unreviewed_packet(self) -> LastFmStaticGenreReviewPacket:
        """Fail closed if custody, bounded sampling, or abstention state drift."""
        if self.source_archive_sha256 != _ARCHIVE_SHA256:
            raise ValueError("archive hash is not the pinned Last.fm source")
        if self.static_discovery_sha256 != _STATIC_DISCOVERY_SHA256:
            raise ValueError("static discovery hash is not the pinned public v2 asset")
        if self.sample_size != len(self.rows):
            raise ValueError("sample size must equal rows")
        if self.literal_candidate_pair_count < self.sample_size:
            raise ValueError("candidate count cannot be smaller than the sample")
        if any(row.review_state != "unreviewed_abstain" for row in self.rows):
            raise ValueError("review rows must remain unreviewed abstentions")
        if any(row.reviewer_artist_genre_member is not None for row in self.rows):
            raise ValueError("review packet must not contain membership labels")
        if len({row.question_id for row in self.rows}) != len(self.rows):
            raise ValueError("review rows must have unique stable question identifiers")
        if self.output_sha256 != sha256_json(self.model_dump(exclude={"output_sha256"})):
            raise ValueError("review packet output hash does not replay")
        return self


def build_lastfm_static_genre_review(
    archive: Path, static_discovery: Path, *, sample_size: int = _MAX_SAMPLE_SIZE
) -> LastFmStaticGenreReviewPacket:
    """Select deterministic literal candidates without reading predictions or labels."""
    if not 1 <= sample_size <= _MAX_SAMPLE_SIZE:
        raise ValueError(f"sample size must be between 1 and {_MAX_SAMPLE_SIZE}")
    archive_sha256, archive_byte_count = sha256_file(archive)
    if archive_sha256 != _ARCHIVE_SHA256:
        raise ValueError("Last.fm ArtistTags2007 archive hash does not match the pinned source")
    static_sha256, static_byte_count = sha256_file(static_discovery)
    if static_sha256 != _STATIC_DISCOVERY_SHA256:
        raise ValueError("static discovery hash does not match the pinned public v2 asset")
    static_payload = PublicStaticDiscoveryV2Payload.model_validate_json(
        static_discovery.read_bytes()
    )
    if static_payload.output_sha256 != public_static_discovery_v2_sha256(static_payload):
        raise ValueError("static discovery payload logical hash does not replay")
    genre_by_name = {genre.catalog_genre_name: genre for genre in static_payload.genres}
    if len(genre_by_name) != len(static_payload.genres):
        raise ValueError("static discovery repeats a literal catalog genre name")
    static_artist_ids = frozenset(
        artist.musicbrainz_url.rsplit("/", maxsplit=1)[-1]
        for artist in static_payload.artists
        if artist.musicbrainz_url is not None
    )
    if not static_artist_ids:
        raise ValueError("static discovery has no exact MusicBrainz artist identifiers")
    rows, total, accepted, candidates = _select_rows(
        archive, genre_by_name, static_artist_ids, sample_size
    )
    fields = {
        "revision": "lastfm-artisttags2007-static-genre-review-v1",
        "source_locator": _DATA_MEMBER,
        "source_archive_sha256": archive_sha256,
        "source_archive_byte_count": archive_byte_count,
        "static_discovery_revision": static_payload.revision,
        "static_discovery_sha256": static_sha256,
        "static_discovery_logical_sha256": static_payload.output_sha256,
        "static_discovery_byte_count": static_byte_count,
        "static_artist_mbid_count": len(static_artist_ids),
        "source_row_count": total,
        "accepted_positive_row_count": accepted,
        "literal_candidate_pair_count": candidates,
        "sample_size": sample_size,
        "exact_musicbrainz_artist_id_matching_only": True,
        "literal_genre_name_candidate_matching_only": True,
        "automatic_tag_to_genre_approval": False,
        "negative_labels_present": False,
        "predictions_read": False,
        "rows": rows,
    }
    fields["output_sha256"] = sha256_json(fields | {"rows": [row.model_dump() for row in rows]})
    return LastFmStaticGenreReviewPacket.model_validate(fields)


def _select_rows(
    archive: Path,
    genre_by_name: dict[str, PublicStaticDiscoveryV2Genre],
    static_artist_ids: frozenset[str],
    sample_size: int,
) -> tuple[tuple[LastFmStaticGenreReviewRow, ...], int, int, int]:
    """Stream the archive and retain the hash-smallest bounded candidate sample."""
    heap: list[_HeapEntry] = []
    seen_artist_genre: set[tuple[str, int]] = set()
    total = accepted = candidates = 0
    with tarfile.open(archive, mode="r:gz") as source:
        stream = source.extractfile(_DATA_MEMBER)
        if stream is None:
            raise ValueError("Last.fm ArtistTags2007 data member is unavailable")
        for ordinal, raw in enumerate(stream, start=1):
            total += 1
            parsed = _parse_source_row(raw)
            if parsed is None:
                continue
            artist_id, artist_name, tag, count = parsed
            accepted += 1
            if artist_id not in static_artist_ids:
                continue
            genre = genre_by_name.get(tag)
            if genre is None:
                continue
            if (artist_id, genre.catalog_genre_id) in seen_artist_genre:
                continue
            seen_artist_genre.add((artist_id, genre.catalog_genre_id))
            candidates += 1
            source_hash = hashlib.sha256(raw).hexdigest()
            question_hash = hashlib.sha256(
                f"{artist_id}\0{source_hash}\0{genre.catalog_genre_id}".encode()
            ).hexdigest()
            row = LastFmStaticGenreReviewRow(
                question_id=f"lastfm2007-static-v2:{question_hash}",
                source_row_ordinal=ordinal,
                source_row_sha256=source_hash,
                musicbrainz_artist_id=artist_id,
                source_artist_name=artist_name,
                source_tag=tag,
                source_count=count,
                catalog_genre_id=genre.catalog_genre_id,
                catalog_genre_name=genre.catalog_genre_name,
                catalog_genre_node_id=genre.node_id,
            )
            rank = int(question_hash, 16)
            if len(heap) < sample_size:
                heapq.heappush(heap, (-rank, -ordinal, row))
            elif rank < -heap[0][0]:
                heapq.heapreplace(heap, (-rank, -ordinal, row))
    if len(heap) < sample_size:
        raise ValueError("not enough literal static genre candidates for review packet")
    rows = tuple(sorted((row for _rank, _ordinal, row in heap), key=lambda row: row.question_id))
    return rows, total, accepted, candidates


def _parse_source_row(raw: bytes) -> tuple[str, str, str, int] | None:
    """Accept only one well-formed positive Last.fm observation."""
    try:
        fields = raw.rstrip(b"\r\n").decode("utf-8").split("<sep>")
    except UnicodeDecodeError:
        return None
    if len(fields) != _ROW_FIELD_COUNT:
        return None
    artist_id, artist_name, tag, raw_count = fields
    if not _MBID_PATTERN.fullmatch(artist_id) or not artist_name or not tag:
        return None
    try:
        count = int(raw_count)
    except ValueError:
        return None
    return (artist_id, artist_name, tag, count) if count > 0 else None
