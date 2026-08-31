"""Strict common catalog projections emitted by source adapters."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from musix.types import ExternalId


class _FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")


class NameClaim(_FrozenModel):
    """Represent one source-supported entity name."""

    kind: Literal["primary", "alias", "sort"]
    value: str = Field(min_length=1)
    language_tag: str = Field(default="und", min_length=1)


class IdentifierClaim(_FrozenModel):
    """Represent one source-supported external identifier."""

    type_key: str = Field(min_length=1)
    namespace: str
    value: str = Field(min_length=1)


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


type CatalogProjection = ArtistProjection


class ProjectionResult(_FrozenModel):
    """Report one normalized catalog projection write."""

    projection_kind: str = Field(min_length=1)
    target_id: int = Field(gt=0)
    duplicate: bool
