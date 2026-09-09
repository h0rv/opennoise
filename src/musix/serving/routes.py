"""Typed Litestar routes for map, search, and evidence fragments."""

from datetime import datetime
from typing import TYPE_CHECKING, Literal, Protocol

from litestar import Controller, MediaType, Request, get
from litestar.datastructures import State
from litestar.di import NamedDependency
from litestar.exceptions import NotFoundException, ServiceUnavailableException, ValidationException
from litestar.params import FromPath, FromQuery
from litestar.response import Template

from musix.db import AsyncDatabase
from musix.history.historical_membership_store import (
    HistoricalMembershipStore,
    HistoricalMembershipStoreError,
    HistoricalSignalMembersApiResponse,
)
from musix.history.signals.store import (
    HistoricalSignalMapApiResponse,
    HistoricalSignalMapStore,
    HistoricalSignalMapStoreError,
    HistoricalSignalNeighborApiResponse,
)
from musix.models import (
    LegacyMapResponse,
    MapPointResponse,
    SearchHitResponse,
    SearchResponse,
    map_view,
)
from musix.serving.exploration import (
    CatalogLens,
    GenreDetail,
    HydratedReleaseMetadata,
    LevelOfDetail,
    MapQuery,
    ProvenanceResponse,
    optional_viewport,
)
from musix.serving.genre_entry import GenreEntryRepository
from musix.serving.local.musicbrainz_artist_evidence import (
    LocalMusicBrainzArtistEvidenceError,
    LocalMusicBrainzArtistEvidenceStore,
)
from musix.serving.local.musicbrainz_peer_store import (
    LocalMusicBrainzPeerStore,
    LocalMusicBrainzPeerStoreError,
)
from musix.serving.local.research_map_store import (
    LocalResearchMapError,
    LocalResearchMapResponse,
    LocalResearchMapStore,
)
from musix.serving.local.reviewed_alias_context_store import LocalReviewedAliasContextStore
from musix.serving.map.layouts import ExploredMap, LayoutArtifactMetadata, PublishedLayout
from musix.serving.open.construction_store import (
    OpenConstructionMapResponse,
    OpenConstructionMapStore,
    OpenConstructionMapStoreError,
    OpenConstructionNeighborResponse,
)
from musix.serving.open.construction_store_v2 import (
    OpenConstructionV2MapResponse,
    OpenConstructionV2MapStore,
    OpenConstructionV2MapStoreError,
    OpenConstructionV2NeighborResponse,
    OpenConstructionV2SearchResponse,
)

if TYPE_CHECKING:
    from musix.models.historical_signal import HistoricalSignalHierarchyNode
from musix.serving.map.production_store import (
    ProductionMapApiResponse,
    ProductionMapStore,
    ProductionMapStoreError,
)
from musix.serving.public.artist_navigation_store import (
    ArtistGenresResponse,
    GenreArtistsResponse,
    PublicArtistNavigationStore,
    PublicArtistNavigationStoreError,
    RelatedArtistsResponse,
)

PUBLIC_LAYOUT_KEYS = frozenset({"public", "public-direct", "public-community", "public-taxonomy"})


class _ObservedArtistRow(Protocol):
    @property
    def artist_mbid(self) -> str: ...


class _ObservedSeedRow(Protocol):
    @property
    def source_item_id(self) -> str: ...


def _union_observed_artists(
    direct: tuple[_ObservedArtistRow, ...], context: tuple[_ObservedArtistRow, ...]
) -> tuple[_ObservedArtistRow, ...]:
    """Union direct and reviewed tag observations by the exact MusicBrainz ID."""
    rows: dict[str, _ObservedArtistRow] = {item.artist_mbid: item for item in direct}
    for item in context:
        rows.setdefault(item.artist_mbid, item)
    return tuple(rows.values())


def _union_observed_seeds(
    direct: tuple[_ObservedSeedRow, ...], context: tuple[_ObservedSeedRow, ...]
) -> tuple[_ObservedSeedRow, ...]:
    """Union direct and reviewed tag observations by the exact stable seed ID."""
    rows: dict[str, _ObservedSeedRow] = {item.source_item_id: item for item in direct}
    for item in context:
        rows.setdefault(item.source_item_id, item)
    return tuple(rows.values())


