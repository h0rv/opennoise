"""SQLite schema lifecycle and policy-safe catalog queries."""

import asyncio
import sqlite3
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from pydantic import JsonValue, TypeAdapter

from musix.exploration import (
    CatalogLens,
    GenreDetail,
    MapQuery,
    MapQueryResult,
    ProvenanceEvidence,
    Viewport,
)
from musix.layouts import (
    DerivedCoordinateSpace,
    HistoricCoordinateSpace,
    LayoutArtifactMetadata,
    LayoutStrategyVersion,
)
from musix.models import MapPoint, SearchHit

SCHEMA_VERSION = 5
DEFAULT_DATABASE_PATH = Path("data/musix.sqlite")
DEFAULT_MIGRATION_PATH = Path("migrations/0001_initial.sql")
DEFAULT_MIGRATION_PATHS = (
    DEFAULT_MIGRATION_PATH,
    Path("migrations/0002_album_genres.sql"),
    Path("migrations/0003_genre_discovery.sql"),
    Path("migrations/0004_artist_genre_membership.sql"),
    Path("migrations/0005_artist_co_listen_evidence.sql"),
)
MAX_FTS_TERMS = 8
FIELD_SET_ADAPTER = TypeAdapter(tuple[str, ...])
PARAMETERS_ADAPTER = TypeAdapter(dict[str, JsonValue])


class UnsupportedSchemaError(RuntimeError):
    """Report an on-disk database with an unsupported schema version."""


def fts_prefix_query(value: str) -> str | None:
    """Parse user text into a bounded literal FTS prefix query."""
    terms: list[str] = []
    for term in value.split():
        normalized = "".join(character for character in term if character.isalnum())
        if normalized:
            terms.append(f'"{normalized}"*')
        if len(terms) == MAX_FTS_TERMS:
            break
    return " AND ".join(terms) if terms else None


