"""Bounded public artist navigation from display-authorized direct claims only."""

# ruff: noqa: S608  # Placeholder counts are derived solely from integer page results.

from __future__ import annotations

import asyncio
import re
import sqlite3
from collections import defaultdict
from contextlib import closing
from typing import TYPE_CHECKING, Literal

from pydantic import Field

from opennoise.models import FrozenModel

if TYPE_CHECKING:
    from pathlib import Path

_MAX_PAGE_SIZE = 50
_OPEN_CATALOG_NODE_PATTERN = re.compile(r"^catalog:(wikidata:genre:Q[1-9][0-9]*)$")


class PublicArtistNavigationStoreError(RuntimeError):
    """Report an unavailable database or unknown catalog identity."""


class DirectMembershipEvidence(FrozenModel):
    """One display-authorized source claim; it is never inferred membership."""

    evidence_id: int = Field(gt=0)
    source_key: str = Field(min_length=1, max_length=200)
    source_record_id: str = Field(min_length=1, max_length=500)
    method_key: str = Field(min_length=1, max_length=200)
    method_version: str = Field(min_length=1, max_length=100)
    provenance_id: int = Field(gt=0)


class PublicArtist(FrozenModel):
    """A named catalog artist with a typed local API identity."""

    entity_id: int = Field(gt=0)
    artist_id: str = Field(pattern=r"^catalog:artist:[1-9][0-9]*$")
    name: str = Field(min_length=1, max_length=500)


class PublicGenre(FrozenModel):
    """A named catalog genre with a typed local API identity."""

    entity_id: int = Field(gt=0)
    genre_id: str = Field(pattern=r"^catalog:genre:[1-9][0-9]*$")
    name: str = Field(min_length=1, max_length=500)


class ArtistGenreMembership(FrozenModel):
    """A direct artist-to-genre claim and the sources that support it."""

    artist: PublicArtist
    genre: PublicGenre
    membership_kind: Literal["direct_source_claim"] = "direct_source_claim"
    evidence: tuple[DirectMembershipEvidence, ...] = Field(min_length=1)


class GenreArtistsResponse(FrozenModel):
    """One bounded page of direct artist claims for a known genre."""

    genre: PublicGenre
    offset: int = Field(ge=0)
    limit: int = Field(ge=1, le=_MAX_PAGE_SIZE)
    members: tuple[ArtistGenreMembership, ...] = Field(max_length=_MAX_PAGE_SIZE)


class ArtistGenresResponse(FrozenModel):
    """One bounded page of direct genre claims for a known artist."""

    artist: PublicArtist
    offset: int = Field(ge=0)
    limit: int = Field(ge=1, le=_MAX_PAGE_SIZE)
    genres: tuple[ArtistGenreMembership, ...] = Field(max_length=_MAX_PAGE_SIZE)


class RelatedArtist(FrozenModel):
    """A transparent related-artist result derived only from shared direct genres."""

    artist: PublicArtist
    method: Literal["shared_direct_genre"] = "shared_direct_genre"
    shared_genres: tuple[PublicGenre, ...] = Field(min_length=1)
    shared_genre_count: int = Field(gt=0)


class RelatedArtistsResponse(FrozenModel):
    """One bounded page of related artists, not a learned-similarity result."""

    artist: PublicArtist
    offset: int = Field(ge=0)
    limit: int = Field(ge=1, le=_MAX_PAGE_SIZE)
    method: Literal["shared_direct_genre"] = "shared_direct_genre"
    related: tuple[RelatedArtist, ...] = Field(max_length=_MAX_PAGE_SIZE)


class DirectPeerGenre(FrozenModel):
    """One persisted direct-profile neighbor from the current public model."""

    genre: PublicGenre
    method: Literal["direct_weighted_jaccard"] = "direct_weighted_jaccard"
    score: float = Field(gt=0.0, le=1.0)
    shared_artist_count: int = Field(gt=0)


class GenreDirectPeersResponse(FrozenModel):
    """Bounded direct artist-overlap peers, separate from taxonomy relations."""

    genre: PublicGenre
    peers: tuple[DirectPeerGenre, ...] = Field(max_length=8)