class CoreController(Controller):
    """Render the app shell and health response."""

    @get("/")
    async def index(
        self,
        database: NamedDependency[AsyncDatabase],
        genre_entries: NamedDependency[GenreEntryRepository],
        production_map: NamedDependency[ProductionMapStore],
        historical_signal_map: NamedDependency[HistoricalSignalMapStore],
        open_construction_graph: NamedDependency[OpenConstructionMapStore],
        open_construction_graph_v2: NamedDependency[OpenConstructionV2MapStore],
        local_research_artists: NamedDependency[object],
        local_research_map: NamedDependency[object],
        layout: FromQuery[str] = "default",
        q: FromQuery[str] = "",
        view: FromQuery[Literal["public", "open", "historical"] | None] = None,
    ) -> Template:
        """Render the current full map."""
        selected_view = view or (
            "open"
            if open_construction_graph_v2.configured or open_construction_graph.configured
            else "public"
        )
        context = await workspace_context(
            database,
            genre_entries,
            production_map,
            historical_signal_map,
            open_construction_graph,
            open_construction_graph_v2,
            local_research_map=(
                local_research_map
                if isinstance(local_research_map, LocalResearchMapStore)
                else None
            ),
            local_research_artist_evidence_configured=(
                isinstance(local_research_artists, LocalMusicBrainzArtistEvidenceStore)
                and local_research_artists.configured
            ),
            local_research_map_configured=(
                isinstance(local_research_map, LocalResearchMapStore)
                and local_research_map.configured
            ),
            layout=layout,
            focus=None,
            search_query=q,
            view=selected_view,
        )
        return Template(template_name="index.html", context=context)

    @get("/genres/{genre_id:int}")
    async def selected_genre(
        self,
        database: NamedDependency[AsyncDatabase],
        genre_entries: NamedDependency[GenreEntryRepository],
        production_map: NamedDependency[ProductionMapStore],
        historical_signal_map: NamedDependency[HistoricalSignalMapStore],
        open_construction_graph: NamedDependency[OpenConstructionMapStore],
        open_construction_graph_v2: NamedDependency[OpenConstructionV2MapStore],
        local_research_artists: NamedDependency[object],
        local_research_map: NamedDependency[object],
        genre_id: FromPath[int],
        request: Request[object, object, State],
        layout: FromQuery[str] = "default",
        q: FromQuery[str] = "",
        view: FromQuery[Literal["public", "open", "historical"]] = "public",
    ) -> Template:
        """Render a shareable genre selection with the complete app shell."""
        context = await workspace_context(
            database,
            genre_entries,
            production_map,
            historical_signal_map,
            open_construction_graph,
            open_construction_graph_v2,
            local_research_map=(
                local_research_map
                if isinstance(local_research_map, LocalResearchMapStore)
                else None
            ),
            local_research_artist_evidence_configured=(
                isinstance(local_research_artists, LocalMusicBrainzArtistEvidenceStore)
                and local_research_artists.configured
            ),
            layout=layout,
            focus=genre_id,
            search_query=q,
            view=view,
        )
        if request.headers.get("HX-Request") == "true":
            return detail_template(context)
        return Template(template_name="index.html", context=context)

    @get("/genres/key/{genre_key:str}")
    async def selected_genre_key(
        self,
        database: NamedDependency[AsyncDatabase],
        genre_entries: NamedDependency[GenreEntryRepository],
        production_map: NamedDependency[ProductionMapStore],
        historical_signal_map: NamedDependency[HistoricalSignalMapStore],
        open_construction_graph: NamedDependency[OpenConstructionMapStore],
        open_construction_graph_v2: NamedDependency[OpenConstructionV2MapStore],
        local_research_artists: NamedDependency[object],
        local_research_map: NamedDependency[object],
        genre_key: FromPath[str],
        request: Request[object, object, State],
        layout: FromQuery[str] = "default",
        q: FromQuery[str] = "",
        view: FromQuery[Literal["public", "open", "historical"]] = "public",
    ) -> Template:
        """Open a stable public key, resolving its current local entity only server-side."""
        genre_id = await database.genre_id_for_public_key(genre_key)
        if genre_id is None:
            raise NotFoundException(detail="genre not found")
        context = await workspace_context(
            database,
            genre_entries,
            production_map,
            historical_signal_map,
            open_construction_graph,
            open_construction_graph_v2,
            local_research_map=(
                local_research_map
                if isinstance(local_research_map, LocalResearchMapStore)
                else None
            ),
            local_research_artist_evidence_configured=(
                isinstance(local_research_artists, LocalMusicBrainzArtistEvidenceStore)
                and local_research_artists.configured
            ),
            layout=layout,
            focus=genre_id,
            search_query=q,
            view=view,
        )
        if request.headers.get("HX-Request") == "true":
            return detail_template(context)
        return Template(template_name="index.html", context=context)

    @get("/api/health", media_type=MediaType.TEXT)
    async def health(self, database: NamedDependency[AsyncDatabase]) -> str:
        """Check that SQLite accepts a query."""
        await database.ping()
        return "ok"


