"""Strict common catalog projections emitted by source adapters."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from musix.types import EntityKind, ExternalId, StatementRank


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
        """Expose the source-local identity for shared lifecycle partitioning."""
        return self.source_identity.value


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


type CatalogProjection = ArtistProjection | EntityProjection


class ProjectionResult(_FrozenModel):
    """Report one normalized catalog projection write."""

    projection_kind: str = Field(min_length=1)
    target_id: int = Field(gt=0)
    duplicate: bool
