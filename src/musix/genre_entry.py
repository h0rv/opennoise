"""Policy-safe reads for the bounded genre entry experience."""

import asyncio
import json
import sqlite3
from pathlib import Path

from musix.db import Database
from musix.exploration import (
    GenreDetail,
    GenreDiscoveryItem,
    GenreExternalLink,
    GenreModelExplanation,
    GenreProfileComponent,
    GenreProfileMember,
    GenreProfileSummary,
    GenreSimilarity,
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
            (
                representative,
                artists,
                albums,
                tracks,
                neighbors,
                explanation,
            ) = await asyncio.to_thread(self._read, detail.entity_id)
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
            model_explanation=explanation,
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
        GenreModelExplanation | None,
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
            neighbor_rows = connection.execute(
                """WITH public_neighbors AS (
                       SELECT relation.neighbor_genre_id AS related_genre_id,
                              name.display_name AS name, relation.rank
                       FROM displayable_public_genre_neighbors AS relation
                       JOIN public_genre_names AS name
                         ON name.model_run_id = relation.model_run_id
                        AND name.genre_id = relation.neighbor_genre_id
                       WHERE relation.genre_id = ?
                         AND relation.profile_kind = 'one_hop'
                         AND relation.metric = 'weighted_jaccard'
                     ), historical_neighbors AS (
                       SELECT relation.related_genre_id,
                              name.name,
                              min(coalesce(relation.source_local_rank, 2147483647)) AS rank
                       FROM displayable_historical_genre_relations AS relation
                       JOIN displayable_entity_names AS name
                         ON name.entity_id = relation.related_genre_id
                       WHERE relation.genre_id = ? AND relation.related_genre_id IS NOT NULL
                       GROUP BY relation.related_genre_id
                   )
                   SELECT related_genre_id, name, rank FROM public_neighbors
                   UNION ALL
                   SELECT historical.related_genre_id, historical.name, historical.rank
                   FROM historical_neighbors AS historical
                   WHERE NOT EXISTS (SELECT 1 FROM public_neighbors)
                   ORDER BY rank, name COLLATE NOCASE, related_genre_id
                   LIMIT ?""",
                (genre_id, genre_id, NEIGHBOR_LIMIT),
            ).fetchall()
            profile_rows = connection.execute(
                """WITH ranked AS (
                       SELECT profile_kind, source_artist_ref, score, evidence_refs_json,
                              components_json,
                              row_number() OVER (
                                PARTITION BY profile_kind
                                ORDER BY score DESC, source_artist_ref
                              ) AS member_rank
                       FROM displayable_public_genre_profile_memberships
                       WHERE genre_id = ?
                     )
                   SELECT profile_kind, source_artist_ref, score, evidence_refs_json,
                          components_json
                   FROM ranked WHERE member_rank <= ?
                   ORDER BY profile_kind, member_rank""",
                (genre_id, NEIGHBOR_LIMIT),
            ).fetchall()
            model_neighbor_rows = connection.execute(
                """WITH ranked AS (
                       SELECT relation.neighbor_genre_id, name.display_name,
                              relation.profile_kind, relation.metric, relation.score,
                              relation.shared_artist_count, relation.rank,
                              row_number() OVER (
                                PARTITION BY relation.profile_kind, relation.metric
                                ORDER BY relation.rank
                              ) AS relation_rank
                       FROM displayable_public_genre_neighbors AS relation
                       JOIN public_genre_names AS name
                         ON name.model_run_id = relation.model_run_id
                        AND name.genre_id = relation.neighbor_genre_id
                       WHERE relation.genre_id = ?
                     )
                   SELECT neighbor_genre_id, display_name, profile_kind, metric, score,
                          shared_artist_count, rank
                   FROM ranked WHERE relation_rank <= ?
                   ORDER BY profile_kind, metric, rank""",
                (genre_id, NEIGHBOR_LIMIT),
            ).fetchall()
        representative = _representative(representative_row)
        artists = _public_items(public_rows, "artist", ARTIST_LIMIT)
        albums = _public_items(public_rows, "release_group", ALBUM_LIMIT)
        tracks = _public_items(public_rows, "recording", TRACK_LIMIT)
        neighbors = tuple(
            GenreDiscoveryItem(
                entity_id=int(row[0]),
                name=str(row[1]),
                href=f"/genres/{int(row[0])}",
            )
            for row in neighbor_rows
        )
        explanation = _model_explanation(profile_rows, model_neighbor_rows)
        return representative, artists, albums, tracks, neighbors, explanation


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


def _model_explanation(
    profile_rows: list[sqlite3.Row],
    neighbor_rows: list[sqlite3.Row],
) -> GenreModelExplanation | None:
    """Parse bounded persisted model evidence at the SQLite-to-domain boundary."""
    members_by_kind: dict[str, list[GenreProfileMember]] = {}
    for row in profile_rows:
        raw_components = json.loads(str(row[4]))
        if not isinstance(raw_components, list):
            raise TypeError("stored profile components must be a JSON array")
        components = tuple(
            GenreProfileComponent.model_validate(
                {
                    **component,
                    "evidence_refs": _json_string_tuple(component.get("evidence_refs")),
                }
            )
            for component in raw_components
            if isinstance(component, dict)
        )
        if len(components) != len(raw_components):
            raise TypeError("stored profile component must be a JSON object")
        members_by_kind.setdefault(str(row[0]), []).append(
            GenreProfileMember(
                artist_ref=str(row[1]),
                score=float(row[2]),
                evidence_refs=_json_string_tuple(json.loads(str(row[3]))),
                components=components,
            )
        )
    profiles = tuple(
        GenreProfileSummary.model_validate({"profile_kind": kind, "members": tuple(members)})
        for kind, members in sorted(members_by_kind.items())
    )
    neighbors = tuple(
        GenreSimilarity.model_validate(
            {
                "genre_id": int(row[0]),
                "name": str(row[1]),
                "profile_kind": str(row[2]),
                "metric": str(row[3]),
                "score": float(row[4]),
                "shared_artist_count": int(row[5]),
                "rank": int(row[6]),
            }
        )
        for row in neighbor_rows
    )
    if not profiles and not neighbors:
        return None
    return GenreModelExplanation(profiles=profiles, neighbors=neighbors)


def _json_string_tuple(value: object) -> tuple[str, ...]:
    """Parse one stored JSON string array without letting an untyped list escape."""
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise TypeError("stored evidence references must be a JSON string array")
    return tuple(item for item in value if isinstance(item, str))


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
