"""Local-only literal Last.fm 2007 artist-tag candidates for the seed vocabulary.

Construction consumes only raw ArtistTags2007 fields and the names/IDs projected
from the supplied 6,291-row reconciliation.  It never reads reconciliation
identity facets, public memberships, predictions, or historical relationships.
The public static map is an optional terminal comparison input only.
"""

from __future__ import annotations

import hashlib
import json
import tarfile
from collections import Counter, defaultdict
from typing import TYPE_CHECKING, Final, Literal

from pydantic import Field, model_validator

from opennoise.common import sha256_file, sha256_json
from opennoise.deployment.public_static_discovery_v2 import PublicStaticDiscoveryV2Payload
from opennoise.models import FrozenModel
from opennoise.types import Sha256  # noqa: TC001 - Pydantic resolves aliases at runtime.

if TYPE_CHECKING:
    from pathlib import Path


_ARCHIVE_SHA256: Final = "b2b78000279c00c49ad6c0e764203dfbe4deb18a8012c1f43b7fb64933741c4f"
_SEED_VOCABULARY_SHA256: Final = "c87fe5b67c0974b30d5ae1d2a9f66b22b122126230cd2561837c94897514f022"
_DATA_MEMBER: Final = "Lastfm-ArtistTags2007/ArtistTags.dat"
_SEED_COUNT: Final = 6_291
_MBID_LENGTH: Final = 36
_ROW_FIELD_COUNT: Final = 4
_MAX_ABSTENTION_BUCKETS: Final = 10_000


class LastFmArtistTags2007SeedCandidate(FrozenModel):
    """One raw positive tag with a literal, unreviewed seed-name target."""

    source_row_ordinal: int = Field(gt=0)
    source_row_sha256: Sha256
    musicbrainz_artist_id: str = Field(pattern=r"^[0-9a-f-]{36}$")
    source_artist_name: str = Field(min_length=1)
    source_tag: str = Field(min_length=1)
    source_count: int = Field(ge=1)
    seed_source_item_id: str = Field(min_length=1)
    seed_name: str = Field(min_length=1)
    candidate_state: Literal["literal_tag_name_match_unreviewed"] = (
        "literal_tag_name_match_unreviewed"
    )

    @model_validator(mode="after")
    def _literal_match(self) -> LastFmArtistTags2007SeedCandidate:
        if self.source_tag != self.seed_name:
            raise ValueError("candidate seed name must exactly equal the raw source tag")
        return self


class LastFmArtistTags2007Abstention(FrozenModel):
    """Aggregate raw observations that cannot become literal candidates."""

    source_tag: str = Field(min_length=1)
    source_count: int = Field(ge=1)
    reason: Literal["no_exact_seed_name", "ambiguous_exact_seed_name", "duplicate_artist_tag"]
    source_row_count: int = Field(gt=0)


class LastFmArtistTags2007SeedParseCoverage(FrozenModel):
    """Complete source-row accounting before any candidate interpretation."""

    total_row_count: int = Field(ge=0)
    accepted_positive_row_count: int = Field(ge=0)
    malformed_row_count: int = Field(ge=0)
    invalid_utf8_row_count: int = Field(ge=0)
    invalid_mbid_row_count: int = Field(ge=0)
    invalid_count_row_count: int = Field(ge=0)
    nonpositive_count_row_count: int = Field(ge=0)
    duplicate_artist_tag_row_count: int = Field(ge=0)
    literal_candidate_row_count: int = Field(ge=0)
    literal_unmatched_row_count: int = Field(ge=0)
    ambiguous_seed_name_row_count: int = Field(ge=0)
    unretained_abstention_row_count: int = Field(ge=0)

    @model_validator(mode="after")
    def _partitions(self) -> LastFmArtistTags2007SeedParseCoverage:
        if self.total_row_count != (
            self.accepted_positive_row_count
            + self.malformed_row_count
            + self.invalid_utf8_row_count
            + self.invalid_mbid_row_count
            + self.invalid_count_row_count
            + self.nonpositive_count_row_count
            + self.duplicate_artist_tag_row_count
        ):
            raise ValueError("parse coverage must partition physical source rows")
        if self.accepted_positive_row_count != (
            self.literal_candidate_row_count
            + self.literal_unmatched_row_count
            + self.ambiguous_seed_name_row_count
        ):
            raise ValueError("accepted source rows must partition into candidate or abstention")
        return self


