"""SQLite schema lifecycle and policy-safe catalog queries."""

import asyncio
import sqlite3
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

from musix.models import MapPoint, SearchHit

SCHEMA_VERSION = 1
DEFAULT_DATABASE_PATH = Path("data/musix.sqlite")
DEFAULT_MIGRATION_PATH = Path("migrations/0001_initial.sql")
MAX_FTS_TERMS = 8


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
            if version == 0:
                connection.executescript(self.migration_path.read_text(encoding="utf-8"))
                version = connection.execute("PRAGMA user_version").fetchone()[0]
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


"""SQLite schema lifecycle and policy-safe catalog queries."""