class MapController(Controller):
    """Serve stable and experimental map representations."""

    @get("/api/local-research-map")
    async def local_research_map_data(
        self, local_research_map: NamedDependency[object], level: FromQuery[int] = 0
    ) -> LocalResearchMapResponse:
        """Return a bounded local-only peer layout cohort."""
        if (
            not isinstance(local_research_map, LocalResearchMapStore)
            or not local_research_map.configured
        ):
            raise ServiceUnavailableException(detail="local research peer map is disabled")
        try:
            return local_research_map.response(level=level)
        except LocalResearchMapError as error:
            raise ServiceUnavailableException(
                detail="local research peer map unavailable"
            ) from error

    @get("/api/local-research-map/neighbors/{node_id:str}")
    async def local_research_map_neighbors(
        self,
        local_research_map: NamedDependency[object],
        node_id: FromPath[str],
        offset: FromQuery[int] = 0,
    ) -> LocalResearchMapResponse:
        """Drill a display community or a direct evidence neighborhood."""
        if (
            not isinstance(local_research_map, LocalResearchMapStore)
            or not local_research_map.configured
        ):
            raise ServiceUnavailableException(detail="local research peer map is disabled")
        try:
            return local_research_map.neighbors(node_id, offset=offset)
        except LocalResearchMapError as error:
            raise NotFoundException(detail="local research peer node unavailable") from error

    @get("/api/map")
    async def map_data(
        self,
        database: NamedDependency[AsyncDatabase],
        production_map: NamedDependency[ProductionMapStore],
        layout: FromQuery[str] = "default",
    ) -> ProductionMapApiResponse | LegacyMapResponse:
        """Return the production graph; never use the legacy map as an interactive graph."""
        if production_map.configured and layout == "default":
            try:
                response = production_map.response()
            except ProductionMapStoreError as error:
                raise ServiceUnavailableException(
                    detail="production map artifact unavailable"
                ) from error
            if response is None:
                raise RuntimeError("configured production map store returned no graph")
            return response
        if layout == "default":
            raise ServiceUnavailableException(
                detail="production map artifact is required; run the production map build first"
            )
        layout_key, _ = resolve_layout(layout, await database.published_layouts())
        points = await database.map_points(layout_key)
        return LegacyMapResponse(
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

    @get("/api/historical-signal-map")
    async def historical_signal_map_data(
        self,
        historical_signal_map: NamedDependency[HistoricalSignalMapStore],
        level: FromQuery[int] = 0,
        column: FromQuery[int | None] = None,
        row: FromQuery[int | None] = None,
        parent_id: FromQuery[str | None] = None,
    ) -> HistoricalSignalMapApiResponse:
        """Return one bounded H3 map cohort or viewport tile after explicit local opt-in."""
        if not historical_signal_map.configured:
            raise ServiceUnavailableException(
                detail=(
                    "historical signal map is disabled; configure MUSIX_HISTORICAL_SIGNAL_MAP_PATH"
                )
            )
        try:
            response = historical_signal_map.response(
                level=level, column=column, row=row, parent_id=parent_id
            )
        except HistoricalSignalMapStoreError as error:
            raise ServiceUnavailableException(
                detail="historical signal map artifact unavailable"
            ) from error
        if response is None:
            raise RuntimeError("configured historical signal map store returned no graph")
        return response

    @get("/api/open-construction-map")
    async def open_construction_map_data(
        self,
        open_construction_graph: NamedDependency[OpenConstructionMapStore],
        level: FromQuery[int] = 0,
        min_x: FromQuery[float | None] = None,
        min_y: FromQuery[float | None] = None,
        max_x: FromQuery[float | None] = None,
        max_y: FromQuery[float | None] = None,
    ) -> OpenConstructionMapResponse:
        """Return one bounded landscape LOD from the committed 6,291-node artifact."""
        if not open_construction_graph.configured:
            raise ServiceUnavailableException(detail="open construction graph is disabled")
        if level not in range(4):
            raise ValidationException(detail="open construction level must be between 0 and 3")
        bounds = (min_x, min_y, max_x, max_y)
        if any(value is None for value in bounds) and any(value is not None for value in bounds):
            raise ValidationException(detail="open construction viewport must include all bounds")
        if (
            min_x is not None
            and min_y is not None
            and max_x is not None
            and max_y is not None
            and (min_x >= max_x or min_y >= max_y)
        ):
            raise ValidationException(detail="open construction viewport bounds are invalid")
        try:
            return open_construction_graph.response(
                level=level, min_x=min_x, min_y=min_y, max_x=max_x, max_y=max_y
            )
        except OpenConstructionMapStoreError as error:
            raise ServiceUnavailableException(
                detail="open construction graph artifact unavailable"
            ) from error

    @get("/api/open-construction-map/neighbors/{genre_id:str}")
    async def open_construction_neighbors(
        self,
        open_construction_graph: NamedDependency[OpenConstructionMapStore],
        genre_id: FromPath[str],
    ) -> OpenConstructionNeighborResponse:
        """Return one bounded one-hop open graph drill result."""
        if not open_construction_graph.configured:
            raise ServiceUnavailableException(detail="open construction graph is disabled")
        try:
            return open_construction_graph.neighbors(genre_id)
        except OpenConstructionMapStoreError as error:
            raise NotFoundException(detail="open construction graph node unavailable") from error

    @get("/api/open-construction-map/v2")
    async def open_construction_map_v2_data(
        self,
        open_construction_graph_v2: NamedDependency[OpenConstructionV2MapStore],
        level: FromQuery[int] = 0,
        min_x: FromQuery[float | None] = None,
        min_y: FromQuery[float | None] = None,
        max_x: FromQuery[float | None] = None,
        max_y: FromQuery[float | None] = None,
    ) -> OpenConstructionV2MapResponse:
        """Return a bounded v2 LOD only from an explicitly configured artifact."""
        if not open_construction_graph_v2.configured:
            raise ServiceUnavailableException(detail="open construction v2 graph is disabled")
        if level not in range(4):
            raise ValidationException(detail="open construction v2 level must be between 0 and 3")
        bounds = (min_x, min_y, max_x, max_y)
        if any(value is None for value in bounds) and any(value is not None for value in bounds):
            raise ValidationException(
                detail="open construction v2 viewport must include all bounds"
            )
        if (
            min_x is not None
            and min_y is not None
            and max_x is not None
            and max_y is not None
            and (min_x >= max_x or min_y >= max_y)
        ):
            raise ValidationException(detail="open construction v2 viewport bounds are invalid")
        try:
            return open_construction_graph_v2.response(
                level=level, min_x=min_x, min_y=min_y, max_x=max_x, max_y=max_y
            )
        except OpenConstructionV2MapStoreError as error:
            raise ServiceUnavailableException(
                detail="open construction v2 graph artifact unavailable"
            ) from error

    @get("/api/open-construction-map/v2/search")
    async def open_construction_v2_search(
        self,
        open_construction_graph_v2: NamedDependency[OpenConstructionV2MapStore],
        q: FromQuery[str] = "",
    ) -> OpenConstructionV2SearchResponse:
        """Find configured v2 names without consulting public catalog membership data."""
        if not open_construction_graph_v2.configured:
            raise ServiceUnavailableException(detail="open construction v2 graph is disabled")
        try:
            return open_construction_graph_v2.search(q[:500])
        except OpenConstructionV2MapStoreError as error:
            raise ServiceUnavailableException(
                detail="open construction v2 graph artifact unavailable"
            ) from error

    @get("/api/open-construction-map/v2/neighbors/{node_id:str}")
    async def open_construction_v2_neighbors(
        self,
        open_construction_graph_v2: NamedDependency[OpenConstructionV2MapStore],
        node_id: FromPath[str],
    ) -> OpenConstructionV2NeighborResponse:
        """Return a bounded one-hop v2 drill without an implied membership claim."""
        if not open_construction_graph_v2.configured:
            raise ServiceUnavailableException(detail="open construction v2 graph is disabled")
        try:
            return open_construction_graph_v2.neighbors(node_id)
        except OpenConstructionV2MapStoreError as error:
            raise NotFoundException(detail="open construction v2 graph node unavailable") from error

    @get("/api/historical-signal-map/neighbors/{genre_id:str}")
    async def historical_signal_neighbors(
        self,
        historical_signal_map: NamedDependency[HistoricalSignalMapStore],
        genre_id: FromPath[str],
    ) -> HistoricalSignalNeighborApiResponse:
        """Return focused H3 similarity evidence without graph-wide edge serialization."""
        if not historical_signal_map.configured:
            raise ServiceUnavailableException(detail="historical signal map is disabled")
        try:
            response = historical_signal_map.neighbors(genre_id)
        except HistoricalSignalMapStoreError as error:
            raise NotFoundException(detail="historical signal genre unavailable") from error
        if response is None:
            raise RuntimeError("configured historical signal map store returned no graph")
        return response

    @get("/api/historical-signal-map/members/{genre_id:str}")
    async def historical_signal_members(
        self,
        historical_memberships: NamedDependency[HistoricalMembershipStore],
        genre_id: FromPath[str],
        offset: FromQuery[int] = 0,
        limit: FromQuery[int] = 50,
    ) -> HistoricalSignalMembersApiResponse:
        """Return one bounded, policy-authorized H3 member page for a selected genre."""
        if not historical_memberships.configured:
            raise ServiceUnavailableException(detail="historical membership database is disabled")
        try:
            return await historical_memberships.members(genre_id, offset=offset, limit=limit)
        except HistoricalMembershipStoreError as error:
            raise NotFoundException(detail="historical membership data unavailable") from error

    @get("/api/explore/map")
    async def explore_map(
        self,
        database: NamedDependency[AsyncDatabase],
        layout: FromQuery[str] = "default",
        lens: FromQuery[CatalogLens] = CatalogLens.ALL,
        lod: FromQuery[LevelOfDetail] = LevelOfDetail.LABELS,
        source: FromQuery[str | None] = None,
        as_of: FromQuery[datetime | None] = None,
        min_x: FromQuery[float | None] = None,
        min_y: FromQuery[float | None] = None,
        max_x: FromQuery[float | None] = None,
        max_y: FromQuery[float | None] = None,
        limit: FromQuery[int] = 10_000,
    ) -> ExploredMap:
        """Return a bounded map with its exact selection and layout metadata."""
        layout_key, _ = resolve_layout(layout, await database.published_layouts())
        query = map_query(
            layout=layout_key,
            lens=lens,
            level_of_detail=lod,
            source=source,
            as_of=as_of,
            min_x=min_x,
            min_y=min_y,
            max_x=max_x,
            max_y=max_y,
            limit=limit,
        )
        result = await database.query_map(query)
        metadata = await database.layout_metadata(query.layout_key)
        return ExploredMap(
            query=query,
            layout=metadata,
            bounds=query.viewport or (metadata.bounds if metadata is not None else None),
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
                for point in result.points
            ),
            truncated=result.truncated,
        )

    @get("/api/layouts/{layout_key:str}/metadata")
    async def layout_metadata(
        self,
        database: NamedDependency[AsyncDatabase],
        layout_key: FromPath[str],
    ) -> LayoutArtifactMetadata:
        """Return reproduction metadata for a published layout."""
        metadata = await database.layout_metadata(layout_key[:100])
        if metadata is None:
            raise NotFoundException(detail="layout not found")
        return metadata

    @get("/fragments/map")
    async def map_fragment(
        self,
        database: NamedDependency[AsyncDatabase],
        focus: FromQuery[int | None] = None,
        layout: FromQuery[str] = "default",
        lens: FromQuery[CatalogLens] = CatalogLens.ALL,
        lod: FromQuery[LevelOfDetail] = LevelOfDetail.LABELS,
        source: FromQuery[str | None] = None,
        as_of: FromQuery[datetime | None] = None,
        min_x: FromQuery[float | None] = None,
        min_y: FromQuery[float | None] = None,
        max_x: FromQuery[float | None] = None,
        max_y: FromQuery[float | None] = None,
        limit: FromQuery[int] = 10_000,
    ) -> Template:
        """Render a bounded SVG map at the requested level of detail."""
        layout_key, active_layout = resolve_layout(layout, await database.published_layouts())
        query = map_query(
            layout=layout_key,
            lens=lens,
            level_of_detail=lod,
            source=source,
            as_of=as_of,
            min_x=min_x,
            min_y=min_y,
            max_x=max_x,
            max_y=max_y,
            limit=limit,
        )
        result = await database.query_map(query)
        view = map_view(
            list(result.points),
            focus,
            view_box=query.viewport.svg_view_box() if query.viewport is not None else None,
            show_labels=query.level_of_detail is LevelOfDetail.LABELS,
        )
        return Template(
            template_name="map.html",
            context={
                "active_layout": active_layout,
                "layout_key": query.layout_key,
                "layout_query": None if layout == "default" else query.layout_key,
                "map": view,
            },
        )

    @get("/fragments/workspace")
    async def workspace_fragment(
        self,
        database: NamedDependency[AsyncDatabase],
        genre_entries: NamedDependency[GenreEntryRepository],
        production_map: NamedDependency[ProductionMapStore],
        historical_signal_map: NamedDependency[HistoricalSignalMapStore],
        open_construction_graph: NamedDependency[OpenConstructionMapStore],
        open_construction_graph_v2: NamedDependency[OpenConstructionV2MapStore],
        local_research_artists: NamedDependency[object],
        local_research_map: NamedDependency[object],
        focus: FromQuery[int | None] = None,
        layout: FromQuery[str] = "default",
        q: FromQuery[str] = "",
        view: FromQuery[Literal["public", "open", "historical"] | None] = None,
    ) -> Template:
        """Render one coherent map selection and detail fragment."""
        selected_view = view or (
            "open"
            if open_construction_graph_v2.configured or open_construction_graph.configured
            else "public"
        )
        context = await workspace_context(
            database,
            genre_entries,
            production_map,
            historical_signal_map,
            open_construction_graph,
            open_construction_graph_v2,
            local_research_map=(
                local_research_map
                if isinstance(local_research_map, LocalResearchMapStore)
                else None
            ),
            local_research_artist_evidence_configured=(
                isinstance(local_research_artists, LocalMusicBrainzArtistEvidenceStore)
                and local_research_artists.configured
            ),
            layout=layout,
            focus=focus,
            search_query=q,
            view=selected_view,
        )
        return Template(
            template_name="workspace.html",
            context=context,
        )


