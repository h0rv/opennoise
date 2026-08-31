"""Shared constrained scalar types with no project-layer dependencies."""

from typing import Annotated, Literal

from pydantic import Field

type Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
type SourceId = Annotated[str, Field(min_length=1)]
type ExternalId = Annotated[str, Field(min_length=1)]
type EntityKind = Literal["genre", "artist", "release_group", "recording", "work"]
type StatementRank = Literal["preferred", "normal"]
type MusicBrainzArtistId = Annotated[
    str,
    Field(
        pattern=r"^musicbrainz:artist:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
    ),
]
