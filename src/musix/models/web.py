"""Validated settings and web response models."""

from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

type GenrePlacementReason = Literal["no_direct_membership", "no_hierarchy_relation"]


class FrozenModel(BaseModel):
    """Base for immutable values parsed at system boundaries."""

    model_config = ConfigDict(frozen=True, strict=True)


class Settings(BaseSettings):
    """Process settings read once at startup."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    host: str = Field(default="127.0.0.1", validation_alias="HOST")
    port: int = Field(default=3001, ge=1, le=65535, validation_alias="PORT")
    database_path: Path = Field(
        default=Path("data/musix.sqlite"), validation_alias="MUSIX_DATABASE_PATH"
    )
    vault_path: Path = Field(default=Path("data/vault"), validation_alias="MUSIX_VAULT_PATH")
    production_map_path: Path | None = Field(
        default=None, validation_alias="MUSIX_PRODUCTION_MAP_PATH"
    )
    historical_signal_map_path: Path | None = Field(
        default=None, validation_alias="MUSIX_HISTORICAL_SIGNAL_MAP_PATH"
    )
    historical_membership_database_path: Path | None = Field(
        default=None, validation_alias="MUSIX_HISTORICAL_MEMBERSHIP_DATABASE_PATH"
    )
    open_construction_graph_path: Path | None = Field(
        default=Path(__file__).resolve().parents[3] / "data/model/open-construction-graph-v1.json",
        validation_alias="MUSIX_OPEN_CONSTRUCTION_GRAPH_PATH",
    )
    open_construction_graph_v2_path: Path | None = Field(
        default=None,
        validation_alias="MUSIX_OPEN_CONSTRUCTION_GRAPH_V2_PATH",
    )


class SearchHit(FrozenModel):
    """One policy-safe catalog search result."""

    entity_id: int
    entity_kind: str
    name: str


class MapPoint(FrozenModel):
    """One entity in a published map layout."""

    entity_id: int
    entity_kind: str
    name: str
    x: float
    y: float
    display_weight: float | None
    color_hex: str | None


class SearchHitResponse(FrozenModel):
    """Stable JSON shape for one search hit."""

    id: int
    kind: str
    name: str


class SearchResponse(FrozenModel):
    """Validated search API response."""

    hits: tuple[SearchHitResponse, ...]


class MapPointResponse(FrozenModel):
    """Stable JSON shape for one map point."""

    id: int
    kind: str
    name: str
    x: float
    y: float
    weight: float | None
    color: str | None


class MapResponse(FrozenModel):
    """Validated map API response."""

    points: tuple[MapPointResponse, ...]


class LegacyMapResponse(FrozenModel):
    """Declare that the endpoint is using the legacy SQLite layout fallback."""

    source: Literal["legacy-layout"] = "legacy-layout"
    fallback: Literal[True] = True
    points: tuple[MapPointResponse, ...]


class MapView(FrozenModel):
    """Computed SVG bounds and points for a server-rendered map."""

    points: tuple[MapPoint, ...]
    view_box: str
    view_width: float
    view_height: float
    focused_entity_id: int | None = None
    show_labels: bool = True
    label_entity_ids: tuple[int, ...] = ()
    detail_label_entity_ids: tuple[int, ...] = ()
    horizontal_midpoint: float = 50.0


MAP_LABEL_PROFILE = (48, 11.0)
MAP_DETAIL_LABEL_PROFILE = (160, 7.0)


def _label_entity_ids(
    points: list[MapPoint],
    focused_entity_id: int | None,
    *,
    show_labels: bool,
    profile: tuple[int, float] = MAP_LABEL_PROFILE,
) -> tuple[int, ...]:
    if not show_labels:
        return ()
    if not points:
        return ()
    budget, font_size = profile
    ordered_points = sorted(
        points,
        key=lambda point: (
            point.entity_id != focused_entity_id,
            -(point.display_weight or 0.0),
            point.name.casefold(),
            point.entity_id,
        ),
    )
    minimum_x = min(point.x for point in ordered_points)
    maximum_x = max(point.x for point in ordered_points)
    horizontal_midpoint = minimum_x + (maximum_x - minimum_x) / 2
    accepted_bounds: list[tuple[float, float, float, float]] = []
    selected: list[int] = []
    for point in ordered_points:
        label_width = max(20.0, min(len(point.name), 42) * font_size * 0.58)
        label_left = point.x - 8.0 - label_width if point.x > horizontal_midpoint else point.x + 8.0
        bounds = (
            label_left - 4.0,
            point.y - font_size,
            label_left + label_width + 4.0,
            point.y + font_size * 0.5,
        )
        if any(
            bounds[0] < other[2]
            and bounds[2] > other[0]
            and bounds[1] < other[3]
            and bounds[3] > other[1]
            for other in accepted_bounds
        ):
            continue
        accepted_bounds.append(bounds)
        selected.append(point.entity_id)
        if len(selected) == budget:
            break
    return tuple(selected)


class GenrePlacement(FrozenModel):
    """Describe whether one selected genre appears in the active layout."""

    layout_key: str = Field(min_length=1, max_length=100)
    placed: bool
    reason_key: GenrePlacementReason | None = None

    @model_validator(mode="after")
    def require_reason_only_when_unplaced(self) -> Self:
        """Keep placement state and an optional model reason consistent."""
        if self.placed and self.reason_key is not None:
            raise ValueError("a placed genre cannot have an unplaced reason")
        return self


def map_view(
    points: list[MapPoint],
    focused_entity_id: int | None = None,
    *,
    view_box: str | None = None,
    show_labels: bool = True,
) -> MapView:
    """Compute padded SVG bounds for a sequence of map points."""
    overview_labels = _label_entity_ids(points, focused_entity_id, show_labels=show_labels)
    detail_labels = _label_entity_ids(
        points,
        focused_entity_id,
        show_labels=show_labels,
        profile=MAP_DETAIL_LABEL_PROFILE,
    )
    detail_labels = tuple(dict.fromkeys((*overview_labels, *detail_labels)))
    if view_box is not None:
        _, _, view_width, view_height = (float(value) for value in view_box.split())
        return MapView(
            points=tuple(points),
            view_box=view_box,
            view_width=view_width,
            view_height=view_height,
            focused_entity_id=focused_entity_id,
            show_labels=show_labels,
            label_entity_ids=overview_labels,
            detail_label_entity_ids=detail_labels,
            horizontal_midpoint=float(view_box.split()[0]) + view_width / 2,
        )
    if not points:
        return MapView(
            points=(),
            view_box="0 0 100 100",
            view_width=100.0,
            view_height=100.0,
            focused_entity_id=focused_entity_id,
            show_labels=show_labels,
            label_entity_ids=(),
            detail_label_entity_ids=(),
            horizontal_midpoint=50.0,
        )
    minimum_x = min(point.x for point in points)
    maximum_x = max(point.x for point in points)
    minimum_y = min(point.y for point in points)
    maximum_y = max(point.y for point in points)
    span_x = max(maximum_x - minimum_x, 1.0)
    span_y = max(maximum_y - minimum_y, 1.0)
    padding_left = max(span_x * 0.04, 40.0)
    padding_right = max(span_x * 0.08, 240.0)
    padding_y = max(span_y * 0.08, 80.0)
    view_box = (
        f"{minimum_x - padding_left} {minimum_y - padding_y} "
        f"{span_x + padding_left + padding_right} {span_y + padding_y * 2}"
    )
    return MapView(
        points=tuple(points),
        view_box=view_box,
        view_width=span_x + padding_left + padding_right,
        view_height=span_y + padding_y * 2,
        focused_entity_id=focused_entity_id,
        show_labels=show_labels,
        label_entity_ids=overview_labels,
        detail_label_entity_ids=detail_labels,
        horizontal_midpoint=minimum_x + span_x / 2,
    )
