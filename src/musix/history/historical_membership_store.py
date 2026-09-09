"""Optional, sealed local display access to bounded H3 genre memberships."""

from __future__ import annotations

import asyncio
import hashlib
import sqlite3
from typing import TYPE_CHECKING, Literal

from pydantic import Field

from musix.models import FrozenModel

if TYPE_CHECKING:
    from pathlib import Path

    from musix.models.historical_signal import HistoricalSignalPublicationArtifact

_MAX_MEMBERS_PER_RESPONSE = 50


class HistoricalMembershipStoreError(RuntimeError):
    """Report an unavailable, unsealed, or malformed local membership store."""


class HistoricalSignalMember(FrozenModel):
    """One display-authorized H3 artist reference with no audio fields."""

    source_artist_id: str = Field(min_length=1, max_length=200)
    source_artist_name: str | None = Field(default=None, max_length=500)
    source_local_rank: int | None = Field(default=None, ge=1)
    evidence_ref: str = Field(
        min_length=1, max_length=300, pattern=r"^historical:genre-artist:[1-9][0-9]*$"
    )


class HistoricalSignalMembersApiResponse(FrozenModel):
    """Bounded member slice for one sealed H3 genre selection."""

    source: Literal["historical-signal-membership-database"] = (
        "historical-signal-membership-database"
    )
    genre_id: str = Field(min_length=1, max_length=200)
    offset: int = Field(ge=0)
    limit: int = Field(ge=1, le=_MAX_MEMBERS_PER_RESPONSE)
    members: tuple[HistoricalSignalMember, ...] = Field(max_length=_MAX_MEMBERS_PER_RESPONSE)


class HistoricalMembershipStore:
    """Verify an opt-in local database once, then query the authorized display view only."""

    def __init__(self, path: Path | None) -> None:
        """Retain the optional read-only local database path without implicit fallback."""
        self._path = path
        self._publication: HistoricalSignalPublicationArtifact | None = None
        self._genre_names: dict[str, str] = {}

    @property
    def configured(self) -> bool:
        """Return whether the separate local membership database setting is present."""
        return self._path is not None

    async def start(self, publication: HistoricalSignalPublicationArtifact | None) -> None:
        """Hash and validate the configured database before any endpoint can query it."""
        if not self.configured:
            return
        if publication is None:
            raise HistoricalMembershipStoreError(
                "historical membership database requires a configured historical signal map"
            )
        await asyncio.to_thread(self._validate, publication)

    async def members(
        self, genre_id: str, *, offset: int = 0, limit: int = _MAX_MEMBERS_PER_RESPONSE
    ) -> HistoricalSignalMembersApiResponse:
        """Run the bounded SQLite display query off the event loop."""
        return await asyncio.to_thread(self._members_sync, genre_id, offset=offset, limit=limit)

    def _members_sync(
        self, genre_id: str, *, offset: int, limit: int
    ) -> HistoricalSignalMembersApiResponse:
        """Return a stable bounded H3 membership slice through the sealed display policy."""
        publication = self._publication
        path = self._path
        if publication is None or path is None:
            raise HistoricalMembershipStoreError("historical membership database is unavailable")
        if genre_id not in self._genre_names:
            raise HistoricalMembershipStoreError("historical signal genre does not exist")
        if offset < 0 or not 1 <= limit <= _MAX_MEMBERS_PER_RESPONSE:
            raise HistoricalMembershipStoreError(
                "historical membership pagination is out of bounds"
            )
        query = """
            SELECT observation.id, observation.source_artist_id, observation.source_artist_name,
                   observation.source_local_rank
            FROM displayable_historical_genre_artists AS observation
            JOIN rights_policies AS policy ON policy.id = observation.policy_id
            JOIN genres AS genre ON genre.id = observation.genre_id
            WHERE genre.name = ? COLLATE NOCASE
              AND observation.observation_role = 'genre_page_member'
              AND observation.source_artifact_sha256 = ?
              AND policy.policy_key = ?
            ORDER BY coalesce(observation.source_local_rank, 2147483647),
                     observation.source_artist_name COLLATE NOCASE,
                     observation.source_artist_id
            LIMIT ? OFFSET ?
        """
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as connection:
            rows = connection.execute(
                query,
                (
                    self._genre_names[genre_id],
                    publication.h3_artifact_sha256,
                    publication.h3_policy_key,
                    limit,
                    offset,
                ),
            )
            members = tuple(
                HistoricalSignalMember(
                    source_artist_id=str(artist_id),
                    source_artist_name=str(artist_name) if artist_name is not None else None,
                    source_local_rank=int(rank) if rank is not None else None,
                    evidence_ref=f"historical:genre-artist:{observation_id}",
                )
                for observation_id, artist_id, artist_name, rank in rows
            )
        return HistoricalSignalMembersApiResponse(
            genre_id=genre_id, offset=offset, limit=limit, members=members
        )

    def _validate(self, publication: HistoricalSignalPublicationArtifact) -> None:
        path = self._path
        if path is None:
            raise HistoricalMembershipStoreError("historical membership database is unavailable")
        try:
            database_sha256 = _sha256_path(path)
        except OSError as error:
            raise HistoricalMembershipStoreError(
                "historical membership database cannot be hashed"
            ) from error
        if database_sha256 != publication.h3_database_sha256:
            raise HistoricalMembershipStoreError(
                "historical membership database hash does not match"
            )
        query = """
            SELECT count(*), count(DISTINCT observation.genre_id),
                   count(DISTINCT observation.source_artist_id)
            FROM displayable_historical_genre_artists AS observation
            JOIN rights_policies AS policy ON policy.id = observation.policy_id
            WHERE observation.observation_role = 'genre_page_member'
              AND observation.source_artifact_sha256 = ?
              AND policy.policy_key = ?
        """
        try:
            with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as connection:
                row = connection.execute(
                    query, (publication.h3_artifact_sha256, publication.h3_policy_key)
                ).fetchone()
        except sqlite3.Error as error:
            raise HistoricalMembershipStoreError(
                "historical membership database lacks the sealed display view"
            ) from error
        if row is None:
            raise HistoricalMembershipStoreError("historical membership display validation failed")
        counts = tuple(int(value) for value in row)
        expected = (
            publication.map.inputs.membership_count,
            publication.map.inputs.mapped_membership_genre_count,
            publication.map.inputs.distinct_artist_count,
        )
        if counts != expected:
            raise HistoricalMembershipStoreError(
                "historical membership display rows do not match sealed signal inputs"
            )
        self._publication = publication
        self._genre_names = {node.genre_id: node.name for node in publication.map.nodes}


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1_048_576):
            digest.update(block)
    return digest.hexdigest()