class LastFmArtistTags2007SeedCandidateArtifact(FrozenModel):
    """A source-backed candidate artifact, never direct membership or gold."""

    revision: Literal["lastfm-artisttags2007-literal-seed-candidates-v1"] = (
        "lastfm-artisttags2007-literal-seed-candidates-v1"
    )
    local_only: Literal[True] = True
    construction_allowed: Literal[False] = False
    factual_direct_membership: Literal[False] = False
    independent_gold_input: Literal[False] = False
    archive_sha256: Sha256
    archive_byte_count: int = Field(ge=1)
    source_locator: Literal["Lastfm-ArtistTags2007/ArtistTags.dat"] = _DATA_MEMBER
    seed_vocabulary_sha256: Sha256
    seed_vocabulary_byte_count: int = Field(ge=1)
    seed_vocabulary_revision: Literal["seed-reconciliation-v3"]
    seed_count: Literal[6291] = _SEED_COUNT
    distinct_literal_seed_name_count: int = Field(ge=0, le=_SEED_COUNT)
    ambiguous_literal_seed_name_count: int = Field(ge=0, le=_SEED_COUNT)
    parse_coverage: LastFmArtistTags2007SeedParseCoverage
    candidates: tuple[LastFmArtistTags2007SeedCandidate, ...]
    abstentions: tuple[LastFmArtistTags2007Abstention, ...]
    unretained_abstention_row_count: int = Field(ge=0)
    output_sha256: Sha256

    @model_validator(mode="after")
    def _complete(self) -> LastFmArtistTags2007SeedCandidateArtifact:
        if self.archive_sha256 != _ARCHIVE_SHA256:
            raise ValueError("archive hash is not the pinned Last.fm ArtistTags2007 source")
        if len(self.candidates) != self.parse_coverage.literal_candidate_row_count:
            raise ValueError("candidate rows do not match parse coverage")
        if sum(row.source_row_count for row in self.abstentions) != (
            self.parse_coverage.literal_unmatched_row_count
            + self.parse_coverage.ambiguous_seed_name_row_count
            + self.parse_coverage.duplicate_artist_tag_row_count
            - self.unretained_abstention_row_count
        ):
            raise ValueError("abstention rows do not match parse coverage")
        if self.output_sha256 != sha256_json(self.model_dump(exclude={"output_sha256"})):
            raise ValueError("candidate artifact output hash does not replay")
        return self


class LastFmArtistTags2007PublicMapComparison(FrozenModel):
    """Terminal comparison only; it cannot change candidate selection."""

    revision: Literal["lastfm-artisttags2007-public-map-comparison-v1"] = (
        "lastfm-artisttags2007-public-map-comparison-v1"
    )
    candidate_output_sha256: Sha256
    public_map_sha256: Sha256
    public_map_artist_mbid_count: int = Field(ge=0)
    candidate_artist_mbid_count: int = Field(ge=0)
    candidate_artist_mbid_in_public_map_count: int = Field(ge=0)
    candidate_seed_count: int = Field(ge=0)
    candidate_seed_in_public_map_count: int = Field(ge=0)
    candidate_pair_count: int = Field(ge=0)
    exact_literal_pair_overlap_count: int = Field(ge=0)
    public_map_read_after_candidate_build: Literal[True] = True
    output_sha256: Sha256

    @model_validator(mode="after")
    def _complete(self) -> LastFmArtistTags2007PublicMapComparison:
        if self.output_sha256 != sha256_json(self.model_dump(exclude={"output_sha256"})):
            raise ValueError("public map comparison output hash does not replay")
        return self


def build_lastfm_artisttags2007_literal_seed_candidates(
    archive: Path, seed_vocabulary: Path
) -> LastFmArtistTags2007SeedCandidateArtifact:
    """Build literal candidates using just pinned rows and the current seed ID/name vocabulary."""
    archive_sha256, archive_byte_count = sha256_file(archive)
    if archive_sha256 != _ARCHIVE_SHA256:
        raise ValueError("Last.fm ArtistTags2007 archive hash does not match the pinned source")
    vocabulary_sha256, vocabulary_byte_count = sha256_file(seed_vocabulary)
    if vocabulary_sha256 != _SEED_VOCABULARY_SHA256:
        raise ValueError("seed vocabulary hash does not match the pinned current 6,291-seed input")
    seed_names = _read_seed_vocabulary(seed_vocabulary)
    candidates, abstentions, coverage = _read_source_rows(archive, seed_names)
    fields: dict[str, object] = {
        "revision": "lastfm-artisttags2007-literal-seed-candidates-v1",
        "local_only": True,
        "construction_allowed": False,
        "factual_direct_membership": False,
        "independent_gold_input": False,
        "archive_sha256": archive_sha256,
        "archive_byte_count": archive_byte_count,
        "source_locator": _DATA_MEMBER,
        "seed_vocabulary_sha256": vocabulary_sha256,
        "seed_vocabulary_byte_count": vocabulary_byte_count,
        "seed_vocabulary_revision": "seed-reconciliation-v3",
        "seed_count": _SEED_COUNT,
        "distinct_literal_seed_name_count": sum(len(rows) == 1 for rows in seed_names.values()),
        "ambiguous_literal_seed_name_count": sum(len(rows) > 1 for rows in seed_names.values()),
        "parse_coverage": coverage.model_dump(mode="json"),
        "candidates": tuple(row.model_dump(mode="json") for row in candidates),
        "abstentions": tuple(row.model_dump(mode="json") for row in abstentions),
        "unretained_abstention_row_count": coverage.unretained_abstention_row_count,
    }
    return LastFmArtistTags2007SeedCandidateArtifact.model_validate_json(
        json.dumps(fields | {"output_sha256": sha256_json(fields)})
    )


