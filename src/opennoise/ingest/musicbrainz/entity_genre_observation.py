"""Parse local MusicBrainz entity genre observations without artist propagation.

The MusicBrainz response remains the source of each observation.  A recording,
release, and release group are distinct entities, and tags remain distinct from
proper MusicBrainz genres.  This module does not read artist credits and cannot
produce artist membership rows.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import TYPE_CHECKING, Final, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

if TYPE_CHECKING:
    from pathlib import Path

_REVISION: Final = "musicbrainz-entity-genre-observation-v1"
_SHA256: Final = r"^[0-9a-f]{64}$"

type EntityKind = Literal["recording", "release", "release_group"]
type GenreFacet = Literal["musicbrainz_genre", "musicbrainz_tag"]


class _FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")


class _ApiModel(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True, extra="ignore")


class EntityGenreObservationError(ValueError):
    """A retained entity response cannot support a local observation."""


class MusicBrainzGenre(_ApiModel):
    """One proper MusicBrainz genre in an entity response."""

    id: UUID
    name: str = Field(min_length=1)
    count: int = Field(ge=0)


class MusicBrainzTag(_ApiModel):
    """One community tag in an entity response, with its positive vote count."""

    name: str = Field(min_length=1)
    count: int | None = Field(default=None, ge=0)


class _ReleaseGroupReference(_ApiModel):
    id: UUID


class _EntityResponse(_ApiModel):
    id: UUID
    genres: tuple[MusicBrainzGenre, ...] = Field(default=(), max_length=512)
    tags: tuple[MusicBrainzTag, ...] = Field(default=(), max_length=2_000)


class _ReleaseResponse(_EntityResponse):
    release_group: _ReleaseGroupReference = Field(alias="release-group")


class EntityGenreSourceReceipt(_FrozenModel):
    """A row-level receipt for one retained MusicBrainz entity response."""

    source_partition: str = Field(min_length=1)
    source_snapshot: str = Field(min_length=1)
    entity_kind: EntityKind
    entity_mbid: UUID
    request_url: str = Field(min_length=1)
    response_sha256: str = Field(pattern=_SHA256)


_BOUNDED_SOURCE_PARTITION: Final = "musicbrainz_ws2_entity_genre_research_20260923"
_BOUNDED_SOURCE_SNAPSHOT: Final = "20260923-local-entity-genre-query-001"
BOUNDED_ENTITY_GENRE_RECEIPTS: Final = (
    EntityGenreSourceReceipt(
        source_partition=_BOUNDED_SOURCE_PARTITION,
        source_snapshot=_BOUNDED_SOURCE_SNAPSHOT,
        entity_kind="recording",
        entity_mbid=UUID("00526a18-e31d-4b1f-bc6a-c6c7e318694d"),
        request_url="https://musicbrainz.org/ws/2/recording/00526a18-e31d-4b1f-bc6a-c6c7e318694d?fmt=json&inc=genres%2Btags",
        response_sha256="255555b3b19de92d58e286d1816c773de82d05a8a1f0ed1dbee1809e759c8818",
    ),
    EntityGenreSourceReceipt(
        source_partition=_BOUNDED_SOURCE_PARTITION,
        source_snapshot=_BOUNDED_SOURCE_SNAPSHOT,
        entity_kind="recording",
        entity_mbid=UUID("0065d575-27e6-4151-a489-4ecc4afb9974"),
        request_url="https://musicbrainz.org/ws/2/recording/0065d575-27e6-4151-a489-4ecc4afb9974?fmt=json&inc=genres%2Btags",
        response_sha256="206926c81e0f0517c0f238573f54d058d505e912b43968f268293c5679229cd9",
    ),
    EntityGenreSourceReceipt(
        source_partition=_BOUNDED_SOURCE_PARTITION,
        source_snapshot=_BOUNDED_SOURCE_SNAPSHOT,
        entity_kind="recording",
        entity_mbid=UUID("0078b7fc-f0cd-4496-ad71-0235f955fa3b"),
        request_url="https://musicbrainz.org/ws/2/recording/0078b7fc-f0cd-4496-ad71-0235f955fa3b?fmt=json&inc=genres%2Btags",
        response_sha256="d4081e97cfe0b812e34a8cd7530c06982d819b2ed0b80ed5d85d086b5870f0f8",
    ),
    EntityGenreSourceReceipt(
        source_partition=_BOUNDED_SOURCE_PARTITION,
        source_snapshot=_BOUNDED_SOURCE_SNAPSHOT,
        entity_kind="recording",
        entity_mbid=UUID("008d0bdd-e3e1-469a-9531-2cb5ef8eb109"),
        request_url="https://musicbrainz.org/ws/2/recording/008d0bdd-e3e1-469a-9531-2cb5ef8eb109?fmt=json&inc=genres%2Btags",
        response_sha256="7cdc71c5e932b7730f59cf013b45aa0050ed7b65c0c86c6f1e7402c68e0018a1",
    ),
    EntityGenreSourceReceipt(
        source_partition=_BOUNDED_SOURCE_PARTITION,
        source_snapshot=_BOUNDED_SOURCE_SNAPSHOT,
        entity_kind="release",
        entity_mbid=UUID("018a6ac2-e74f-4874-9b42-7add11ba6ddf"),
        request_url="https://musicbrainz.org/ws/2/release/018a6ac2-e74f-4874-9b42-7add11ba6ddf?fmt=json&inc=genres%2Btags%2Brelease-groups",
        response_sha256="c3382e3557824db78b6cbcbe084919a8f37eb9c2abf1fa7652c0c06ca7c56cfa",
    ),
    EntityGenreSourceReceipt(
        source_partition=_BOUNDED_SOURCE_PARTITION,
        source_snapshot=_BOUNDED_SOURCE_SNAPSHOT,
        entity_kind="release",
        entity_mbid=UUID("03118dd6-5252-489f-a934-4304a92972c1"),
        request_url="https://musicbrainz.org/ws/2/release/03118dd6-5252-489f-a934-4304a92972c1?fmt=json&inc=genres%2Btags%2Brelease-groups",
        response_sha256="224cc8fcfb4dbbebccbccd08af735e5de8350c6e73ea53ccceb1843a6c12f934",
    ),
    EntityGenreSourceReceipt(
        source_partition=_BOUNDED_SOURCE_PARTITION,
        source_snapshot=_BOUNDED_SOURCE_SNAPSHOT,
        entity_kind="release",
        entity_mbid=UUID("03288a74-b855-4274-a5ec-e48e72d6451b"),
        request_url="https://musicbrainz.org/ws/2/release/03288a74-b855-4274-a5ec-e48e72d6451b?fmt=json&inc=genres%2Btags%2Brelease-groups",
        response_sha256="be018bcfd894f8a693ba8eb0941edb98bb6c6b21950516a14db00d7026e2d37d",
    ),
    EntityGenreSourceReceipt(
        source_partition=_BOUNDED_SOURCE_PARTITION,
        source_snapshot=_BOUNDED_SOURCE_SNAPSHOT,
        entity_kind="release_group",
        entity_mbid=UUID("005909de-978b-3450-a820-c89b7dae787a"),
        request_url="https://musicbrainz.org/ws/2/release-group/005909de-978b-3450-a820-c89b7dae787a?fmt=json&inc=genres%2Btags",
        response_sha256="62324163ec202cb59b5f2b27e215a6848836d75c41865bea80ddfda8dfcf5015",
    ),
    EntityGenreSourceReceipt(
        source_partition=_BOUNDED_SOURCE_PARTITION,
        source_snapshot=_BOUNDED_SOURCE_SNAPSHOT,
        entity_kind="release_group",
        entity_mbid=UUID("02adb8a7-496c-3a9a-a324-662df73fdba5"),
        request_url="https://musicbrainz.org/ws/2/release-group/02adb8a7-496c-3a9a-a324-662df73fdba5?fmt=json&inc=genres%2Btags",
        response_sha256="645e49770763e2ae9c41bb676eecd63da2d5ebcb4a60a2c43e465814bbc0e6b5",
    ),
    EntityGenreSourceReceipt(
        source_partition=_BOUNDED_SOURCE_PARTITION,
        source_snapshot=_BOUNDED_SOURCE_SNAPSHOT,
        entity_kind="release_group",
        entity_mbid=UUID("04de5d0b-1e38-4890-93a3-34bc5fdda4dc"),
        request_url="https://musicbrainz.org/ws/2/release-group/04de5d0b-1e38-4890-93a3-34bc5fdda4dc?fmt=json&inc=genres%2Btags",
        response_sha256="2ff0fb21faebc332c2d2e703cb21516692192f70d168af022fe3b3f14616396d",
    ),
)


class RetainedEntityGenreResponse(_FrozenModel):
    """Verified raw response bytes and the receipt that identifies them."""

    receipt: EntityGenreSourceReceipt
    payload: bytes = Field(min_length=2)

    @model_validator(mode="after")
    def receipt_matches_bytes(self) -> RetainedEntityGenreResponse:
        """Require the receipt to identify the exact retained bytes."""
        if hashlib.sha256(self.payload).hexdigest() != self.receipt.response_sha256:
            raise ValueError("entity response SHA-256 does not match its receipt")
        return self


class EntityGenreObservation(_FrozenModel):
    """One native entity observation with no artist or membership fields."""

    entity_kind: EntityKind
    entity_mbid: UUID
    release_group_mbid: UUID | None = None
    facet: GenreFacet
    label: str = Field(min_length=1)
    genre_mbid: UUID | None = None
    genre_vote_count: int | None = Field(default=None, ge=0)
    tag_vote_count: int | None = Field(default=None, gt=0)
    source_receipt: EntityGenreSourceReceipt
    artist_membership_propagated: Literal[False] = False

    @model_validator(mode="after")
    def native_entity_and_facet_are_consistent(self) -> EntityGenreObservation:
        """Keep the entity identity and the two source facets separate."""
        if self.source_receipt.entity_kind != self.entity_kind:
            raise ValueError("source receipt entity kind does not match observation")
        if self.source_receipt.entity_mbid != self.entity_mbid:
            raise ValueError("source receipt entity ID does not match observation")
        if self.entity_kind == "release" and self.release_group_mbid is None:
            raise ValueError("release observations require their exact release group ID")
        if self.entity_kind != "release" and self.release_group_mbid is not None:
            raise ValueError("only a release observation may carry a parent release group ID")
        if self.facet == "musicbrainz_genre":
            if (
                self.genre_mbid is None
                or self.genre_vote_count is None
                or self.tag_vote_count is not None
            ):
                raise ValueError("proper genre observations require only genre identity and count")
        elif (
            self.genre_mbid is not None
            or self.genre_vote_count is not None
            or self.tag_vote_count is None
        ):
            raise ValueError("tag observations require only a positive tag count")
        return self


class EntityGenreObservationReport(_FrozenModel):
    """A hash-sealed local-only collection of native MusicBrainz observations."""

    revision: Literal["musicbrainz-entity-genre-observation-v1"] = _REVISION
    export_allowed: Literal[False] = False
    serving_allowed: Literal[False] = False
    artist_membership_propagation_allowed: Literal[False] = False
    source_receipts: tuple[EntityGenreSourceReceipt, ...] = Field(min_length=1)
    observations: tuple[EntityGenreObservation, ...]
    genre_observation_count: int = Field(ge=0)
    tag_observation_count: int = Field(ge=0)
    output_sha256: str = Field(pattern=_SHA256)

    @model_validator(mode="after")
    def counts_match_observations(self) -> EntityGenreObservationReport:
        """Require declared facet counts and receipt ordering to replay."""
        if self.genre_observation_count != sum(
            item.facet == "musicbrainz_genre" for item in self.observations
        ):
            raise ValueError("proper genre count does not match observations")
        if self.tag_observation_count != sum(
            item.facet == "musicbrainz_tag" for item in self.observations
        ):
            raise ValueError("tag count does not match observations")
        if tuple(sorted(self.source_receipts, key=_receipt_key)) != self.source_receipts:
            raise ValueError("source receipts must have a stable order")
        return self


def _receipt_key(receipt: EntityGenreSourceReceipt) -> tuple[str, str, str, str]:
    return (
        receipt.source_partition,
        receipt.source_snapshot,
        receipt.entity_kind,
        str(receipt.entity_mbid),
    )


def _logical_sha256(report: EntityGenreObservationReport) -> str:
    payload = report.model_dump(mode="json", exclude={"output_sha256"})
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()


def verify_entity_genre_observation_report(report: EntityGenreObservationReport) -> None:
    """Fail closed when a persisted local observation report no longer replays."""
    if _logical_sha256(report) != report.output_sha256:
        raise EntityGenreObservationError("entity genre observation report hash does not replay")


def write_local_report_once(*, cache_root: Path, output: Path, payload: bytes) -> None:
    """Create one report under its local cache root without replacing any file."""
    if not output.resolve().is_relative_to(cache_root.resolve()):
        raise EntityGenreObservationError("entity genre reports may only be written under .cache")
    if output.exists() or output.is_symlink():
        raise EntityGenreObservationError("entity genre report already exists")
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("xb") as stream:
        stream.write(payload)


def _parse_response(retained: RetainedEntityGenreResponse) -> _EntityResponse:
    try:
        match retained.receipt.entity_kind:
            case "release":
                parsed: _EntityResponse = _ReleaseResponse.model_validate_json(retained.payload)
            case "recording" | "release_group":
                parsed = _EntityResponse.model_validate_json(retained.payload)
    except ValueError as error:
        raise EntityGenreObservationError(
            "retained entity response is not a valid MusicBrainz payload"
        ) from error
    if parsed.id != retained.receipt.entity_mbid:
        raise EntityGenreObservationError("response entity ID does not match its receipt")
    return parsed


def _observations_for_response(
    retained: RetainedEntityGenreResponse,
) -> tuple[EntityGenreObservation, ...]:
    parsed = _parse_response(retained)
    release_group_mbid = parsed.release_group.id if isinstance(parsed, _ReleaseResponse) else None
    observations = [
        EntityGenreObservation(
            entity_kind=retained.receipt.entity_kind,
            entity_mbid=parsed.id,
            release_group_mbid=release_group_mbid,
            facet="musicbrainz_genre",
            label=genre.name,
            genre_mbid=genre.id,
            genre_vote_count=genre.count,
            source_receipt=retained.receipt,
        )
        for genre in parsed.genres
    ]
    observations.extend(
        EntityGenreObservation(
            entity_kind=retained.receipt.entity_kind,
            entity_mbid=parsed.id,
            release_group_mbid=release_group_mbid,
            facet="musicbrainz_tag",
            label=tag.name,
            tag_vote_count=tag.count,
            source_receipt=retained.receipt,
        )
        for tag in parsed.tags
        if tag.count is not None and tag.count > 0
    )
    return tuple(observations)


def build_entity_genre_observation_report(
    retained_responses: tuple[RetainedEntityGenreResponse, ...],
) -> EntityGenreObservationReport:
    """Build a deterministic local-only report from checksum-verified responses."""
    if not retained_responses:
        raise EntityGenreObservationError("at least one retained entity response is required")
    receipts = tuple(sorted((item.receipt for item in retained_responses), key=_receipt_key))
    if len(set(receipts)) != len(receipts):
        raise EntityGenreObservationError("retained entity responses repeat a source receipt")
    observations = tuple(
        item
        for retained in sorted(retained_responses, key=lambda item: _receipt_key(item.receipt))
        for item in _observations_for_response(retained)
    )
    identity = tuple(
        (
            item.entity_kind,
            item.entity_mbid,
            item.facet,
            item.genre_mbid if item.genre_mbid is not None else item.label.casefold(),
        )
        for item in observations
    )
    if len(set(identity)) != len(identity):
        raise EntityGenreObservationError("one entity response repeats a genre or tag observation")
    unsealed = EntityGenreObservationReport(
        source_receipts=receipts,
        observations=observations,
        genre_observation_count=sum(item.facet == "musicbrainz_genre" for item in observations),
        tag_observation_count=sum(item.facet == "musicbrainz_tag" for item in observations),
        output_sha256="0" * 64,
    )
    return unsealed.model_copy(update={"output_sha256": _logical_sha256(unsealed)})
