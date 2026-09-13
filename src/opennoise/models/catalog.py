"""Strict common catalog projections emitted by source adapters."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from opennoise.types import EntityKind, ExternalId, MusicBrainzArtistId, Sha256, StatementRank


class _FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")


class NameClaim(_FrozenModel):
    """Represent one source-supported entity name."""

    kind: Literal["primary", "alias", "sort"]
    value: str = Field(min_length=1)
    language_tag: str = Field(default="und", min_length=1)
    script_code: str | None = Field(default=None, min_length=4, max_length=4)


class IdentifierClaim(_FrozenModel):
    """Represent one source-supported external identifier."""

    type_key: str = Field(min_length=1)
    namespace: str
    value: str = Field(min_length=1)


class ExternalIdentity(_FrozenModel):
    """Identify an object only inside an explicit source namespace."""

    namespace: str = Field(min_length=1)
    value: ExternalId


class StatementReference(_FrozenModel):
    """Preserve one source-local reference node and optional cited URL."""

    identity: ExternalIdentity
    url: str | None = None


class ValueClaim(_FrozenModel):
    """Represent a typed scalar source statement."""

    claim_kind: Literal["value"] = "value"
    property_key: str = Field(min_length=1)
    value_kind: Literal["time", "string"]
    value: str = Field(min_length=1)
    statement_id: ExternalIdentity | None = None
    rank: StatementRank = "normal"
    references: tuple[StatementReference, ...] = ()


class RelationClaim(_FrozenModel):
    """Keep a relation target source-local until explicit identity resolution."""

    claim_kind: Literal["relation"] = "relation"
    property_key: str = Field(min_length=1)
    target: ExternalIdentity
    target_kind: EntityKind | Literal["unresolved"] = "unresolved"
    statement_id: ExternalIdentity | None = None
    rank: StatementRank = "normal"
    references: tuple[StatementReference, ...] = ()


type EvidenceClaim = Annotated[ValueClaim | RelationClaim, Field(discriminator="claim_kind")]


class EntityProjection(_FrozenModel):
    """Project one source object and its evidence without guessing identity."""

    projection_kind: Literal["entity"] = "entity"
    entity_kind: EntityKind
    source_identity: ExternalIdentity
    names: tuple[NameClaim, ...] = Field(min_length=1)
    identifiers: tuple[IdentifierClaim, ...] = ()
    claims: tuple[EvidenceClaim, ...] = ()

    @property
    def external_id(self) -> ExternalId:
        """Return a stable namespace-qualified ID for shared pipeline partitioning."""
        return f"{self.source_identity.namespace}:{self.source_identity.value}"


class GenreMembershipClaim(_FrozenModel):
    """Represent one positive, source-qualified genre association count."""

    source_identity: ExternalIdentity
    name: str = Field(min_length=1)
    support_count: int = Field(gt=0)


class ArtistProjection(_FrozenModel):
    """Represent common artist facts projected from an upstream record."""

    projection_kind: Literal["artist"] = "artist"
    entity_kind: Literal["artist"] = "artist"
    external_id: ExternalId
    names: tuple[NameClaim, ...] = Field(min_length=1)
    identifiers: tuple[IdentifierClaim, ...] = Field(min_length=1)
    artist_kind: str | None = None
    disambiguation: str | None = None
    begin_year: int | None = Field(default=None, ge=1, le=9999)
    end_year: int | None = Field(default=None, ge=1, le=9999)
    genre_claims: tuple[GenreMembershipClaim, ...] = Field(default=(), max_length=128)
    tag_claims: tuple[GenreMembershipClaim, ...] = Field(default=(), max_length=512)


class ArtistCreditMemberClaim(_FrozenModel):
    """Identify one ordered credited artist without name-based reconciliation."""

    artist_identity: ExternalIdentity
    artist_name: str = Field(min_length=1)
    credited_name: str = Field(min_length=1)
    join_phrase: str = Field(default="", max_length=100)


class ReleaseGroupProjection(_FrozenModel):
    """Represent the bounded MusicBrainz album-level metadata used by discovery."""

    projection_kind: Literal["release_group"] = "release_group"
    entity_kind: Literal["release_group"] = "release_group"
    external_id: ExternalId
    names: tuple[NameClaim, ...] = Field(min_length=1)
    identifiers: tuple[IdentifierClaim, ...] = Field(min_length=1)
    primary_type: str | None = None
    secondary_types: tuple[str, ...] = Field(default=(), max_length=32)
    first_release_date: str | None = Field(default=None, max_length=10)
    artist_credit: tuple[ArtistCreditMemberClaim, ...] = Field(min_length=1, max_length=128)
    genre_claims: tuple[GenreMembershipClaim, ...] = Field(default=(), max_length=128)


class RecordingProjection(_FrozenModel):
    """Represent MusicBrainz recording identity and discovery metadata, never media."""

    projection_kind: Literal["recording"] = "recording"
    entity_kind: Literal["recording"] = "recording"
    external_id: ExternalId
    names: tuple[NameClaim, ...] = Field(min_length=1)
    identifiers: tuple[IdentifierClaim, ...] = Field(min_length=1)
    disambiguation: str | None = None
    first_release_date: str | None = Field(default=None, max_length=10)
    artist_credit: tuple[ArtistCreditMemberClaim, ...] = Field(min_length=1, max_length=128)
    genre_claims: tuple[GenreMembershipClaim, ...] = Field(default=(), max_length=128)


class ArtistCoListenProjection(_FrozenModel):
    """Represent source evidence before any similarity function or weighting."""

    projection_kind: Literal["artist_co_listen"] = "artist_co_listen"
    external_id: ExternalId
    left_artist_source_id: MusicBrainzArtistId
    right_artist_source_id: MusicBrainzArtistId
    window_start: int = Field(ge=0)
    window_end: int = Field(gt=0)
    distinct_user_count: int = Field(gt=0)


class ArtistCoListenRunProjection(_FrozenModel):
    """Report complete source coverage after all transient listener state is gone."""

    projection_kind: Literal["artist_co_listen_run"] = "artist_co_listen_run"
    external_id: ExternalId
    adapter_key: str = Field(min_length=1)
    adapter_version: str = Field(min_length=1)
    adapter_build_sha256: Sha256
    aggregation_version: str = Field(min_length=1)
    configuration_sha256: Sha256
    window_seconds: int = Field(gt=0)
    minimum_distinct_users: int = Field(gt=0)
    listens_seen: int = Field(ge=0)
    listens_with_artist_mbid: int = Field(ge=0)
    distinct_artists: int = Field(ge=0)
    user_windows: int = Field(ge=0)
    candidate_pairs: int = Field(ge=0)
    emitted_pairs: int = Field(ge=0)
    quarantined_records: int = Field(ge=0)
    minimum_listened_at: int | None = Field(default=None, ge=0)
    maximum_listened_at: int | None = Field(default=None, ge=0)
    elapsed_ms: int = Field(ge=0)
    peak_rss_bytes: int = Field(ge=0)


type CatalogProjection = (
    ArtistProjection
    | ReleaseGroupProjection
    | RecordingProjection
    | EntityProjection
    | ArtistCoListenProjection
    | ArtistCoListenRunProjection
)


class ProjectionResult(_FrozenModel):
    """Report one normalized catalog projection write."""

    projection_kind: str = Field(min_length=1)
    target_id: int = Field(gt=0)
    duplicate: bool
