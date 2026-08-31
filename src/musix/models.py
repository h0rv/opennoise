"""Validated settings, catalog records, and web response models."""

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
    focused_entity_id: int | None = None


def map_view(points: list[MapPoint], focused_entity_id: int | None = None) -> MapView:
    """Compute padded SVG bounds for a sequence of map points."""
    if not points:
        return MapView(points=(), view_box="0 0 100 100", focused_entity_id=focused_entity_id)
    focused_point = next(
        (point for point in points if point.entity_id == focused_entity_id),
        None,
    )
    if focused_point is not None:
        focus_width = 600.0
        focus_height = 800.0
        view_box = (
            f"{focused_point.x - focus_width / 2} "
            f"{focused_point.y - focus_height / 2} "
            f"{focus_width} {focus_height}"
        )
        return MapView(
            points=tuple(points),
            view_box=view_box,
            focused_entity_id=focused_entity_id,
        )
    minimum_x = min(point.x for point in points)
    maximum_x = max(point.x for point in points)
    minimum_y = min(point.y for point in points)
    maximum_y = max(point.y for point in points)
    span_x = max(maximum_x - minimum_x, 1.0)
    span_y = max(maximum_y - minimum_y, 1.0)
    padding_x = span_x * 0.03
    padding_y = span_y * 0.005
    view_box = (
        f"{minimum_x - padding_x} {minimum_y - padding_y} "
        f"{span_x + padding_x * 2} {span_y + padding_y * 2}"
    )
    return MapView(points=tuple(points), view_box=view_box, focused_entity_id=focused_entity_id)
