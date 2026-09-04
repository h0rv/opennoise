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
from musix.historical_membership_store import HistoricalMembershipStore
from musix.historical_signal_store import HistoricalSignalMapStore
from musix.models import Settings
from musix.production_store import ProductionMapStore
from musix.routes import CoreController, EvidenceController, MapController, SearchController

PACKAGE_ROOT = Path(__file__).parent
STATIC_ROOT = PACKAGE_ROOT / "static"
TEMPLATE_ROOT = PACKAGE_ROOT / "templates"


def create_app(
    database_path: Path | None = None,
    production_map_path: Path | None = None,
    historical_signal_map_path: Path | None = None,
    historical_membership_database_path: Path | None = None,
) -> Litestar:
    """Create an app with a separate lifecycle-managed read connection."""
    settings = Settings()
    selected_path = database_path or settings.database_path
    database = AsyncDatabase(selected_path)
    genre_entries = GenreEntryRepository(selected_path)
    production_map = ProductionMapStore(production_map_path or settings.production_map_path)
    historical_signal_map = HistoricalSignalMapStore(
        historical_signal_map_path or settings.historical_signal_map_path
    )
    historical_memberships = HistoricalMembershipStore(
        historical_membership_database_path or settings.historical_membership_database_path
    )

    @asynccontextmanager
    async def lifespan(_: Litestar) -> AsyncIterator[None]:
        await historical_signal_map.start()
        await historical_memberships.start(historical_signal_map.publication_artifact())
        await database.start()
        try:
            yield
        finally:
            await database.stop()

    async def provide_database() -> AsyncDatabase:
        return database

    async def provide_genre_entries() -> GenreEntryRepository:
        return genre_entries

    async def provide_production_map() -> ProductionMapStore:
        return production_map

    async def provide_historical_signal_map() -> HistoricalSignalMapStore:
        return historical_signal_map

    async def provide_historical_memberships() -> HistoricalMembershipStore:
        return historical_memberships

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
            "production_map": Provide(provide_production_map),
            "historical_signal_map": Provide(provide_historical_signal_map),
            "historical_memberships": Provide(provide_historical_memberships),
        },
        lifespan=[lifespan],
        template_config=TemplateConfig(directory=TEMPLATE_ROOT, engine=JinjaTemplateEngine),
    )


app = create_app()
