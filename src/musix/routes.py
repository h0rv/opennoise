"""Typed Litestar routes for map, search, and evidence fragments."""

from datetime import datetime

from litestar import Controller, MediaType, Request, get
from litestar.di import NamedDependency
from litestar.exceptions import NotFoundException, ValidationException
from litestar.params import FromPath, FromQuery
from litestar.response import Template

from musix.db import AsyncDatabase
from musix.exploration import (
    CatalogLens,
    GenreDetail,
    LevelOfDetail,
    MapQuery,
    ProvenanceResponse,
    optional_viewport,
)
from musix.genre_entry import GenreEntryRepository
from musix.layouts import ExploredMap, LayoutArtifactMetadata, PublishedLayout
from musix.models import (
    MapPointResponse,
    MapResponse,
    SearchHitResponse,
    SearchResponse,
    map_view,
)


class CoreController(Controller):
    """Render the app shell and health response."""

    @get("/")
    async def index(
        self,
        database: NamedDependency[AsyncDatabase],
        genre_entries: NamedDependency[GenreEntryRepository],
        layout: FromQuery[str] = "default",
        q: FromQuery[str] = "",
    ) -> Template:
        """Render the current full map."""
        context = await workspace_context(
            database, genre_entries, layout=layout, focus=None, search_query=q
        )
        return Template(template_name="index.html", context=context)

    @get("/genres/{genre_id:int}")
    async def selected_genre(
        self,
        database: NamedDependency[AsyncDatabase],
        genre_entries: NamedDependency[GenreEntryRepository],
        genre_id: FromPath[int],
        request: Request[object, object, object],
        layout: FromQuery[str] = "default",
        q: FromQuery[str] = "",
    ) -> Template:
        """Render a shareable genre selection with the complete app shell."""
        context = await workspace_context(
            database, genre_entries, layout=layout, focus=genre_id, search_query=q
        )
        if request.headers.get("HX-Request") == "true":
            return detail_template(context)
        return Template(template_name="index.html", context=context)

    @get("/genres/key/{genre_key:str}")
    async def selected_genre_key(
        self,
        database: NamedDependency[AsyncDatabase],
        genre_entries: NamedDependency[GenreEntryRepository],
        genre_key: FromPath[str],
        request: Request[object, object, object],
        layout: FromQuery[str] = "default",
        q: FromQuery[str] = "",
    ) -> Template:
        """Open a stable public key, resolving its current local entity only server-side."""
        genre_id = await database.genre_id_for_public_key(genre_key)
        if genre_id is None:
            raise NotFoundException(detail="genre not found")
        context = await workspace_context(
            database, genre_entries, layout=layout, focus=genre_id, search_query=q
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
        layout: FromQuery[str] = "default",
    ) -> MapResponse:
        """Return the stable map JSON shape."""
        layout_key, _ = resolve_layout(layout, await database.published_layouts())
        points = await database.map_points(layout_key)
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
                "map": view,
            },
        )

    @get("/fragments/workspace")
    async def workspace_fragment(
        self,
        database: NamedDependency[AsyncDatabase],
        genre_entries: NamedDependency[GenreEntryRepository],
        focus: FromQuery[int | None] = None,
        layout: FromQuery[str] = "default",
        q: FromQuery[str] = "",
    ) -> Template:
        """Render one coherent map selection and detail fragment."""
        context = await workspace_context(
            database, genre_entries, layout=layout, focus=focus, search_query=q
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
                "placement": placement,
            },
        )

    @get("/fragments/genres/key/{genre_key:str}")
    async def genre_detail_key_fragment(
        self,
        database: NamedDependency[AsyncDatabase],
        genre_entries: NamedDependency[GenreEntryRepository],
        genre_key: FromPath[str],
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
                "placement": placement,
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
    *,
    layout: str,
    focus: int | None,
    search_query: str,
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
    return {
        "active_layout": active_layout,
        "genre": genre,
        "layout_key": layout_key,
        "layouts": layouts,
        "map": map_view(await database.map_points(layout_key), focus),
        "placement": placement,
        "hits": await database.search(bounded_search_query) if bounded_search_query else (),
        "search_query": bounded_search_query,
    }


def detail_template(context: dict[str, object]) -> Template:
    """Render only the persistent detail slot for an HTMX normal-link request."""
    return Template(
        template_name="genre_detail.html",
        context={
            "genre": context["genre"],
            "layout_key": context["layout_key"],
            "placement": context["placement"],
            "search_query": context["search_query"],
        },
    )
