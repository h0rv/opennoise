"""Project uniquely witnessed proper-genre frontier anchors for local review.

This is deliberately not a coordinate projection.  It reads the current layout
only as a partition of retained seed IDs into positioned and unplaced sets, and
emits seed-to-seed review relations with exact MusicBrainz artist-record
evidence.  Historical assignments, tags, releases, peer graphs, and coordinate
values are outside the input contract.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Literal

import ijson
from pydantic import Field, model_validator

from opennoise.deployment.musicbrainz_direct_proper_genre_custody import (
    DirectProperGenreClaim,
    DirectProperGenreCustodyReceipt,
    iter_verified_portable_direct_proper_genre_claims,
    verify_portable_direct_proper_genre_custody,
)
from opennoise.models import FrozenModel
from opennoise.types import Sha256  # noqa: TC001

_REVISION: Final = "musicbrainz-direct-proper-genre-anchor-projection-v1"
_RETAINED_SEED_COUNT: Final = 6_291
_SHA256_HEX_LENGTH: Final = 64
_EXCLUSIVE_ARTIST_SEED_COUNT: Final = 2

if TYPE_CHECKING:
    from pathlib import Path


class DirectProperGenreAnchorProjectionError(ValueError):
    """An input is not a bounded, replayable local anchor projection."""


class DirectProperGenreAnchor(FrozenModel):
    """One exclusive exact-artist route from an unplaced seed to one map seed."""

    unplaced_seed_id: str = Field(min_length=1)
    positioned_seed_id: str = Field(min_length=1)
    artist_mbid: str = Field(pattern=r"^[0-9a-f]{8}-[0-9a-f-]{27}$")
    unplaced_source_record_id: str = Field(min_length=1)
    unplaced_source_record_sha256: Sha256
    unplaced_source_evidence_ref: str = Field(min_length=1)
    positioned_source_record_id: str = Field(min_length=1)
    positioned_source_record_sha256: Sha256
    positioned_source_evidence_ref: str = Field(min_length=1)

    @model_validator(mode="after")
    def _different_endpoints(self) -> DirectProperGenreAnchor:
        if self.unplaced_seed_id == self.positioned_seed_id:
            raise ValueError("anchor endpoints must differ")
        return self


class DirectProperGenreAnchorAbstention(FrozenModel):
    """One frontier seed deliberately not projected to a single neighborhood."""

    unplaced_seed_id: str = Field(min_length=1)
    reason: Literal[
        "no_positioned_artist_overlap",
        "multiple_positioned_anchor_seeds",
        "positioned_artist_overlap_not_exclusive",
    ]
    positioned_anchor_seed_count: int = Field(ge=0)
    exclusive_positioned_anchor_seed_count: int = Field(ge=0)


class DirectProperGenreAnchorProjection(FrozenModel):
    """Sealed local-only anchor proposal with all frontier outcomes retained."""

    revision: Literal["musicbrainz-direct-proper-genre-anchor-projection-v1"] = _REVISION
    publication_scope: Literal["local_only_review_projection"] = "local_only_review_projection"
    public_export_authorized: Literal[False] = False
    layout_coordinates_read: Literal[False] = False
    historical_assignments_read: Literal[False] = False
    tags_or_release_or_peer_rows_used: Literal[False] = False
    custody_receipt_byte_sha256: Sha256
    custody_receipt_output_sha256: Sha256
    custody_object_sha256: Sha256
    layout_byte_sha256: Sha256
    layout_embedded_output_sha256: Sha256
    layout_logical_hash_verified: Literal[False] = False
    retained_seed_count: Literal[6291] = _RETAINED_SEED_COUNT
    positioned_seed_count: int = Field(ge=0, le=_RETAINED_SEED_COUNT)
    unplaced_seed_count: int = Field(ge=0, le=_RETAINED_SEED_COUNT)
    proper_genre_frontier_seed_count: int = Field(ge=0, le=_RETAINED_SEED_COUNT)
    proposals: tuple[DirectProperGenreAnchor, ...]
    abstentions: tuple[DirectProperGenreAnchorAbstention, ...]
    output_sha256: Sha256

    @model_validator(mode="after")
    def _complete_partition(self) -> DirectProperGenreAnchorProjection:
        if self.positioned_seed_count + self.unplaced_seed_count != self.retained_seed_count:
            raise ValueError("layout seed partition does not cover retained seed universe")
        proposed = {item.unplaced_seed_id for item in self.proposals}
        abstained = {item.unplaced_seed_id for item in self.abstentions}
        if proposed & abstained:
            raise ValueError("frontier seed cannot be both proposed and abstained")
        if len(proposed) != len(self.proposals) or len(abstained) != len(self.abstentions):
            raise ValueError("frontier outcomes must be unique per unplaced seed")
        if len(proposed | abstained) != self.proper_genre_frontier_seed_count:
            raise ValueError("frontier outcomes do not cover every proper-genre seed")
        return self


@dataclass(frozen=True, slots=True)
class _LayoutPartition:
    positioned: frozenset[str]
    unplaced: frozenset[str]
    output_sha256: str


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1_048_576), b""):
            digest.update(block)
    return digest.hexdigest()


def _projection_sha256(projection: DirectProperGenreAnchorProjection) -> str:
    return hashlib.sha256(
        _canonical(projection.model_dump(mode="json", exclude={"output_sha256"}))
    ).hexdigest()


def _layout_partition(path: Path) -> _LayoutPartition:
    """Read only seed IDs and the embedded hash; coordinate values never enter memory."""
    positioned: set[str] = set()
    unplaced: set[str] = set()
    output_sha256: str | None = None
    with path.open("rb") as stream:
        for prefix, event, value in ijson.parse(stream):
            if (
                prefix == "coordinates.item.seed_id"
                and event == "string"
                and isinstance(value, str)
            ):
                positioned.add(value)
            elif prefix == "unplaced.item.seed_id" and event == "string" and isinstance(value, str):
                unplaced.add(value)
            elif prefix == "output_sha256" and event == "string" and isinstance(value, str):
                output_sha256 = value
    if output_sha256 is None or len(output_sha256) != _SHA256_HEX_LENGTH:
        raise DirectProperGenreAnchorProjectionError("layout lacks output_sha256")
    if positioned & unplaced or len(positioned) + len(unplaced) != _RETAINED_SEED_COUNT:
        raise DirectProperGenreAnchorProjectionError("layout does not partition retained seed IDs")
    return _LayoutPartition(frozenset(positioned), frozenset(unplaced), output_sha256)


def build_direct_proper_genre_anchor_projection(
    *, custody_receipt_path: Path, custody_object_store: Path, layout_path: Path
) -> DirectProperGenreAnchorProjection:
    """Build a bounded seed-ID-only review projection from verified source custody."""
    receipt_bytes = custody_receipt_path.read_bytes()
    receipt = DirectProperGenreCustodyReceipt.model_validate_json(receipt_bytes)
    verify_portable_direct_proper_genre_custody(receipt, object_store=custody_object_store)
    layout = _layout_partition(layout_path)
    claims_by_seed_artist: dict[tuple[str, str], DirectProperGenreClaim] = {}
    seed_artists: dict[str, set[str]] = defaultdict(set)
    artist_seeds: dict[str, set[str]] = defaultdict(set)
    for claim in iter_verified_portable_direct_proper_genre_claims(
        receipt, object_store=custody_object_store
    ):
        key = (claim.seed_id, claim.artist_mbid)
        claims_by_seed_artist.setdefault(key, claim)
        seed_artists[claim.seed_id].add(claim.artist_mbid)
        artist_seeds[claim.artist_mbid].add(claim.seed_id)

    frontier = sorted(set(seed_artists) & layout.unplaced)
    proposals: list[DirectProperGenreAnchor] = []
    abstentions: list[DirectProperGenreAnchorAbstention] = []
    for seed_id in frontier:
        positioned_by_artist = {
            artist: artist_seeds[artist] & layout.positioned
            for artist in sorted(seed_artists[seed_id])
        }
        positioned_anchors = set().union(*positioned_by_artist.values())
        exclusive = {
            min(anchor_seeds)
            for artist, anchor_seeds in positioned_by_artist.items()
            if len(artist_seeds[artist]) == _EXCLUSIVE_ARTIST_SEED_COUNT and len(anchor_seeds) == 1
        }
        if len(positioned_anchors) == 0:
            reason = "no_positioned_artist_overlap"
        elif len(positioned_anchors) == 1 and len(exclusive) == 1:
            artist = next(
                artist
                for artist, anchor_seeds in sorted(positioned_by_artist.items())
                if len(artist_seeds[artist]) == _EXCLUSIVE_ARTIST_SEED_COUNT
                and anchor_seeds == exclusive
            )
            positioned_seed_id = min(exclusive)
            unplaced_claim = claims_by_seed_artist[(seed_id, artist)]
            positioned_claim = claims_by_seed_artist[(positioned_seed_id, artist)]
            proposals.append(
                DirectProperGenreAnchor(
                    unplaced_seed_id=seed_id,
                    positioned_seed_id=positioned_seed_id,
                    artist_mbid=artist,
                    unplaced_source_record_id=unplaced_claim.source_record_id,
                    unplaced_source_record_sha256=unplaced_claim.source_record_sha256,
                    unplaced_source_evidence_ref=unplaced_claim.source_evidence_ref,
                    positioned_source_record_id=positioned_claim.source_record_id,
                    positioned_source_record_sha256=positioned_claim.source_record_sha256,
                    positioned_source_evidence_ref=positioned_claim.source_evidence_ref,
                )
            )
            continue
        elif len(positioned_anchors) > 1:
            reason = "multiple_positioned_anchor_seeds"
        else:
            reason = "positioned_artist_overlap_not_exclusive"
        abstentions.append(
            DirectProperGenreAnchorAbstention(
                unplaced_seed_id=seed_id,
                reason=reason,
                positioned_anchor_seed_count=len(positioned_anchors),
                exclusive_positioned_anchor_seed_count=len(exclusive),
            )
        )
    base = DirectProperGenreAnchorProjection(
        custody_receipt_byte_sha256=hashlib.sha256(receipt_bytes).hexdigest(),
        custody_receipt_output_sha256=receipt.output_sha256,
        custody_object_sha256=receipt.claims_object_sha256,
        layout_byte_sha256=_sha256(layout_path),
        layout_embedded_output_sha256=layout.output_sha256,
        positioned_seed_count=len(layout.positioned),
        unplaced_seed_count=len(layout.unplaced),
        proper_genre_frontier_seed_count=len(frontier),
        proposals=tuple(proposals),
        abstentions=tuple(abstentions),
        output_sha256="0" * 64,
    )
    return base.model_copy(update={"output_sha256": _projection_sha256(base)})


def verify_direct_proper_genre_anchor_projection(
    projection: DirectProperGenreAnchorProjection,
) -> None:
    """Replay the self-hash and policy-bearing structural invariants."""
    if projection.output_sha256 != _projection_sha256(projection):
        raise DirectProperGenreAnchorProjectionError("projection output hash does not replay")
