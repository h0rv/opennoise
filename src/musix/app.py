"""Async Litestar application for the local map interface."""

import asyncio
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
from musix.local_musicbrainz_artist_evidence import (
    LocalMusicBrainzArtistEvidenceStore,
    LocalMusicBrainzEvidenceSources,
    load_musicbrainz_model_adapter_report,
    load_release_group_evidence_artifact,
)
from musix.local_musicbrainz_artist_metadata import (
    LocalArtistMetadataSources,
    load_artist_metadata_artifact,
)
from musix.models import Settings
from musix.open_construction_store import OpenConstructionMapStore
from musix.open_construction_store_v2 import OpenConstructionV2MapStore
from musix.pipeline.manifest import load_download_source
from musix.production_store import ProductionMapStore
from musix.public_artist_navigation_store import PublicArtistNavigationStore
from musix.routes import CoreController, EvidenceController, MapController, SearchController
from musix.seed_reconciliation import load_seed_reconciliation

PACKAGE_ROOT = Path(__file__).parent
STATIC_ROOT = PACKAGE_ROOT / "static"
TEMPLATE_ROOT = PACKAGE_ROOT / "templates"


class _UnsetPath:
    """Distinguish an omitted path from an explicit opt-out in create_app."""


_UNSET_PATH = _UnsetPath()


def create_app(  # noqa: C901, PLR0913, PLR0915, PLR0917
    database_path: Path | None = None,
    production_map_path: Path | None = None,
    historical_signal_map_path: Path | None = None,
    historical_membership_database_path: Path | None = None,
    open_construction_graph_path: Path | _UnsetPath | None = _UNSET_PATH,
    open_construction_graph_v2_path: Path | _UnsetPath | None = _UNSET_PATH,
) -> Litestar:
    """Create an app with a separate lifecycle-managed read connection."""
    settings = Settings()
    selected_path = database_path or settings.database_path
    database = AsyncDatabase(selected_path, read_only=settings.database_read_only)
    genre_entries = GenreEntryRepository(selected_path)
    production_map = ProductionMapStore(production_map_path or settings.production_map_path)
    historical_signal_map = HistoricalSignalMapStore(
        historical_signal_map_path or settings.historical_signal_map_path
    )
    historical_memberships = HistoricalMembershipStore(
        historical_membership_database_path or settings.historical_membership_database_path
    )
    selected_v2_path = (
        settings.open_construction_graph_v2_path
        if isinstance(open_construction_graph_v2_path, _UnsetPath)
        else open_construction_graph_v2_path
    )
    if isinstance(open_construction_graph_path, _UnsetPath):
        # The checked-in v2 artifact is the sole default Open surface. Keep v1
        # available when explicitly configured (including by environment), and
        # retain the v1-only fallback when v2 is explicitly disabled.
        v1_explicitly_configured = "open_construction_graph_path" in settings.model_fields_set
        selected_v1_path = (
            settings.open_construction_graph_path
            if v1_explicitly_configured or selected_v2_path is None
            else None
        )
    else:
        selected_v1_path = open_construction_graph_path
    open_construction_graph = OpenConstructionMapStore(selected_v1_path)
    open_construction_graph_v2 = OpenConstructionV2MapStore(selected_v2_path)
    public_artist_navigation = PublicArtistNavigationStore(selected_path)
    local_research_artists: LocalMusicBrainzArtistEvidenceStore | None = None
    if settings.local_research_artist_evidence_enabled:
        if settings.host not in {"127.0.0.1", "::1", "localhost"}:
            raise ValueError("local research artist evidence requires a loopback host")
        evidence_artifact = load_release_group_evidence_artifact(
            settings.local_research_artist_evidence_artifact_path
        )
        source = load_download_source(Path("config/data_sources.toml"), evidence_artifact.source_id)
        if not (source.local_only and source.local_search and source.display):
            raise ValueError("local research artist evidence source policy forbids local discovery")
        artist_metadata = None
        if (
            settings.local_research_artist_metadata_database_path is not None
            and settings.local_research_artist_metadata_artifact_path is not None
        ):
            artist_metadata = LocalArtistMetadataSources(
                database=settings.local_research_artist_metadata_database_path,
                artifact=load_artist_metadata_artifact(
                    settings.local_research_artist_metadata_artifact_path
                ),
            )
        local_research_artists = LocalMusicBrainzArtistEvidenceStore(
            LocalMusicBrainzEvidenceSources(
                database=settings.local_research_artist_evidence_database_path,
                evidence_artifact=evidence_artifact,
                reconciliation=load_seed_reconciliation(
                    settings.local_research_seed_reconciliation_path
                ),
                adapter_report=load_musicbrainz_model_adapter_report(
                    settings.local_research_adapter_report_path
                ),
                artist_metadata=artist_metadata,
            )
        )

    @asynccontextmanager
    async def lifespan(_: Litestar) -> AsyncIterator[None]:
        await historical_signal_map.start()
        await historical_memberships.start(historical_signal_map.publication_artifact())
        await open_construction_graph.start()
        await open_construction_graph_v2.start()
        await database.start()
        if local_research_artists is not None:
            await asyncio.to_thread(local_research_artists.start)
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

    async def provide_open_construction_graph() -> OpenConstructionMapStore:
        return open_construction_graph

    async def provide_open_construction_graph_v2() -> OpenConstructionV2MapStore:
        return open_construction_graph_v2

    async def provide_public_artist_navigation() -> PublicArtistNavigationStore:
        return public_artist_navigation

    async def provide_local_research_artists() -> LocalMusicBrainzArtistEvidenceStore | None:
        return local_research_artists

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
            "open_construction_graph": Provide(provide_open_construction_graph),
            "open_construction_graph_v2": Provide(provide_open_construction_graph_v2),
            "public_artist_navigation": Provide(provide_public_artist_navigation),
            "local_research_artists": Provide(provide_local_research_artists),
        },
        lifespan=[lifespan],
        template_config=TemplateConfig(directory=TEMPLATE_ROOT, engine=JinjaTemplateEngine),
    )


app = create_app()
