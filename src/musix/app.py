"""Async Litestar application for the local map interface."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from litestar import Litestar, MediaType, get
from litestar.contrib.jinja import JinjaTemplateEngine
from litestar.params import FromQuery
from litestar.response import Template
from litestar.static_files import create_static_files_router
from litestar.template.config import TemplateConfig

from musix.db import AsyncDatabase
from musix.models import (
    MapPointResponse,
    MapResponse,
    SearchHitResponse,
    SearchResponse,
    Settings,
    map_view,
)

PACKAGE_ROOT = Path(__file__).parent
STATIC_ROOT = PACKAGE_ROOT / "static"
TEMPLATE_ROOT = PACKAGE_ROOT / "templates"


def create_app(database_path: Path | None = None) -> Litestar:
    """Create an app with a separate lifecycle-managed read connection."""
    selected_path = database_path or Settings().database_path
    database = AsyncDatabase(selected_path)

    @asynccontextmanager
    async def lifespan(_: Litestar) -> AsyncIterator[None]:
        await database.start()
        try:
            yield
        finally:
            await database.stop()

    @get("/")
    async def index() -> Template:
        view = map_view(await database.map_points())
        return Template(template_name="index.html", context={"map": view})

    @get("/api/health", media_type=MediaType.TEXT)
    async def health() -> str:
        await database.ping()
        return "ok"

    @get("/api/map")
    async def map_data(layout: FromQuery[str] = "default") -> MapResponse:
        points = await database.map_points(layout[:100])
        return MapResponse(
            points=tuple(
                MapPointResponse(
                    id=point.entity_id,
                    kind=point.entity_kind,
                    name=point.name,
                    x=point.x,
                    y=point.y,
                    weight=point.display_weight,
                    color=point.color_hex,
                )
                for point in points
            )
        )

    @get("/api/search")
    async def search(q: FromQuery[str] = "") -> SearchResponse:
        hits = await database.search(q[:500])
        return SearchResponse(
            hits=tuple(
                SearchHitResponse(id=hit.entity_id, kind=hit.entity_kind, name=hit.name)
                for hit in hits
            )
        )

    @get("/fragments/search")
    async def search_fragment(q: FromQuery[str] = "") -> Template:
        hits = await database.search(q[:500])
        return Template(template_name="search_results.html", context={"hits": hits})

    @get("/fragments/map")
    async def map_fragment(
        focus: FromQuery[int | None] = None,
        layout: FromQuery[str] = "default",
    ) -> Template:
        view = map_view(await database.map_points(layout[:100]), focus)
        return Template(template_name="map.html", context={"map": view})

    return Litestar(
        route_handlers=[
            index,
            health,
            map_data,
            search,
            search_fragment,
            map_fragment,
            create_static_files_router(path="/static", directories=[STATIC_ROOT]),
        ],
        lifespan=[lifespan],
        template_config=TemplateConfig(directory=TEMPLATE_ROOT, engine=JinjaTemplateEngine),
    )


app = create_app()
