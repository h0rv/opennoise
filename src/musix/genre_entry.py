"""Policy-safe reads for the bounded genre entry experience."""

import asyncio
import sqlite3
from pathlib import Path

from musix.db import Database
from musix.exploration import (
    GenreDetail,
    GenreDiscoveryItem,
    GenreExternalLink,
    HistoricalGenreRepresentative,
)
from musix.metadata_links import metadata_url
from musix.models.modeling import MetadataKind

ARTIST_LIMIT = 6
ALBUM_LIMIT = 6
TRACK_LIMIT = 6
NEIGHBOR_LIMIT = 8


class GenreEntryRepository:
    """Read optional discovery data using one short-lived SQLite operation."""

    def __init__(self, database_path: Path) -> None:
        """Bind the repository to the same local catalog as the app."""
        self._database = Database(database_path)
        self._calls = asyncio.Semaphore(4)

    async def enrich(self, detail: GenreDetail) -> GenreDetail:
        """Attach display-safe discovery fields without blocking the event loop."""
        async with self._calls:
            representative, artists, albums, tracks, neighbors = await asyncio.to_thread(
                self._read,
                detail.entity_id,
            )
        return GenreDetail(
            entity_id=detail.entity_id,
            slug=detail.slug,
            name=detail.name,
            description=detail.description,
            evidence=detail.evidence,
            historical_representative=representative,
            representative_artists=artists,
            defining_albums=albums,
            defining_tracks=tracks,
            playable_links=detail.playable_links,
            neighbors=neighbors,
        )

    def _read(
        self,
        genre_id: int,
    ) -> tuple[
        HistoricalGenreRepresentative | None,
        tuple[GenreDiscoveryItem, ...],
        tuple[GenreDiscoveryItem, ...],
        tuple[GenreDiscoveryItem, ...],
        tuple[GenreDiscoveryItem, ...],
    ]:
        with self._database.connect() as connection:
            representative_row = connection.execute(
                """SELECT artist.source_artist_name, track.source_track_title,
                          track.recording_provider, track.safe_external_url
                   FROM displayable_historical_genre_tracks AS track
                   JOIN displayable_historical_genre_artists AS artist
                     ON artist.id = track.artist_observation_id
                   WHERE track.genre_id = ? AND artist.genre_id = track.genre_id
                     AND artist.observation_role = 'representative'
                   ORDER BY track.source_revision_date DESC, track.id
                   LIMIT 1""",
                (genre_id,),
            ).fetchone()
            public_rows = connection.execute(
                """SELECT entity_kind, source_entity_ref, display_name
                   FROM displayable_public_genre_representatives
                   WHERE genre_id = ? AND rank <= ?
                   ORDER BY entity_kind, rank, source_entity_ref""",
                (genre_id, max(ARTIST_LIMIT, ALBUM_LIMIT, TRACK_LIMIT)),
            ).fetchall()
            album_rows = connection.execute(
                """WITH album_names AS (
                       SELECT membership.release_group_id,
                              name.name,
                              row_number() OVER (
                                  PARTITION BY membership.release_group_id
                                  ORDER BY (name.name_kind = 'primary') DESC,
                                           name.is_preferred DESC,
                                           (name.language_tag = 'und') DESC,
                                           name.id
                              ) AS name_rank
                       FROM displayable_album_genre_memberships AS membership
                       JOIN displayable_entity_names AS name
                         ON name.entity_id = membership.release_group_id
                       WHERE membership.genre_id = ?
                   )
                   SELECT release_group_id, name
                   FROM album_names
                   WHERE name_rank = 1
                   ORDER BY name COLLATE NOCASE, release_group_id
                   LIMIT ?""",
                (genre_id, ALBUM_LIMIT),
            ).fetchall()
            neighbor_rows = connection.execute(
                """WITH neighbor_names AS (
                       SELECT relation.related_genre_id,
                              name.name,
                              min(coalesce(relation.source_local_rank, 2147483647)) AS rank
                       FROM displayable_historical_genre_relations AS relation
                       JOIN displayable_entity_names AS name
                         ON name.entity_id = relation.related_genre_id
                       WHERE relation.genre_id = ? AND relation.related_genre_id IS NOT NULL
                       GROUP BY relation.related_genre_id
                   )
                   SELECT related_genre_id, name
                   FROM neighbor_names
                   ORDER BY rank, name COLLATE NOCASE, related_genre_id
                   LIMIT ?""",
                (genre_id, NEIGHBOR_LIMIT),
            ).fetchall()
        representative = _representative(representative_row)
        artists = _public_items(public_rows, "artist", ARTIST_LIMIT)
        albums = _public_items(public_rows, "release_group", ALBUM_LIMIT)
        if not albums:
            albums = tuple(
                GenreDiscoveryItem(entity_id=int(row[0]), name=str(row[1])) for row in album_rows
            )
        tracks = _public_items(public_rows, "recording", TRACK_LIMIT)
        neighbors = tuple(
            GenreDiscoveryItem(
                entity_id=int(row[0]),
                name=str(row[1]),
                href=f"/genres/{int(row[0])}",
            )
            for row in neighbor_rows
        )
        return representative, artists, albums, tracks, neighbors


def _public_items(
    rows: list[sqlite3.Row],
    entity_kind: MetadataKind,
    limit: int,
) -> tuple[GenreDiscoveryItem, ...]:
    """Build bounded outbound items only from kind-matched public identifiers."""
    result: list[GenreDiscoveryItem] = []
    for row in rows:
        if str(row[0]) != entity_kind:
            continue
        source_ref = str(row[1])
        href = metadata_url(entity_kind, source_ref)
        if href is None:
            continue
        result.append(GenreDiscoveryItem(name=str(row[2]), href=href))
        if len(result) == limit:
            break
    return tuple(result)


def _representative(row: sqlite3.Row | None) -> HistoricalGenreRepresentative | None:
    if row is None:
        return None
    values = tuple(row)
    external_url = str(values[3]) if values[3] is not None else None
    link = (
        GenreExternalLink(label=str(values[2]).title(), url=external_url)
        if external_url is not None
        else None
    )
    return HistoricalGenreRepresentative(
        artist_name=str(values[0]),
        track_title=str(values[1]),
        external_link=link,
    )
