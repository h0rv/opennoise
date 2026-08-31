"""Validated settings and web response models."""

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


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


class MapView(FrozenModel):
    """Computed SVG bounds and points for a server-rendered map."""

    points: tuple[MapPoint, ...]
    view_box: str
    view_width: float
    view_height: float
    focused_entity_id: int | None = None
    show_labels: bool = True


def map_view(
    points: list[MapPoint],
    focused_entity_id: int | None = None,
    *,
    view_box: str | None = None,
    show_labels: bool = True,
) -> MapView:
    """Compute padded SVG bounds for a sequence of map points."""
    if view_box is not None:
        _, _, view_width, view_height = (float(value) for value in view_box.split())
        return MapView(
            points=tuple(points),
            view_box=view_box,
            view_width=view_width,
            view_height=view_height,
            focused_entity_id=focused_entity_id,
            show_labels=show_labels,
        )
    if not points:
        return MapView(
            points=(),
            view_box="0 0 100 100",
            view_width=100.0,
            view_height=100.0,
            focused_entity_id=focused_entity_id,
            show_labels=show_labels,
        )
    minimum_x = min(point.x for point in points)
    maximum_x = max(point.x for point in points)
    minimum_y = min(point.y for point in points)
    maximum_y = max(point.y for point in points)
    span_x = max(maximum_x - minimum_x, 1.0)
    span_y = max(maximum_y - minimum_y, 1.0)
    padding_x = max(span_x * 0.08, 80.0)
    padding_y = max(span_y * 0.05, 28.0)
    view_box = (
        f"{minimum_x - padding_x} {minimum_y - padding_y} "
        f"{span_x + padding_x * 2} {span_y + padding_y * 2}"
    )
    return MapView(
        points=tuple(points),
        view_box=view_box,
        view_width=span_x + padding_x * 2,
        view_height=span_y + padding_y * 2,
        focused_entity_id=focused_entity_id,
        show_labels=show_labels,
    )