class SearchController(Controller):
    """Serve catalog search responses."""

    @get("/api/search")
    async def search(
        self,
        database: NamedDependency[AsyncDatabase],
        q: FromQuery[str] = "",
    ) -> SearchResponse:
        """Return the stable search JSON shape."""
        hits = await database.search(q[:500])
        return SearchResponse(
            hits=tuple(
                SearchHitResponse(id=hit.entity_id, kind=hit.entity_kind, name=hit.name)
                for hit in hits
            )
        )

    @get("/fragments/search")
    async def search_fragment(
        self,
        database: NamedDependency[AsyncDatabase],
        q: FromQuery[str] = "",
        layout: FromQuery[str] = "default",
    ) -> Template:
        """Render search results for the bounded results region."""
        hits = await database.search(q[:500])
        layout_key, _ = resolve_layout(layout, await database.published_layouts())
        return Template(
            template_name="search_results.html",
            context={
                "hits": hits,
                "layout_key": layout_key,
                "layout_query": None if layout == "default" else layout_key,
                "search_query": q[:500],
            },
        )

    @get("/fragments/open-construction-map/v2/search")
    async def open_construction_v2_search_fragment(
        self,
        open_construction_graph_v2: NamedDependency[OpenConstructionV2MapStore],
        q: FromQuery[str] = "",
    ) -> Template:
        """Render map-name results with ordinary links when JavaScript is unavailable."""
        if not open_construction_graph_v2.configured:
            raise ServiceUnavailableException(detail="open construction v2 graph is disabled")
        try:
            response = open_construction_graph_v2.search(q[:500])
        except OpenConstructionV2MapStoreError as error:
            raise ServiceUnavailableException(
                detail="open construction v2 graph artifact unavailable"
            ) from error
        return Template(
            template_name="open_construction_v2_search_results.html",
            context={"hits": response.hits},
        )

    @get("/fragments/local-research-map/search")
    async def local_research_map_search_fragment(
        self,
        local_research_map: NamedDependency[object],
        q: FromQuery[str] = "",
    ) -> Template:
        """Render local-layout results without assigning missing coordinates."""
        if (
            not isinstance(local_research_map, LocalResearchMapStore)
            or not local_research_map.configured
        ):
            raise ServiceUnavailableException(detail="local research peer map is disabled")
        try:
            hits = local_research_map.search(q[:500])
        except LocalResearchMapError as error:
            raise ServiceUnavailableException(
                detail="local research peer map artifact unavailable"
            ) from error
        return Template(
            template_name="local_research_map_search_results.html",
            context={"hits": hits},
        )