class Database:
    """Open short-lived SQLite connections to one catalog."""

    def __init__(self, path: Path, migration_path: Path = DEFAULT_MIGRATION_PATH) -> None:
        """Store paths without opening a connection."""
        self.path = path
        self.migration_path = migration_path

    def initialize(self) -> None:
        """Create a new database or confirm its schema version."""
        if self.path != Path(":memory:"):
            self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            migration_paths = (
                DEFAULT_MIGRATION_PATHS
                if self.migration_path == DEFAULT_MIGRATION_PATH
                else (self.migration_path,)
            )
            if version < 0 or version > len(migration_paths):
                raise UnsupportedSchemaError(
                    f"database schema is version {version}; expected {SCHEMA_VERSION}"
                )
            for target_version, migration_path in enumerate(migration_paths, start=1):
                if version >= target_version:
                    continue
                connection.executescript(migration_path.read_text(encoding="utf-8"))
                version = connection.execute("PRAGMA user_version").fetchone()[0]
                if version != target_version:
                    raise UnsupportedSchemaError(
                        f"migration {migration_path} produced version {version}; "
                        f"expected {target_version}"
                    )
            if version != SCHEMA_VERSION:
                raise UnsupportedSchemaError(
                    f"database schema is version {version}; expected {SCHEMA_VERSION}"
                )

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        """Yield one configured SQLite connection."""
        connection = sqlite3.connect(self.path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        if self.path != Path(":memory:"):
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("PRAGMA synchronous = NORMAL")
        try:
            yield connection
        finally:
            connection.close()

    def ping(self) -> None:
        """Run a minimal database health query."""
        with self.connect() as connection:
            connection.execute("SELECT 1").fetchone()

    def entity_count(self) -> int:
        """Return the number of catalog entities."""
        with self.connect() as connection:
            row = connection.execute("SELECT count(*) AS count FROM catalog_entities").fetchone()
        if row is None:
            raise RuntimeError("entity count query returned no row")
        return int(row["count"])

    def search(self, query: str, *, limit: int = 20) -> list[SearchHit]:
        """Search displayable artists and genres."""
        match_query = fts_prefix_query(query)
        if match_query is None:
            return []
        bounded_limit = min(max(limit, 1), 100)
        sql = """
            WITH ranked_names AS (
                SELECT entity_id, name,
                    row_number() OVER (
                        PARTITION BY entity_id
                        ORDER BY (name_kind = 'primary') DESC, is_preferred DESC,
                                 (language_tag = 'und') DESC, id
                    ) AS name_rank
                FROM displayable_entity_names
            ), scored_hits AS MATERIALIZED (
                SELECT document.entity_id, document.id,
                       bm25(search_documents_fts) AS score
                FROM search_documents_fts
                JOIN searchable_documents AS document
                  ON document.id = search_documents_fts.rowid
                JOIN catalog_entities AS entity ON entity.id = document.entity_id
                WHERE search_documents_fts MATCH ?
                  AND entity.entity_kind IN ('artist', 'genre')
                ORDER BY bm25(search_documents_fts), document.id
                LIMIT 1000
            ), ranked_hits AS (
                SELECT entity_id, min(score) AS score
                FROM scored_hits
                GROUP BY entity_id
            )
            SELECT hit.entity_id, entity.entity_kind, name.name
            FROM ranked_hits AS hit
            JOIN catalog_entities AS entity ON entity.id = hit.entity_id
            JOIN ranked_names AS name ON name.entity_id = hit.entity_id AND name.name_rank = 1
            ORDER BY hit.score, name.name COLLATE NOCASE, hit.entity_id
            LIMIT ?
        """
        with self.connect() as connection:
            rows = connection.execute(sql, (match_query, bounded_limit)).fetchall()
        return [
            SearchHit(entity_id=int(row[0]), entity_kind=str(row[1]), name=str(row[2]))
            for row in rows
        ]

    def map_points(self, layout_key: str = "default") -> list[MapPoint]:
        """Read points from one published, displayable layout."""
        sql = """
            SELECT entity_id, entity_kind, name, x, y, display_weight, color_hex
            FROM displayable_map_points
            WHERE layout_key = ?
            ORDER BY coalesce(display_weight, 0.0) DESC, name COLLATE NOCASE, entity_id
        """
        with self.connect() as connection:
            rows = connection.execute(sql, (layout_key,)).fetchall()
        return [
            MapPoint(
                entity_id=int(row[0]),
                entity_kind=str(row[1]),
                name=str(row[2]),
                x=float(row[3]),
                y=float(row[4]),
                display_weight=float(row[5]) if row[5] is not None else None,
                color_hex=str(row[6]) if row[6] is not None else None,
            )
            for row in rows
        ]

    def query_map(self, query: MapQuery) -> MapQueryResult:
        """Read a bounded layout region with explicit source, time, and lens filters."""
        viewport = query.viewport
        source_key = query.source_key
        observed_at = (
            _sqlite_timestamp(query.observed_at_or_before)
            if query.observed_at_or_before is not None
            else None
        )
        parameters: tuple[str | int | float | None, ...] = (
            query.layout_key,
            int(query.lens is CatalogLens.GENRES),
            viewport.minimum_x if viewport is not None else None,
            viewport.minimum_x if viewport is not None else None,
            viewport.maximum_x if viewport is not None else None,
            viewport.maximum_x if viewport is not None else None,
            viewport.minimum_y if viewport is not None else None,
            viewport.minimum_y if viewport is not None else None,
            viewport.maximum_y if viewport is not None else None,
            viewport.maximum_y if viewport is not None else None,
            source_key,
            observed_at,
            source_key,
            source_key,
            observed_at,
            observed_at,
            query.limit + 1,
        )
        sql = """
            SELECT point.entity_id, point.entity_kind, point.name, point.x, point.y,
                   point.display_weight, point.color_hex
            FROM displayable_map_points AS point
            WHERE point.layout_key = ?
              AND (? = 0 OR point.entity_kind = 'genre')
              AND (? IS NULL OR point.x >= ?)
              AND (? IS NULL OR point.x <= ?)
              AND (? IS NULL OR point.y >= ?)
              AND (? IS NULL OR point.y <= ?)
              AND (
                    (? IS NULL AND ? IS NULL)
                    OR EXISTS (
                        SELECT 1
                        FROM entity_provenance AS link
                        JOIN provenance_records AS provenance
                          ON provenance.id = link.provenance_id
                        JOIN data_sources AS source ON source.id = provenance.source_id
                        WHERE link.entity_id = point.entity_id
                          AND (? IS NULL OR source.source_key = ?)
                          AND (? IS NULL OR julianday(provenance.observed_at) <= julianday(?))
                    )
              )
            ORDER BY coalesce(point.display_weight, 0.0) DESC,
                     point.name COLLATE NOCASE, point.entity_id
            LIMIT ?
        """
        with self.connect() as connection:
            rows = connection.execute(sql, parameters).fetchall()
        truncated = len(rows) > query.limit
        points = tuple(self._map_point(row) for row in rows[: query.limit])
        return MapQueryResult(query=query, points=points, truncated=truncated)

    def layout_metadata(self, layout_key: str) -> LayoutArtifactMetadata | None:
        """Read metadata for one currently published layout artifact."""
        sql = """
            SELECT run.layout_key, run.revision, run.algorithm_key,
                   run.algorithm_revision, run.parameters_json, run.input_fingerprint,
                   run.random_seed, run.status, run.policy_id, run.created_at,
                   run.completed_at, count(point.entity_id) AS point_count,
                   min(point.x), min(point.y), max(point.x), max(point.y)
            FROM current_layouts AS current
            JOIN layout_runs AS run ON run.id = current.layout_run_id
            LEFT JOIN layout_points AS point ON point.layout_run_id = run.id
            WHERE current.layout_key = ?
            GROUP BY run.id
        """
        with self.connect() as connection:
            row = connection.execute(sql, (layout_key,)).fetchone()
        if row is None:
            return None
        parameters = PARAMETERS_ADAPTER.validate_json(str(row[4]))
        strategy_key = str(row[2])
        input_fingerprint = str(row[5])
        bounds = (
            Viewport(
                minimum_x=float(row[12]),
                minimum_y=float(row[13]),
                maximum_x=float(row[14]),
                maximum_y=float(row[15]),
            )
            if row[12] is not None
            and row[13] is not None
            and row[14] is not None
            and row[15] is not None
            and (float(row[12]) < float(row[14]) and float(row[13]) < float(row[15]))
            else None
        )
        return LayoutArtifactMetadata(
            layout_key=str(row[0]),
            revision=int(row[1]),
            strategy=LayoutStrategyVersion(key=strategy_key, revision=str(row[3])),
            parameters=parameters,
            input_fingerprint=input_fingerprint,
            random_seed=int(row[6]) if row[6] is not None else None,
            status=str(row[7]),
            policy_id=int(row[8]),
            created_at=_sqlite_datetime(str(row[9])),
            completed_at=_sqlite_datetime(str(row[10])) if row[10] is not None else None,
            point_count=int(row[11]),
            bounds=bounds,
            coordinate_space=(
                HistoricCoordinateSpace(
                    source_ref=input_fingerprint,
                    units="source_pixels",
                )
                if strategy_key == "source_coordinates"
                else DerivedCoordinateSpace(units="layout_units")
            ),
        )

    def entity_provenance(self, entity_id: int) -> tuple[ProvenanceEvidence, ...]:
        """Read policy-safe provenance attached to one entity."""
        sql = """
            SELECT provenance.id, source.source_key, source.name,
                   provenance.snapshot_ref, provenance.artifact_sha256,
                   provenance.parser_release_ref, provenance.observed_at,
                   policy.classification, link.field_set_json, link.is_primary
            FROM entity_provenance AS link
            JOIN provenance_records AS provenance ON provenance.id = link.provenance_id
            JOIN data_sources AS source ON source.id = provenance.source_id
            JOIN rights_policies AS policy ON policy.id = provenance.policy_id
            JOIN active_rights_policy_permissions AS permission
              ON permission.policy_id = policy.id
             AND permission.use_kind = 'display'
             AND permission.decision = 'allow'
            WHERE link.entity_id = ?
              AND NOT EXISTS (
                  SELECT 1
                  FROM active_suppressions AS suppression
                  WHERE suppression.use_kind IN ('all', 'display')
                    AND (
                        (suppression.target_kind = 'entity'
                         AND suppression.target_ref = CAST(link.entity_id AS TEXT))
                        OR (suppression.target_kind = 'provenance'
                            AND suppression.target_ref = CAST(provenance.id AS TEXT))
                        OR (suppression.target_kind = 'source'
                            AND suppression.target_ref = CAST(source.id AS TEXT))
                    )
              )
            ORDER BY link.is_primary DESC, provenance.observed_at DESC, provenance.id
        """
        with self.connect() as connection:
            rows = connection.execute(sql, (entity_id,)).fetchall()
        return tuple(
            ProvenanceEvidence(
                provenance_id=int(row[0]),
                source_key=str(row[1]),
                source_name=str(row[2]),
                snapshot_ref=str(row[3]),
                artifact_sha256=str(row[4]) if row[4] is not None else None,
                parser_release_ref=str(row[5]),
                observed_at=_sqlite_datetime(str(row[6])),
                policy_classification=str(row[7]),
                fields=FIELD_SET_ADAPTER.validate_json(str(row[8])),
                is_primary=bool(row[9]),
            )
            for row in rows
        )

    def genre_detail(self, entity_id: int) -> GenreDetail | None:
        """Read one genre with display-safe source evidence."""
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT genre.id, genre.slug, name.name, genre.description
                FROM genres AS genre
                JOIN displayable_entity_names AS name ON name.entity_id = genre.id
                WHERE genre.id = ?
                ORDER BY (name.name_kind = 'primary') DESC, name.is_preferred DESC,
                         (name.language_tag = 'und') DESC, name.id
                LIMIT 1
                """,
                (entity_id,),
            ).fetchone()
        if row is None:
            return None
        return GenreDetail(
            entity_id=int(row[0]),
            slug=str(row[1]),
            name=str(row[2]),
            description=str(row[3]) if row[3] is not None else None,
            evidence=self.entity_provenance(entity_id),
        )

    @staticmethod
    def _map_point(row: sqlite3.Row) -> MapPoint:
        """Parse one trusted SQLite row into a map point."""
        return MapPoint(
            entity_id=int(row[0]),
            entity_kind=str(row[1]),
            name=str(row[2]),
            x=float(row[3]),
            y=float(row[4]),
            display_weight=float(row[5]) if row[5] is not None else None,
            color_hex=str(row[6]) if row[6] is not None else None,
        )


class AsyncDatabase:
    """Expose short-lived SQLite operations through a bounded async boundary."""

    def __init__(self, path: Path, migration_path: Path = DEFAULT_MIGRATION_PATH) -> None:
        """Store a synchronous database and bound concurrent worker calls."""
        self._database = Database(path, migration_path)
        self._calls = asyncio.Semaphore(4)

    async def start(self) -> None:
        """Apply or verify the schema in one worker operation."""
        await self._call(self._database.initialize)

    async def stop(self) -> None:
        """Finish lifecycle shutdown; worker calls own their connections."""

    async def _call[T](self, operation: Callable[[], T]) -> T:
        """Run one complete database operation in a bounded worker slot."""
        async with self._calls:
            return await asyncio.to_thread(operation)

    async def ping(self) -> None:
        """Run a minimal async health query."""
        await self._call(self._database.ping)

    async def search(self, query: str, *, limit: int = 20) -> list[SearchHit]:
        """Search displayable artists and genres without blocking the event loop."""
        return await self._call(lambda: self._database.search(query, limit=limit))

    async def map_points(self, layout_key: str = "default") -> list[MapPoint]:
        """Read one published layout without blocking the event loop."""
        return await self._call(lambda: self._database.map_points(layout_key))

    async def query_map(self, query: MapQuery) -> MapQueryResult:
        """Read one bounded map query without blocking the event loop."""
        return await self._call(lambda: self._database.query_map(query))

    async def layout_metadata(self, layout_key: str) -> LayoutArtifactMetadata | None:
        """Read published layout metadata without blocking the event loop."""
        return await self._call(lambda: self._database.layout_metadata(layout_key))

    async def entity_provenance(self, entity_id: int) -> tuple[ProvenanceEvidence, ...]:
        """Read entity evidence without blocking the event loop."""
        return await self._call(lambda: self._database.entity_provenance(entity_id))

    async def genre_detail(self, entity_id: int) -> GenreDetail | None:
        """Read a genre detail record without blocking the event loop."""
        return await self._call(lambda: self._database.genre_detail(entity_id))


def _sqlite_datetime(value: str) -> datetime:
    """Parse the UTC timestamps written by the SQLite schema."""
    return datetime.fromisoformat(value)


def _sqlite_timestamp(value: datetime) -> str:
    """Format an aware timestamp like values written by the SQLite schema."""
    utc_value = value.astimezone(UTC).isoformat(timespec="milliseconds")
    return f"{utc_value.removesuffix('+00:00')}Z"


"""SQLite schema lifecycle and policy-safe catalog queries."""
