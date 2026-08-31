"""Strict ListenBrainz source-boundary models."""

from typing import Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field


class _ListenBrainzBoundaryModel(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True, extra="ignore")


class ListenMbidMapping(_ListenBrainzBoundaryModel):
    """Parse server-resolved MusicBrainz artist identifiers when present."""

    artist_mbids: tuple[str, ...] = ()


class ListenAdditionalInfo(_ListenBrainzBoundaryModel):
    """Parse MusicBrainz identifiers carried by the official listen dump."""

    artist_mbids: tuple[str, ...] = ()


class ListenTrackMetadata(_ListenBrainzBoundaryModel):
    """Discard submitted names and retain only source-qualified identifiers."""

    mbid_mapping: ListenMbidMapping | None = None
    additional_info: ListenAdditionalInfo | None = None


class ListenBrainzListen(_ListenBrainzBoundaryModel):
    """Parse the minimum official JSON listen shape used by aggregation."""

    listened_at: int = Field(
        validation_alias=AliasChoices("timestamp", "listened_at"),
        ge=0,
    )
    user_id: int = Field(ge=0)
    track_metadata: ListenTrackMetadata


class ListenBrainzAggregationConfig(BaseModel):
    """Choose explicit fixed windows, privacy floor, ordering, and state limits."""

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    ordering: Literal["newest_first"] = "newest_first"
    window_seconds: int = Field(default=86_400, gt=0)
    minimum_distinct_users: int = Field(default=2, gt=0)
    max_users_per_window: int = Field(default=2_000_000, gt=0)
    max_artists_per_user_window: int = Field(default=1_000, gt=1)
    max_distinct_artists: int = Field(default=5_000_000, gt=1)
    max_pairs_per_window: int = Field(default=10_000_000, gt=0)
    max_listen_members: int = Field(default=16, gt=0)
