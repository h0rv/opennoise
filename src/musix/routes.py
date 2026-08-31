"""Typed Litestar routes for map, search, and evidence fragments."""

from datetime import datetime

from litestar import Controller, MediaType, get
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
from musix.layouts import ExploredMap, LayoutArtifactMetadata
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
    async def index(self, database: NamedDependency[AsyncDatabase]) -> Template:
        """Render the current full map."""
        view = map_view(await database.map_points())
        return Template(template_name="index.html", context={"map": view})

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
        query = map_query(
            layout=layout,
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
        query = map_query(
            layout=layout,
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
        return Template(template_name="map.html", context={"map": view})


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
    ) -> Template:
        """Render search results for the bounded results region."""
        hits = await database.search(q[:500])
        return Template(template_name="search_results.html", context={"hits": hits})


class EvidenceController(Controller):
    """Serve genre detail and provenance contracts."""

    @get("/api/genres/{genre_id:int}")
    async def genre_detail(
        self,
        database: NamedDependency[AsyncDatabase],
        genre_id: FromPath[int],
    ) -> GenreDetail:
        """Return one genre and its policy-safe evidence."""
        detail = await database.genre_detail(genre_id)
        if detail is None:
            raise NotFoundException(detail="genre not found")
        return detail

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

    @get("/fragments/genres/{genre_id:int}")
    async def genre_detail_fragment(
        self,
        database: NamedDependency[AsyncDatabase],
        genre_id: FromPath[int],
    ) -> Template:
        """Render one bounded genre detail region."""
        detail = await database.genre_detail(genre_id)
        if detail is None:
            raise NotFoundException(detail="genre not found")
        return Template(template_name="genre_detail.html", context={"genre": detail})


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