def compare_lastfm_artisttags2007_candidates_to_public_map(
    candidate: LastFmArtistTags2007SeedCandidateArtifact, public_map: Path
) -> LastFmArtistTags2007PublicMapComparison:
    """Measure exact overlap only after a candidate was fully source-built."""
    public_sha256, _public_byte_count = sha256_file(public_map)
    payload = PublicStaticDiscoveryV2Payload.model_validate_json(public_map.read_bytes())
    public_pairs: set[tuple[str, str]] = set()
    public_artists: set[str] = set()
    public_seed_names: set[str] = set()
    for artist in payload.artists:
        if artist.musicbrainz_url is None:
            continue
        artist_id = artist.musicbrainz_url.rsplit("/", maxsplit=1)[-1]
        if not _is_mbid(artist_id):
            raise ValueError("public map has an invalid MusicBrainz artist identifier")
        public_artists.add(artist_id)
        for membership in artist.memberships:
            public_pairs.add((artist_id, membership.node_id))
            public_seed_names.add(membership.node_id)
    candidate_pairs = {
        (row.musicbrainz_artist_id, row.seed_source_item_id) for row in candidate.candidates
    }
    candidate_artists = {artist for artist, _seed in candidate_pairs}
    candidate_seeds = {seed for _artist, seed in candidate_pairs}
    fields = {
        "revision": "lastfm-artisttags2007-public-map-comparison-v1",
        "candidate_output_sha256": candidate.output_sha256,
        "public_map_sha256": public_sha256,
        "public_map_artist_mbid_count": len(public_artists),
        "candidate_artist_mbid_count": len(candidate_artists),
        "candidate_artist_mbid_in_public_map_count": len(candidate_artists & public_artists),
        "candidate_seed_count": len(candidate_seeds),
        "candidate_seed_in_public_map_count": len(candidate_seeds & public_seed_names),
        "candidate_pair_count": len(candidate_pairs),
        "exact_literal_pair_overlap_count": len(candidate_pairs & public_pairs),
        "public_map_read_after_candidate_build": True,
    }
    fields["output_sha256"] = sha256_json(fields)
    return LastFmArtistTags2007PublicMapComparison.model_validate(fields)


def _read_seed_vocabulary(path: Path) -> dict[str, tuple[str, ...]]:
    """Project only source IDs and seed names from the reconciliation boundary."""
    try:
        raw = json.loads(path.read_bytes())
    except json.JSONDecodeError as error:
        raise ValueError("seed vocabulary input is not JSON") from error
    if not isinstance(raw, dict) or raw.get("revision") != "seed-reconciliation-v3":
        raise ValueError("seed vocabulary input is not seed-reconciliation-v3")
    rows = raw.get("dispositions")
    if not isinstance(rows, list) or len(rows) != _SEED_COUNT:
        raise ValueError("seed vocabulary must contain exactly 6,291 dispositions")
    names: defaultdict[str, list[str]] = defaultdict(list)
    source_ids: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            raise TypeError("seed vocabulary disposition is not an object")
        source_id, seed_name = row.get("source_item_id"), row.get("seed_name")
        if (
            not isinstance(source_id, str)
            or not source_id
            or not isinstance(seed_name, str)
            or not seed_name
        ):
            raise ValueError("seed vocabulary disposition lacks a source ID or seed name")
        if source_id in source_ids:
            raise ValueError("seed vocabulary repeats a source item ID")
        source_ids.add(source_id)
        names[seed_name].append(source_id)
    return {name: tuple(ids) for name, ids in names.items()}