class EvidenceController(Controller):
    """Serve genre detail and provenance contracts."""

    @get("/fragments/local-research/musicbrainz/{node_id:str}")
    async def local_research_musicbrainz_fragment(
        self,
        request: Request[object, object, State],
        local_research_artists: NamedDependency[object],
        local_research_peers: NamedDependency[object],
        local_reviewed_alias_context: NamedDependency[object],
        node_id: FromPath[str],
    ) -> Template:
        """Render bounded loopback-only research evidence for one legacy seed."""
        if request.client is None or request.client.host not in {"127.0.0.1", "::1", "localhost"}:
            raise NotFoundException(detail="local research panel is unavailable")
        if not isinstance(local_research_artists, LocalMusicBrainzArtistEvidenceStore):
            raise NotFoundException(detail="local research panel is unavailable")
        if not local_research_artists.configured:
            raise NotFoundException(detail="local research panel is unavailable")
        if not node_id.startswith("legacy:item"):
            raise NotFoundException(detail="local research panel requires a legacy seed")
        try:
            response = local_research_artists.artists_for_seed(node_id.removeprefix("legacy:"))
        except LocalMusicBrainzArtistEvidenceError as error:
            raise ServiceUnavailableException(
                detail="local research evidence is unavailable"
            ) from error
        peers = ()
        if isinstance(local_research_peers, LocalMusicBrainzPeerStore):
            try:
                peers = local_research_peers.neighbors(node_id.removeprefix("legacy:"))
            except LocalMusicBrainzPeerStoreError as error:
                raise ServiceUnavailableException(
                    detail="local peer evidence is unavailable"
                ) from error
        observed_artists: tuple[_ObservedArtistRow, ...] = response.artists
        if isinstance(local_reviewed_alias_context, LocalReviewedAliasContextStore):
            observed_artists = _union_observed_artists(
                observed_artists,
                local_reviewed_alias_context.artist_rows(node_id.removeprefix("legacy:")),
            )
        return Template(
            template_name="local_musicbrainz_artist_evidence.html",
            context={
                "node_id": node_id,
                "response": response,
                "peers": peers,
                "observed_artists": observed_artists,
            },
        )

    @get("/fragments/local-research/musicbrainz/{node_id:str}/artist/{artist_mbid:str}")
    async def local_research_musicbrainz_artist_fragment(
        self,
        request: Request[object, object, State],
        local_research_artists: NamedDependency[object],
        local_reviewed_alias_context: NamedDependency[object],
        node_id: FromPath[str],
        artist_mbid: FromPath[str],
    ) -> Template:
        """Render exact stable-seed links for one locally certified artist ID."""
        if request.client is None or request.client.host not in {"127.0.0.1", "::1", "localhost"}:
            raise NotFoundException(detail="local research panel is unavailable")
        if not isinstance(local_research_artists, LocalMusicBrainzArtistEvidenceStore):
            raise NotFoundException(detail="local research panel is unavailable")
        if not local_research_artists.configured:
            raise NotFoundException(detail="local research panel is unavailable")
        if not node_id.startswith("legacy:item"):
            raise NotFoundException(detail="local research panel requires a legacy seed")
        try:
            response = local_research_artists.seeds_for_artist(artist_mbid)
        except LocalMusicBrainzArtistEvidenceError as error:
            raise ServiceUnavailableException(
                detail="local research evidence is unavailable"
            ) from error
        observed_seeds: tuple[_ObservedSeedRow, ...] = response.seeds
        if isinstance(local_reviewed_alias_context, LocalReviewedAliasContextStore):
            observed_seeds = _union_observed_seeds(
                observed_seeds, local_reviewed_alias_context.seed_rows(artist_mbid)
            )
        return Template(
            template_name="local_musicbrainz_artist_seeds.html",
            context={
                "node_id": node_id,
                "response": response,
                "observed_seeds": observed_seeds,
            },
        )

    @get("/fragments/open-construction-map/v2/artists/{node_id:str}")
    async def open_v2_genre_artists_fragment(
        self,
        open_construction_graph_v2: NamedDependency[OpenConstructionV2MapStore],
        public_artist_navigation: NamedDependency[PublicArtistNavigationStore],
        node_id: FromPath[str],
    ) -> Template:
        """Render direct artists only after an exact Open catalog-QID identity join."""
        genre_id = await public_artist_navigation.catalog_genre_id_for_open_node(node_id)
        if genre_id is None:
            return Template(
                template_name="open_artist_navigation.html",
                context={
                    "node_id": node_id,
                    "genre_response": None,
                    "peer_response": None,
                    "peer_node_ids": {},
                    "hierarchy": None,
                },
            )
        try:
            response = await public_artist_navigation.genre_artists(genre_id, offset=0, limit=20)
            peers = await public_artist_navigation.genre_direct_peers(genre_id)
            peer_node_ids = await public_artist_navigation.open_node_ids_for_catalog_genres(
                tuple(item.genre.entity_id for item in peers.peers)
            )
        except PublicArtistNavigationStoreError as error:
            raise ServiceUnavailableException(
                detail="public artist navigation is unavailable"
            ) from error
        hierarchy = None
        structural_peer_node_ids = frozenset[str]()
        if open_construction_graph_v2.configured:
            try:
                hierarchy = open_construction_graph_v2.neighbors(node_id).hierarchy
                structural_peer_node_ids = frozenset(
                    peer_node_id
                    for peer_node_id in peer_node_ids.values()
                    if any(
                        item.node_id == peer_node_id
                        and item.taxonomy_presentation == "structural_umbrella"
                        for item in open_construction_graph_v2.neighbors(peer_node_id).nodes
                    )
                )
            except OpenConstructionV2MapStoreError:
                # Exact catalog artist evidence can exist for a node that is
                # absent from a configured map artifact; do not invent a
                # hierarchy or hide the independent direct-claim panel.
                hierarchy = None
        return Template(
            template_name="open_artist_navigation.html",
            context={
                "node_id": node_id,
                "genre_response": response,
                "peer_response": peers,
                "peer_node_ids": peer_node_ids,
                "structural_peer_node_ids": structural_peer_node_ids,
                "hierarchy": hierarchy,
            },
        )

    @get("/fragments/open-construction-map/v2/artists/{node_id:str}/artist/{artist_id:int}")
    async def open_v2_artist_fragment(
        self,
        public_artist_navigation: NamedDependency[PublicArtistNavigationStore],
        node_id: FromPath[str],
        artist_id: FromPath[int],
    ) -> Template:
        """Render direct artist genres and shared-direct-genre relations in one panel."""
        try:
            genres = await public_artist_navigation.artist_genres(artist_id, offset=0, limit=20)
            related = await public_artist_navigation.related_artists(artist_id, offset=0, limit=20)
            open_node_ids = await public_artist_navigation.open_node_ids_for_catalog_genres(
                tuple(item.genre.entity_id for item in genres.genres)
            )
        except PublicArtistNavigationStoreError as error:
            raise ServiceUnavailableException(
                detail="public artist navigation is unavailable"
            ) from error
        return Template(
            template_name="open_artist_navigation_artist.html",
            context={
                "node_id": node_id,
                "genres_response": genres,
                "related_response": related,
                "open_node_ids": open_node_ids,
            },
        )

    @get("/api/genres/{genre_id:int}/artists")
    async def genre_artists(
        self,
        public_artist_navigation: NamedDependency[PublicArtistNavigationStore],
        genre_id: FromPath[int],
        offset: FromQuery[int] = 0,
        limit: FromQuery[int] = 20,
    ) -> GenreArtistsResponse:
        """Page only direct, display-authorized artist claims for a known catalog genre."""
        try:
            return await public_artist_navigation.genre_artists(
                genre_id, offset=offset, limit=limit
            )
        except PublicArtistNavigationStoreError as error:
            if "not found" in str(error):
                raise NotFoundException(detail="genre not found") from error
            raise ValidationException(detail=str(error)) from error

    @get("/api/artists/{artist_id:int}")
    async def artist_detail(
        self,
        public_artist_navigation: NamedDependency[PublicArtistNavigationStore],
        artist_id: FromPath[int],
    ) -> ArtistGenresResponse:
        """Return a known artist and its first direct-genre page for API traversal."""
        try:
            return await public_artist_navigation.artist_genres(artist_id, offset=0, limit=20)
        except PublicArtistNavigationStoreError as error:
            if "not found" in str(error):
                raise NotFoundException(detail="artist not found") from error
            raise ValidationException(detail=str(error)) from error

    @get("/api/artists/{artist_id:int}/genres")
    async def artist_genres(
        self,
        public_artist_navigation: NamedDependency[PublicArtistNavigationStore],
        artist_id: FromPath[int],
        offset: FromQuery[int] = 0,
        limit: FromQuery[int] = 20,
    ) -> ArtistGenresResponse:
        """Page only direct, display-authorized genre claims for a known artist."""
        try:
            return await public_artist_navigation.artist_genres(
                artist_id, offset=offset, limit=limit
            )
        except PublicArtistNavigationStoreError as error:
            if "not found" in str(error):
                raise NotFoundException(detail="artist not found") from error
            raise ValidationException(detail=str(error)) from error

    @get("/api/artists/{artist_id:int}/related")
    async def related_artists(
        self,
        public_artist_navigation: NamedDependency[PublicArtistNavigationStore],
        artist_id: FromPath[int],
        offset: FromQuery[int] = 0,
        limit: FromQuery[int] = 20,
    ) -> RelatedArtistsResponse:
        """Page transparent related artists by shared direct genre, never a learned score."""
        try:
            return await public_artist_navigation.related_artists(
                artist_id, offset=offset, limit=limit
            )
        except PublicArtistNavigationStoreError as error:
            if "not found" in str(error):
                raise NotFoundException(detail="artist not found") from error
            raise ValidationException(detail=str(error)) from error

    @get("/api/genres/{genre_id:int}")
    async def genre_detail(
        self,
        database: NamedDependency[AsyncDatabase],
        genre_entries: NamedDependency[GenreEntryRepository],
        genre_id: FromPath[int],
    ) -> GenreDetail:
        """Return one genre and its policy-safe evidence."""
        detail = await database.genre_detail(genre_id)
        if detail is None:
            raise NotFoundException(detail="genre not found")
        return await genre_entries.enrich(detail)

    @get("/api/entities/{entity_id:int}/provenance")
    async def entity_provenance(
        self,
        database: NamedDependency[AsyncDatabase],
        entity_id: FromPath[int],
    ) -> ProvenanceResponse:
        """Return policy-safe evidence attached to one entity."""
        return ProvenanceResponse(
            entity_id=entity_id,
            evidence=await database.entity_provenance(entity_id),
        )

    @get("/api/entities/{entity_id:int}/hydrated-release")
    async def hydrated_release(
        self, database: NamedDependency[AsyncDatabase], entity_id: FromPath[int]
    ) -> HydratedReleaseMetadata:
        """Return one non-playable hydrated release or a normal empty-state 404."""
        release = await database.hydrated_release_metadata(entity_id)
        if release is None:
            raise NotFoundException(detail="hydrated release metadata not found")
        return release

    @get("/fragments/entities/{entity_id:int}/hydrated-release", media_type=MediaType.HTML)
    async def hydrated_release_fragment(
        self, database: NamedDependency[AsyncDatabase], entity_id: FromPath[int]
    ) -> Template:
        """Render a compact no-JavaScript release-track metadata fragment."""
        return Template(
            template_name="hydrated_release.html",
            context={"release": await database.hydrated_release_metadata(entity_id)},
        )

    @get(
        "/fragments/musicbrainz/{entity_kind:str}/{source_id:str}/hydrated-release",
        media_type=MediaType.HTML,
    )
    async def hydrated_release_source_fragment(
        self,
        database: NamedDependency[AsyncDatabase],
        entity_kind: FromPath[str],
        source_id: FromPath[str],
    ) -> Template:
        """Render hydrated metadata for one exact representative source identity."""
        if entity_kind not in {"release_group", "recording"}:
            raise NotFoundException(detail="unsupported hydrated metadata identity")
        return Template(
            template_name="hydrated_release.html",
            context={
                "release": await database.hydrated_release_metadata_by_source(
                    entity_kind, source_id
                )
            },
        )

    @get("/fragments/genre-detail-empty", media_type=MediaType.HTML)
    async def empty_genre_detail(self) -> str:
        """Clear the progressive-enhancement detail slot without replacing the map."""
        return ""

    @get("/fragments/genres/{genre_id:int}")
    async def genre_detail_fragment(
        self,
        database: NamedDependency[AsyncDatabase],
        genre_entries: NamedDependency[GenreEntryRepository],
        genre_id: FromPath[int],
        q: FromQuery[str] = "",
        layout: FromQuery[str] = "default",
    ) -> Template:
        """Render one bounded genre detail region."""
        detail = await database.genre_detail(genre_id)
        if detail is None:
            raise NotFoundException(detail="genre not found")
        detail = await genre_entries.enrich(detail)
        layout_key, _ = resolve_layout(layout, await database.published_layouts())
        placement = await database.genre_placement(genre_id, layout_key)
        return Template(
            template_name="genre_detail.html",
            context={
                "genre": detail,
                "layout_key": placement.layout_key,
                "layout_query": None if layout == "default" else placement.layout_key,
                "placement": placement,
                "search_query": q[:500],
            },
        )

    @get("/fragments/genres/key/{genre_key:str}")
    async def genre_detail_key_fragment(
        self,
        database: NamedDependency[AsyncDatabase],
        genre_entries: NamedDependency[GenreEntryRepository],
        genre_key: FromPath[str],
        q: FromQuery[str] = "",
        layout: FromQuery[str] = "default",
    ) -> Template:
        """Render detail for a stable public key while preserving the normal-link fallback."""
        genre_id = await database.genre_id_for_public_key(genre_key)
        if genre_id is None:
            raise NotFoundException(detail="genre not found")
        detail = await database.genre_detail(genre_id)
        if detail is None:
            raise NotFoundException(detail="genre not found")
        detail = await genre_entries.enrich(detail)
        layout_key, _ = resolve_layout(layout, await database.published_layouts())
        placement = await database.genre_placement(genre_id, layout_key)
        return Template(
            template_name="genre_detail.html",
            context={
                "genre": detail,
                "layout_key": placement.layout_key,
                "layout_query": None if layout == "default" else placement.layout_key,
                "placement": placement,
                "search_query": q[:500],
            },
        )


