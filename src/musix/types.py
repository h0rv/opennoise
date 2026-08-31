"""Shared constrained scalar types with no project-layer dependencies."""

from typing import Annotated

from pydantic import Field

type Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
type SourceId = Annotated[str, Field(min_length=1)]
type ExternalId = Annotated[str, Field(min_length=1)]
