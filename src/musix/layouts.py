"""Versioned interfaces for replaceable layout strategies."""

from collections.abc import Mapping
from datetime import datetime
from typing import Annotated, Literal, Protocol

from pydantic import Field, JsonValue

from musix.exploration import MapQuery, Viewport
from musix.models import FrozenModel, MapPoint, MapPointResponse


class HistoricCoordinateSpace(FrozenModel):
    """Coordinates copied from a pinned historical source artifact."""

    coordinate_kind: Literal["historic_source"] = "historic_source"
    source_ref: str = Field(min_length=1)
    units: str = Field(min_length=1)


class DerivedCoordinateSpace(FrozenModel):
    """Coordinates computed by a versioned layout strategy."""

    coordinate_kind: Literal["derived"] = "derived"
    units: str = Field(min_length=1)


type CoordinateSpace = Annotated[
    HistoricCoordinateSpace | DerivedCoordinateSpace,
    Field(discriminator="coordinate_kind"),
]


class LayoutStrategyVersion(FrozenModel):
    """A stable key and revision for one layout implementation."""

    key: str = Field(min_length=1, max_length=100)
    revision: str = Field(min_length=1, max_length=200)


class LayoutBuildRequest(FrozenModel):
    """Typed inputs supplied to a layout strategy."""

    layout_key: str = Field(min_length=1, max_length=100)
    input_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    entities: tuple[int, ...]
    parameters: dict[str, JsonValue] = Field(default_factory=dict)
    random_seed: int | None = None


class LayoutArtifactMetadata(FrozenModel):
    """Metadata required to reproduce and compare one layout artifact."""

    layout_key: str
    revision: int
    strategy: LayoutStrategyVersion
    parameters: dict[str, JsonValue]
    input_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    random_seed: int | None
    status: str
    policy_id: int
    created_at: datetime
    completed_at: datetime | None
    point_count: int = Field(ge=0)
    bounds: Viewport | None
    coordinate_space: CoordinateSpace


class PublishedLayout(FrozenModel):
    """One selectable layout backed by a currently published run."""

    layout_key: str = Field(min_length=1, max_length=100)
    point_count: int = Field(gt=0)
    coordinate_space: CoordinateSpace

    @property
    def label(self) -> str:
        """Return a compact product label without exposing an internal method key."""
        labels = {
            "public": "Related",
            "public-direct": "Direct",
            "public-community": "Communities",
            "public-taxonomy": "Taxonomy",
        }
        return labels.get(self.layout_key, self.layout_key.replace("_", " ").replace("-", " "))


class LayoutArtifact(FrozenModel):
    """A complete strategy output before it is stored or published."""

    metadata: LayoutArtifactMetadata
    points: tuple[MapPoint, ...]


class ExploredMap(FrozenModel):
    """A bounded map API response with reproducibility metadata."""

    query: MapQuery
    layout: LayoutArtifactMetadata | None
    bounds: Viewport | None
    points: tuple[MapPointResponse, ...]
    truncated: bool


class LayoutStrategy(Protocol):
    """Interface implemented by independently versioned layout methods."""

    @property
    def version(self) -> LayoutStrategyVersion:
        """Return the implementation identity recorded with every run."""
        ...

    def build(
        self,
        request: LayoutBuildRequest,
        features: Mapping[int, tuple[float, ...]],
    ) -> LayoutArtifact:
        """Build one deterministic artifact from explicit inputs."""
        ...
