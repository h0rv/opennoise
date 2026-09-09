"""Read bounded local MusicBrainz peer evidence for the loopback panel."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import dataclass
from typing import TYPE_CHECKING

from pydantic import Field, FiniteFloat

from musix.models import FrozenModel

if TYPE_CHECKING:
    from pathlib import Path

    from musix.taxonomy.seeds.seed_reconciliation import SeedReconciliationArtifact

_MAX_RESULTS = 10


class LocalMusicBrainzPeerStoreError(ValueError):
    """Report an unavailable or incompatible local peer index."""


class LocalMusicBrainzPeer(FrozenModel):
    """One direct-membership-overlap neighbor from the local peer index."""

    source_item_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    score: FiniteFloat = Field(gt=0.0)
    shared_direct_artist_count: int = Field(ge=1)


@dataclass(slots=True)
class LocalMusicBrainzPeerStore:
    """Startup-checked, read-only access to the compact local peer index."""

    index_path: Path
    reconciliation: SeedReconciliationArtifact
    _ready: bool = False

    def start(self) -> None:
        """Check local-only metadata and SQLite integrity once at startup."""
        if not self.index_path.is_file() or self.index_path.suffix == ".partial":
            raise LocalMusicBrainzPeerStoreError("local peer index is unavailable")
        database_uri = f"file:{self.index_path.absolute()}?mode=ro"
        with closing(sqlite3.connect(database_uri, uri=True)) as connection:
            connection.execute("PRAGMA query_only = ON")
            if connection.execute("PRAGMA integrity_check").fetchone() != ("ok",):
                raise LocalMusicBrainzPeerStoreError("local peer index failed integrity check")
            metadata = dict(connection.execute("SELECT key, value FROM metadata"))
            if (
                metadata.get("non_production_candidate") != "true"
                or metadata.get("all_inputs_export_allowed") != "false"
            ):
                raise LocalMusicBrainzPeerStoreError(
                    "local peer index is not a local-only candidate"
                )
            tables = {
                str(row[0])
                for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
            }
            if not {"seed", "peer_edge"} <= tables:
                raise LocalMusicBrainzPeerStoreError("local peer index schema is incompatible")
        self._ready = True

    @property
    def configured(self) -> bool:
        """Whether startup validation completed successfully."""
        return self._ready

    def neighbors(self, source_item_id: str) -> tuple[LocalMusicBrainzPeer, ...]:
        """Return the top bounded direct-overlap neighbors for one exact seed ID."""
        if not self._ready:
            raise LocalMusicBrainzPeerStoreError("local peer index is not certified")
        names = {row.source_item_id: row.seed_name for row in self.reconciliation.dispositions}
        if source_item_id not in names:
            raise LocalMusicBrainzPeerStoreError("local peer query has an unknown stable seed")
        database_uri = f"file:{self.index_path.absolute()}?mode=ro"
        with closing(sqlite3.connect(database_uri, uri=True)) as connection:
            connection.execute("PRAGMA query_only = ON")
            rows = connection.execute(
                """SELECT source_genre_id, target_genre_id, direct_score, shared_direct_artist_count
                     FROM peer_edge
                    WHERE source_genre_id = ? OR target_genre_id = ?
                    ORDER BY direct_score DESC,
                      CASE WHEN source_genre_id = ? THEN target_genre_id ELSE source_genre_id END
                    LIMIT ?""",
                (source_item_id, source_item_id, source_item_id, _MAX_RESULTS),
            ).fetchall()
        result: list[LocalMusicBrainzPeer] = []
        for source, target, score, shared in rows:
            neighbor_id = str(target) if source == source_item_id else str(source)
            if (
                neighbor_id not in names
                or not isinstance(score, float)
                or not isinstance(shared, int)
            ):
                raise LocalMusicBrainzPeerStoreError("local peer index has an invalid edge")
            result.append(
                LocalMusicBrainzPeer(
                    source_item_id=neighbor_id,
                    name=names[neighbor_id],
                    score=score,
                    shared_direct_artist_count=shared,
                )
            )
        return tuple(result)