def map_query(
    *,
    layout: str,
    lens: CatalogLens,
    level_of_detail: LevelOfDetail,
    source: str | None,
    as_of: datetime | None,
    min_x: float | None,
    min_y: float | None,
    max_x: float | None,
    max_y: float | None,
    limit: int,
) -> MapQuery:
    """Parse route values into one map query or a client error."""
    try:
        return MapQuery(
            layout_key=layout,
            lens=lens,
            level_of_detail=level_of_detail,
            source_key=source,
            observed_at_or_before=as_of,
            viewport=optional_viewport(min_x, min_y, max_x, max_y),
            limit=limit,
        )
    except ValueError as error:
        raise ValidationException(detail=str(error)) from error


def parsed_layout_key(value: str) -> str:
    """Parse an external layout key through the shared map query contract."""
    try:
        return MapQuery(layout_key=value).layout_key
    except ValueError as error:
        raise ValidationException(detail=str(error)) from error


def resolve_layout(
    requested: str, layouts: tuple[PublishedLayout, ...]
) -> tuple[str, PublishedLayout | None]:
    """Resolve the stable default sentinel to the published default lens."""
    layout_key = parsed_layout_key(requested)
    if layout_key == "default":
        active = next((item for item in layouts if item.is_default), None)
        active = active or next((item for item in layouts if item.layout_key == "default"), None)
    else:
        active = next((item for item in layouts if item.layout_key == layout_key), None)
    if active is not None:
        return active.layout_key, active
    if layouts or layout_key != "default":
        raise NotFoundException(detail="layout not found")
    return layout_key, None


