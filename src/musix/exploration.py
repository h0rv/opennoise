"""Validated query and response values for catalog exploration."""

from datetime import datetime
from enum import StrEnum
from typing import Self

from pydantic import AwareDatetime, Field, FiniteFloat, model_validator

from musix.models import FrozenModel, MapPoint


class CatalogLens(StrEnum):
    """Entity kinds a map request can include."""

    ALL = "all"
    GENRES = "genres"


class LevelOfDetail(StrEnum):
    """Server-rendered detail included in a map fragment."""

    POINTS = "points"
    LABELS = "labels"


class Viewport(FrozenModel):
    """A finite rectangular region in layout coordinates."""

    minimum_x: FiniteFloat
    minimum_y: FiniteFloat
    maximum_x: FiniteFloat
    maximum_y: FiniteFloat

    @model_validator(mode="after")
    def require_ordered_bounds(self) -> Self:
        """Reject empty or inverted rectangles."""
        if self.minimum_x >= self.maximum_x or self.minimum_y >= self.maximum_y:
            msg = "viewport minimums must be less than maximums"
            raise ValueError(msg)
        return self

    def svg_view_box(self) -> str:
        """Return the equivalent SVG viewBox value."""
        return (
            f"{self.minimum_x} {self.minimum_y} "
            f"{self.maximum_x - self.minimum_x} {self.maximum_y - self.minimum_y}"
        )


class MapQuery(FrozenModel):
    """One bounded, reproducible map query."""

    layout_key: str = Field(default="default", min_length=1, max_length=100)
    lens: CatalogLens = CatalogLens.ALL
    level_of_detail: LevelOfDetail = LevelOfDetail.LABELS
    source_key: str | None = Field(default=None, min_length=1, max_length=100)
    observed_at_or_before: AwareDatetime | None = None
    viewport: Viewport | None = None
    limit: int = Field(default=10_000, ge=1, le=10_000)


class MapQueryResult(FrozenModel):
    """Map points plus the query that selected them."""

    query: MapQuery
    points: tuple[MapPoint, ...]
    truncated: bool


class ProvenanceEvidence(FrozenModel):
    """Policy-safe source evidence attached to an entity."""

    provenance_id: int
    source_key: str
    source_name: str
    snapshot_ref: str
    artifact_sha256: str | None
    parser_release_ref: str
    observed_at: datetime
    policy_classification: str
    fields: tuple[str, ...]
    is_primary: bool


class GenreDetail(FrozenModel):
    """A genre and the source evidence available for its fields."""

    entity_id: int
    slug: str
    name: str
    description: str | None
    evidence: tuple[ProvenanceEvidence, ...]


class ProvenanceResponse(FrozenModel):
    """Stable API response for entity provenance."""

    entity_id: int
    evidence: tuple[ProvenanceEvidence, ...]


def optional_viewport(
    minimum_x: float | None,
    minimum_y: float | None,
    maximum_x: float | None,
    maximum_y: float | None,
) -> Viewport | None:
    """Parse four optional bounds into either no viewport or one complete viewport."""
    bounds = (minimum_x, minimum_y, maximum_x, maximum_y)
    if all(bound is None for bound in bounds):
        return None
    if minimum_x is None or minimum_y is None or maximum_x is None or maximum_y is None:
        msg = "all four viewport bounds are required"
        raise ValueError(msg)
    return Viewport(
        minimum_x=minimum_x,
        minimum_y=minimum_y,
        maximum_x=maximum_x,
        maximum_y=maximum_y,
    )