class PublicArtistNavigationStore:
    """Read the policy-filtered direct-evidence view without using model or H3 data."""

    def __init__(self, path: Path) -> None:
        """Retain the one sealed catalog path used for direct-evidence navigation."""
        self._path = path

    async def genre_artists(
        self, genre_id: int, *, offset: int, limit: int
    ) -> GenreArtistsResponse:
        """Return one direct-membership page for a known genre."""
        return await asyncio.to_thread(self._genre_artists_sync, genre_id, offset, limit)

    async def artist_genres(
        self, artist_id: int, *, offset: int, limit: int
    ) -> ArtistGenresResponse:
        """Return one direct-membership page for a known artist."""
        return await asyncio.to_thread(self._artist_genres_sync, artist_id, offset, limit)

    async def related_artists(
        self, artist_id: int, *, offset: int, limit: int
    ) -> RelatedArtistsResponse:
        """Return related artists sharing direct display-authorized genres."""
        return await asyncio.to_thread(self._related_artists_sync, artist_id, offset, limit)

    async def genre_direct_peers(self, genre_id: int) -> GenreDirectPeersResponse:
        """Read the current model's bounded direct weighted-Jaccard peers only."""
        return await asyncio.to_thread(self._genre_direct_peers_sync, genre_id)

    async def catalog_genre_id_for_open_node(self, node_id: str) -> int | None:
        """Resolve only one exact Open catalog QID to its local catalog identity."""
        match = _OPEN_CATALOG_NODE_PATTERN.fullmatch(node_id)
        if match is None:
            return None
        return await asyncio.to_thread(
            self._catalog_genre_id_for_qid_sync, match.group(1).removeprefix("wikidata:genre:")
        )

    async def open_node_ids_for_catalog_genres(self, genre_ids: tuple[int, ...]) -> dict[int, str]:
        """Return exact Open QID nodes for bounded catalog-genre links only."""
        return await asyncio.to_thread(self._open_node_ids_for_catalog_genres_sync, genre_ids)

    def _genre_artists_sync(self, genre_id: int, offset: int, limit: int) -> GenreArtistsResponse:
        self._validate_page(offset, limit)
        with closing(self._connect()) as connection:
            genre = self._genre(connection, genre_id)
            artist_ids = self._page_ids(
                connection,
                """SELECT DISTINCT evidence.artist_id
                   FROM displayable_artist_genre_evidence AS evidence
                   WHERE evidence.genre_id = ? AND evidence.evidence_kind = 'direct_source_claim'
                   ORDER BY evidence.artist_id LIMIT ? OFFSET ?""",
                (genre_id, limit, offset),
            )
            members = self._memberships(connection, artist_ids, (genre_id,))
        return GenreArtistsResponse(genre=genre, offset=offset, limit=limit, members=members)

    def _artist_genres_sync(self, artist_id: int, offset: int, limit: int) -> ArtistGenresResponse:
        self._validate_page(offset, limit)
        with closing(self._connect()) as connection:
            artist = self._artist(connection, artist_id)
            genre_ids = self._page_ids(
                connection,
                """SELECT DISTINCT evidence.genre_id
                   FROM displayable_artist_genre_evidence AS evidence
                   WHERE evidence.artist_id = ? AND evidence.evidence_kind = 'direct_source_claim'
                   ORDER BY evidence.genre_id LIMIT ? OFFSET ?""",
                (artist_id, limit, offset),
            )
            genres = self._memberships(connection, (artist_id,), genre_ids)
        return ArtistGenresResponse(artist=artist, offset=offset, limit=limit, genres=genres)

    def _related_artists_sync(
        self, artist_id: int, offset: int, limit: int
    ) -> RelatedArtistsResponse:
        self._validate_page(offset, limit)
        with closing(self._connect()) as connection:
            artist = self._artist(connection, artist_id)
            rows = connection.execute(
                """WITH source_genres AS (
                       SELECT DISTINCT genre_id FROM displayable_artist_genre_evidence
                       WHERE artist_id = ? AND evidence_kind = 'direct_source_claim'
                   ), related AS (
                       SELECT evidence.artist_id, count(DISTINCT evidence.genre_id) AS shared_count
                       FROM displayable_artist_genre_evidence AS evidence
                       JOIN source_genres ON source_genres.genre_id = evidence.genre_id
                       WHERE evidence.artist_id != ?
                         AND evidence.evidence_kind = 'direct_source_claim'
                       GROUP BY evidence.artist_id
                   )
                   SELECT artist_id FROM related
                   ORDER BY shared_count DESC, artist_id LIMIT ? OFFSET ?""",
                (artist_id, artist_id, limit, offset),
            ).fetchall()
            related_ids = tuple(int(row[0]) for row in rows)
            if not related_ids:
                return RelatedArtistsResponse(artist=artist, offset=offset, limit=limit, related=())
            placeholders = ",".join("?" for _ in related_ids)
            shared = connection.execute(
                f"""SELECT evidence.artist_id, genre.id, genre.name
                    FROM displayable_artist_genre_evidence AS evidence
                    JOIN genres AS genre ON genre.id = evidence.genre_id
                    WHERE evidence.artist_id IN ({placeholders})
                      AND evidence.evidence_kind = 'direct_source_claim'
                      AND evidence.genre_id IN (
                          SELECT DISTINCT genre_id FROM displayable_artist_genre_evidence
                          WHERE artist_id = ? AND evidence_kind = 'direct_source_claim'
                      )
                    GROUP BY evidence.artist_id, genre.id, genre.name
                    ORDER BY evidence.artist_id, genre.id""",
                (*related_ids, artist_id),
            ).fetchall()
            genres_by_artist: dict[int, list[PublicGenre]] = defaultdict(list)
            for related_id, genre_id, name in shared:
                genres_by_artist[int(related_id)].append(_genre_value(int(genre_id), str(name)))
            related = tuple(
                RelatedArtist(
                    artist=self._artist(connection, related_id),
                    shared_genres=tuple(genres_by_artist[related_id]),
                    shared_genre_count=len(genres_by_artist[related_id]),
                )
                for related_id in related_ids
            )
        return RelatedArtistsResponse(artist=artist, offset=offset, limit=limit, related=related)

    def _catalog_genre_id_for_qid_sync(self, qid: str) -> int | None:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """SELECT genre.id
                   FROM genres AS genre
                   JOIN entity_identifiers AS identifier ON identifier.entity_id = genre.id
                   JOIN identifier_types AS type ON type.id = identifier.identifier_type_id
                   WHERE type.type_key = 'wikidata_genre_qid' AND identifier.normalized_value = ?
                   ORDER BY genre.id LIMIT 2""",
                (qid,),
            ).fetchall()
        return int(rows[0][0]) if len(rows) == 1 else None

    def _genre_direct_peers_sync(self, genre_id: int) -> GenreDirectPeersResponse:
        with closing(self._connect()) as connection:
            genre = self._genre(connection, genre_id)
            rows = connection.execute(
                """SELECT relation.neighbor_genre_id, neighbor.name, relation.score,
                          relation.shared_artist_count
                   FROM displayable_public_genre_neighbors AS relation
                   JOIN genres AS neighbor ON neighbor.id = relation.neighbor_genre_id
                   WHERE relation.genre_id = ?
                     AND relation.profile_kind = 'direct'
                     AND relation.metric = 'weighted_jaccard'
                   ORDER BY relation.rank, neighbor.name COLLATE NOCASE, neighbor.id
                   LIMIT 8""",
                (genre_id,),
            ).fetchall()
        return GenreDirectPeersResponse(
            genre=genre,
            peers=tuple(
                DirectPeerGenre(
                    genre=_genre_value(int(row[0]), str(row[1])),
                    score=float(row[2]),
                    shared_artist_count=int(row[3]),
                )
                for row in rows
            ),
        )

    def _open_node_ids_for_catalog_genres_sync(self, genre_ids: tuple[int, ...]) -> dict[int, str]:
        if not genre_ids:
            return {}
        placeholders = ",".join("?" for _ in genre_ids)
        with closing(self._connect()) as connection:
            rows = connection.execute(
                f"""SELECT genre.id, identifier.normalized_value
                    FROM genres AS genre
                    JOIN entity_identifiers AS identifier ON identifier.entity_id = genre.id
                    JOIN identifier_types AS type ON type.id = identifier.identifier_type_id
                    WHERE genre.id IN ({placeholders})
                      AND type.type_key = 'wikidata_genre_qid'
                      AND identifier.normalized_value GLOB 'Q*'
                    ORDER BY genre.id, identifier.id""",
                genre_ids,
            ).fetchall()
        result: dict[int, str] = {}
        duplicates: set[int] = set()
        for genre_id, external_id in rows:
            parsed = _OPEN_CATALOG_NODE_PATTERN.fullmatch(f"catalog:wikidata:genre:{external_id}")
            if parsed is None:
                continue
            identifier = int(genre_id)
            if identifier in result:
                duplicates.add(identifier)
            else:
                result[identifier] = f"catalog:wikidata:genre:{external_id}"
        for genre_id in duplicates:
            result.pop(genre_id, None)
        return result

    def _memberships(
        self,
        connection: sqlite3.Connection,
        artist_ids: tuple[int, ...],
        genre_ids: tuple[int, ...],
    ) -> tuple[ArtistGenreMembership, ...]:
        if not artist_ids or not genre_ids:
            return ()
        artist_marks = ",".join("?" for _ in artist_ids)
        genre_marks = ",".join("?" for _ in genre_ids)
        rows = connection.execute(
            f"""SELECT evidence.id, evidence.artist_id, evidence.genre_id,
                       evidence.source_key,
                       evidence.source_record_id, evidence.method_key, evidence.method_version,
                       evidence.provenance_id
                FROM displayable_artist_genre_evidence AS evidence
                WHERE evidence.artist_id IN ({artist_marks})
                  AND evidence.genre_id IN ({genre_marks})
                  AND evidence.evidence_kind = 'direct_source_claim'
                ORDER BY evidence.artist_id, evidence.genre_id, evidence.id""",
            (*artist_ids, *genre_ids),
        ).fetchall()
        grouped: dict[tuple[int, int], list[DirectMembershipEvidence]] = defaultdict(list)
        for row in rows:
            grouped[(int(row[1]), int(row[2]))].append(
                DirectMembershipEvidence(
                    evidence_id=int(row[0]),
                    source_key=str(row[3]),
                    source_record_id=str(row[4]),
                    method_key=str(row[5]),
                    method_version=str(row[6]),
                    provenance_id=int(row[7]),
                )
            )
        return tuple(
            ArtistGenreMembership(
                artist=self._artist(connection, artist_id),
                genre=self._genre(connection, genre_id),
                evidence=tuple(evidence),
            )
            for (artist_id, genre_id), evidence in grouped.items()
        )

    def _artist(self, connection: sqlite3.Connection, artist_id: int) -> PublicArtist:
        row = connection.execute(
            """SELECT artist.id, name.name FROM artists AS artist
               JOIN displayable_entity_names AS name ON name.entity_id = artist.id
               WHERE artist.id = ? ORDER BY name.is_preferred DESC, name.id LIMIT 1""",
            (artist_id,),
        ).fetchone()
        if row is None:
            raise PublicArtistNavigationStoreError("artist not found")
        return _artist_value(int(row[0]), str(row[1]))

    def _genre(self, connection: sqlite3.Connection, genre_id: int) -> PublicGenre:
        row = connection.execute("SELECT id, name FROM genres WHERE id = ?", (genre_id,)).fetchone()
        if row is None:
            raise PublicArtistNavigationStoreError("genre not found")
        return _genre_value(int(row[0]), str(row[1]))

    @staticmethod
    def _page_ids(
        connection: sqlite3.Connection, query: str, values: tuple[int, ...]
    ) -> tuple[int, ...]:
        return tuple(int(row[0]) for row in connection.execute(query, values))

    def _connect(self) -> sqlite3.Connection:
        try:
            return sqlite3.connect(f"file:{self._path}?mode=ro", uri=True)
        except sqlite3.Error as error:
            raise PublicArtistNavigationStoreError(
                "public artist navigation database unavailable"
            ) from error

    @staticmethod
    def _validate_page(offset: int, limit: int) -> None:
        if offset < 0 or not 1 <= limit <= _MAX_PAGE_SIZE:
            raise PublicArtistNavigationStoreError("artist navigation pagination is out of bounds")


def _artist_value(entity_id: int, name: str) -> PublicArtist:
    return PublicArtist(entity_id=entity_id, artist_id=f"catalog:artist:{entity_id}", name=name)


def _genre_value(entity_id: int, name: str) -> PublicGenre:
    return PublicGenre(entity_id=entity_id, genre_id=f"catalog:genre:{entity_id}", name=name)