async def workspace_context(
    database: AsyncDatabase,
    genre_entries: GenreEntryRepository,
    production_map: ProductionMapStore,
    historical_signal_map: HistoricalSignalMapStore,
    open_construction_graph: OpenConstructionMapStore,
    open_construction_graph_v2: OpenConstructionV2MapStore,
    local_research_map: LocalResearchMapStore | None,
    *,
    layout: str,
    focus: int | None,
    search_query: str,
    view: Literal["public", "open", "historical"],
    local_research_artist_evidence_configured: bool = False,
    local_research_map_configured: bool = False,
) -> dict[str, object]:
    """Build one consistent workspace from a published layout and optional genre."""
    layouts = await database.published_layouts()
    layout_key, active_layout = resolve_layout(layout, layouts)
    genre = None
    placement = None
    if focus is not None:
        genre = await database.genre_detail(focus)
        if genre is None:
            raise NotFoundException(detail="genre not found")
        genre = await genre_entries.enrich(genre)
        placement = await database.genre_placement(focus, layout_key)
    bounded_search_query = search_query[:500]
    production_graph: ProductionMapApiResponse | None = None
    historical_overview: tuple[HistoricalSignalHierarchyNode, ...] = ()
    if production_map.configured and layout == "default":
        try:
            production_graph = production_map.response()
        except ProductionMapStoreError as error:
            raise ServiceUnavailableException(
                detail="production map artifact unavailable"
            ) from error
    if view == "historical" and historical_signal_map.configured:
        try:
            historical_response = historical_signal_map.response(level=0)
            historical_overview = historical_response.hierarchy if historical_response else ()
        except HistoricalSignalMapStoreError:
            # A malformed optional artifact must not turn the no-JS shell into a 500.
            historical_overview = ()
    return {
        "active_layout": active_layout,
        "genre": genre,
        "layout_key": layout_key,
        "layout_query": None if layout == "default" else layout_key,
        "layouts": layouts,
        "public_layouts": tuple(item for item in layouts if item.layout_key in PUBLIC_LAYOUT_KEYS),
        "map": map_view(await database.map_points(layout_key), focus),
        "placement": placement,
        "production_graph": production_graph,
        "hits": (
            local_research_map.search(bounded_search_query)
            if view == "open"
            and local_research_map is not None
            and local_research_map.configured
            and bounded_search_query
            else open_construction_graph_v2.search(bounded_search_query).hits
            if view == "open" and open_construction_graph_v2.configured and bounded_search_query
            else await database.search(bounded_search_query)
            if bounded_search_query
            else ()
        ),
        "search_query": bounded_search_query,
        "map_view_mode": view,
        "historical_map_configured": historical_signal_map.configured,
        "historical_overview": historical_overview,
        "open_construction_graph_configured": open_construction_graph.configured,
        "open_construction_graph_v2_configured": open_construction_graph_v2.configured,
        "local_research_artist_evidence_configured": local_research_artist_evidence_configured,
        "local_research_map_configured": local_research_map_configured,
    }


def detail_template(context: dict[str, object]) -> Template:
    """Render only the persistent detail slot for an HTMX normal-link request."""
    return Template(
        template_name="genre_detail.html",
        context={
            "genre": context["genre"],
            "layout_key": context["layout_key"],
            "layout_query": context["layout_query"],
            "placement": context["placement"],
            "search_query": context["search_query"],
        },
    )
