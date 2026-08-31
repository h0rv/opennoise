"""Async Litestar application for the local map interface."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from litestar import Litestar
from litestar.contrib.jinja import JinjaTemplateEngine
from litestar.di import Provide
from litestar.static_files import create_static_files_router
from litestar.template.config import TemplateConfig

from musix.db import AsyncDatabase
from musix.genre_entry import GenreEntryRepository
from musix.models import Settings
from musix.routes import CoreController, EvidenceController, MapController, SearchController

PACKAGE_ROOT = Path(__file__).parent
STATIC_ROOT = PACKAGE_ROOT / "static"
TEMPLATE_ROOT = PACKAGE_ROOT / "templates"


def create_app(database_path: Path | None = None) -> Litestar:
    """Create an app with a separate lifecycle-managed read connection."""
    selected_path = database_path or Settings().database_path
    database = AsyncDatabase(selected_path)
    genre_entries = GenreEntryRepository(selected_path)

    @asynccontextmanager
    async def lifespan(_: Litestar) -> AsyncIterator[None]:
        await database.start()
        try:
            yield
        finally:
            await database.stop()

    async def provide_database() -> AsyncDatabase:
        return database

    async def provide_genre_entries() -> GenreEntryRepository:
        return genre_entries

    return Litestar(
        route_handlers=[
            CoreController,
            MapController,
            SearchController,
            EvidenceController,
            create_static_files_router(path="/static", directories=[STATIC_ROOT]),
        ],
        dependencies={
            "database": Provide(provide_database),
            "genre_entries": Provide(provide_genre_entries),
        },
        lifespan=[lifespan],
        template_config=TemplateConfig(directory=TEMPLATE_ROOT, engine=JinjaTemplateEngine),
    )


app = create_app()