def _read_source_rows(
    archive: Path, seed_names: dict[str, tuple[str, ...]]
) -> tuple[
    tuple[LastFmArtistTags2007SeedCandidate, ...],
    tuple[LastFmArtistTags2007Abstention, ...],
    LastFmArtistTags2007SeedParseCoverage,
]:
    counters: Counter[str] = Counter()
    candidates: list[LastFmArtistTags2007SeedCandidate] = []
    abstentions: Counter[
        tuple[
            str,
            int,
            Literal["no_exact_seed_name", "ambiguous_exact_seed_name", "duplicate_artist_tag"],
        ]
    ] = Counter()
    seen_artist_tags: set[tuple[str, str]] = set()
    with tarfile.open(archive, mode="r:gz") as source:
        stream = source.extractfile(_DATA_MEMBER)
        if stream is None:
            raise ValueError("Last.fm ArtistTags2007 data member is unavailable")
        for ordinal, raw in enumerate(stream, start=1):
            counters["total"] += 1
            parsed, reason = _parse_source_row(raw)
            if parsed is None:
                counters[reason] += 1
                continue
            artist_id, artist_name, tag, count = parsed
            if (artist_id, tag) in seen_artist_tags:
                counters["duplicate"] += 1
                abstentions[(tag, count, "duplicate_artist_tag")] += 1
                continue
            seen_artist_tags.add((artist_id, tag))
            counters["accepted"] += 1
            seed_ids = seed_names.get(tag, ())
            if len(seed_ids) == 1:
                counters["candidate"] += 1
                candidates.append(
                    LastFmArtistTags2007SeedCandidate(
                        source_row_ordinal=ordinal,
                        source_row_sha256=hashlib.sha256(raw).hexdigest(),
                        musicbrainz_artist_id=artist_id,
                        source_artist_name=artist_name,
                        source_tag=tag,
                        source_count=count,
                        seed_source_item_id=seed_ids[0],
                        seed_name=tag,
                    )
                )
            else:
                abstention_reason: Literal[
                    "no_exact_seed_name", "ambiguous_exact_seed_name", "duplicate_artist_tag"
                ] = "ambiguous_exact_seed_name" if seed_ids else "no_exact_seed_name"
                if seed_ids:
                    counters["ambiguous"] += 1
                else:
                    counters["unmatched"] += 1
                abstentions[(tag, count, abstention_reason)] += 1
    retained_abstentions, unretained_count = _bounded_abstentions(abstentions)
    coverage = LastFmArtistTags2007SeedParseCoverage(
        total_row_count=counters["total"],
        accepted_positive_row_count=counters["accepted"],
        malformed_row_count=counters["malformed"],
        invalid_utf8_row_count=counters["invalid_utf8"],
        invalid_mbid_row_count=counters["invalid_mbid"],
        invalid_count_row_count=counters["invalid_count"],
        nonpositive_count_row_count=counters["nonpositive"],
        duplicate_artist_tag_row_count=counters["duplicate"],
        literal_candidate_row_count=counters["candidate"],
        literal_unmatched_row_count=counters["unmatched"],
        ambiguous_seed_name_row_count=counters["ambiguous"],
        unretained_abstention_row_count=unretained_count,
    )
    return (
        tuple(candidates),
        tuple(
            LastFmArtistTags2007Abstention(
                source_tag=tag, source_count=count, reason=reason, source_row_count=row_count
            )
            for (tag, count, reason), row_count in retained_abstentions
        ),
        coverage,
    )


def _bounded_abstentions(
    abstentions: Counter[
        tuple[
            str,
            int,
            Literal["no_exact_seed_name", "ambiguous_exact_seed_name", "duplicate_artist_tag"],
        ]
    ],
) -> tuple[
    tuple[
        tuple[
            tuple[
                str,
                int,
                Literal["no_exact_seed_name", "ambiguous_exact_seed_name", "duplicate_artist_tag"],
            ],
            int,
        ],
        ...,
    ],
    int,
]:
    ordered = sorted(
        abstentions.items(),
        key=lambda item: hashlib.sha256(
            f"{item[0][0]}\0{item[0][1]}\0{item[0][2]}".encode()
        ).digest(),
    )
    retained = tuple(ordered[:_MAX_ABSTENTION_BUCKETS])
    return retained, sum(count for _key, count in ordered[_MAX_ABSTENTION_BUCKETS:])


def _parse_source_row(raw: bytes) -> tuple[tuple[str, str, str, int] | None, str]:
    try:
        row = raw.rstrip(b"\r\n").decode("utf-8")
    except UnicodeDecodeError:
        return None, "invalid_utf8"
    fields = row.split("<sep>")
    if len(fields) != _ROW_FIELD_COUNT:
        return None, "malformed"
    artist_id, artist_name, tag, raw_count = fields
    if not _is_mbid(artist_id) or not artist_name or not tag:
        return None, "invalid_mbid"
    try:
        count = int(raw_count)
    except ValueError:
        return None, "invalid_count"
    if count <= 0:
        return None, "nonpositive"
    return (artist_id, artist_name, tag, count), "accepted"


def _is_mbid(value: str) -> bool:
    return (
        len(value) == _MBID_LENGTH
        and value[8] == value[13] == value[18] == value[23] == "-"
        and all(character in "0123456789abcdef" for character in value.replace("-", ""))
    )
