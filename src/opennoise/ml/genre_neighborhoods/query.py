"""Bounded, provenance-preserving read API for a certified neighborhood cache."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from opennoise.common import sha256_file

from .contracts import GenreNeighborhoodArtifact, GenreNeighborhoodError, verify_artifact


@dataclass(frozen=True, slots=True)
class GenreNeighbor:
    """One ranked peer and enough aggregate support for an explanation UI."""

    seed_id: str
    score: float
    unshrunk_npmi: float
    raw_mass: float
    window_support: int
    artist_pair_support: int


@dataclass(frozen=True, slots=True)
class GenreNeighborhoodPage:
    """A bounded peer page for one exact channel-local stable-seed state."""

    seed_id: str
    channel: Literal["artist_direct", "reviewed_alias_context"]
    state: Literal["observed", "abstained", "isolated"]
    total_neighbor_count: int
    neighbors: tuple[GenreNeighbor, ...]


@dataclass(frozen=True, slots=True)
class CertifiedNeighborhoodCache:
    """A cache path admitted only after its sealed model artifact replays and byte-binds."""

    database: Path
    artifact: GenreNeighborhoodArtifact


def certify_neighborhood_cache(
    database: Path, artifact: GenreNeighborhoodArtifact
) -> CertifiedNeighborhoodCache:
    """Verify the model's logical artifact and cache bytes before serving a query."""
    verify_artifact(artifact)
    if sha256_file(database) != (
        artifact.cache_database_sha256,
        artifact.cache_database_byte_count,
    ):
        raise GenreNeighborhoodError("neighborhood cache does not bind its artifact")
    return CertifiedNeighborhoodCache(database, artifact)


def neighbors_for_seed(
    cache: CertifiedNeighborhoodCache,
    seed_id: str,
    *,
    channel: Literal["artist_direct", "reviewed_alias_context"] = "artist_direct",
    limit: int = 20,
) -> GenreNeighborhoodPage:
    """Return at most 200 pre-ranked neighbors and their raw support provenance."""
    if not 1 <= limit <= 200:
        raise GenreNeighborhoodError("query limit must be between 1 and 200")
    with closing(
        sqlite3.connect(f"{cache.database.resolve().as_uri()}?mode=ro&immutable=1", uri=True)
    ) as database:
        state = database.execute(
            "SELECT state FROM genre_state WHERE channel = ? AND seed_id = ?", (channel, seed_id)
        ).fetchone()
        if state is None:
            raise GenreNeighborhoodError("unknown stable seed")
        total = int(
            database.execute(
                "SELECT count(*) FROM neighbor WHERE channel = ? AND seed_id = ?",
                (channel, seed_id),
            ).fetchone()[0]
        )
        rows = database.execute(
            "SELECT neighbor_seed_id, shrunk_npmi, unshrunk_npmi, raw_mass, window_support, artist_pair_support "
            "FROM neighbor WHERE channel = ? AND seed_id = ? ORDER BY rank LIMIT ?",
            (channel, seed_id, limit),
        ).fetchall()
    return GenreNeighborhoodPage(
        seed_id,
        channel,
        _state_from_sql(str(state[0])),
        total,
        tuple(
            GenreNeighbor(str(a), float(b), float(c), float(d), int(e), int(f))
            for a, b, c, d, e, f in rows
        ),
    )


def _state_from_sql(value: str) -> Literal["observed", "abstained", "isolated"]:
    """Convert the SQLite checked-state value into the closed public API union."""
    match value:
        case "observed":
            return "observed"
        case "abstained":
            return "abstained"
        case "isolated":
            return "isolated"
        case _:
            raise GenreNeighborhoodError("cache has an invalid genre state")
