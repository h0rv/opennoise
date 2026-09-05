"""Typed Litestar routes for map, search, and evidence fragments."""

from datetime import datetime
from typing import TYPE_CHECKING, Literal

from litestar import Controller, MediaType, Request, get
from litestar.datastructures import State
from litestar.di import NamedDependency
from litestar.exceptions import NotFoundException, ServiceUnavailableException, ValidationException
from litestar.params import FromPath, FromQuery
from litestar.response import Template

from musix.db import AsyncDatabase
from musix.exploration import (
    CatalogLens,
    GenreDetail,
    HydratedReleaseMetadata,
    LevelOfDetail,
    MapQuery,
    ProvenanceResponse,
    optional_viewport,
)
from musix.genre_entry import GenreEntryRepository
from musix.historical_membership_store import (
    HistoricalMembershipStore,
    HistoricalMembershipStoreError,
    HistoricalSignalMembersApiResponse,
)
from musix.historical_signal_store import (
    HistoricalSignalMapApiResponse,
    HistoricalSignalMapStore,
    HistoricalSignalMapStoreError,
    HistoricalSignalNeighborApiResponse,
)
from musix.layouts import ExploredMap, LayoutArtifactMetadata, PublishedLayout
from musix.models import (
    LegacyMapResponse,
    MapPointResponse,
    SearchHitResponse,
    SearchResponse,
    map_view,
)
from musix.open_construction_store import (
    OpenConstructionMapResponse,
    OpenConstructionMapStore,
    OpenConstructionMapStoreError,
    OpenConstructionNeighborResponse,
)

if TYPE_CHECKING:
    from musix.models.historical_signal import HistoricalSignalHierarchyNode
from musix.production_store import (
    ProductionMapApiResponse,
    ProductionMapStore,
    ProductionMapStoreError,
)

PUBLIC_LAYOUT_KEYS = frozenset({"public", "public-direct", "public-community", "public-taxonomy"})


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
        layout: FromQuery[str] = "default",
        q: FromQuery[str] = "",
        view: FromQuery[Literal["public", "open", "historical"]] = "public",
    ) -> Template:
        """Render the current full map."""
        context = await workspace_context(
            database,
            genre_entries,
            production_map,
            historical_signal_map,
            open_construction_graph,
            layout=layout,
            focus=None,
            search_query=q,
            view=view,
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
        focus: FromQuery[int | None] = None,
        layout: FromQuery[str] = "default",
        q: FromQuery[str] = "",
        view: FromQuery[Literal["public", "open", "historical"]] = "public",
    ) -> Template:
        """Render one coherent map selection and detail fragment."""
        context = await workspace_context(
            database,
            genre_entries,
            production_map,
            historical_signal_map,
            open_construction_graph,
            layout=layout,
            focus=focus,
            search_query=q,
            view=view,
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


class EvidenceController(Controller):
    """Serve genre detail and provenance contracts."""

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
    *,
    layout: str,
    focus: int | None,
    search_query: str,
    view: Literal["public", "open", "historical"],
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
        "hits": await database.search(bounded_search_query) if bounded_search_query else (),
        "search_query": bounded_search_query,
        "map_view_mode": view,
        "historical_map_configured": historical_signal_map.configured,
        "historical_overview": historical_overview,
        "open_construction_graph_configured": open_construction_graph.configured,
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
