"""Exact native recording credits and artist context; no recording genre inference."""

from __future__ import annotations

import asyncio
import sqlite3
from contextlib import closing
from typing import TYPE_CHECKING, Literal
from uuid import UUID

from pydantic import Field

from opennoise.models import FrozenModel
from opennoise.serving.public.artist_navigation_store import (
    ArtistGenresResponse,
    PublicArtist,
    PublicArtistNavigationStore,
    PublicArtistNavigationStoreError,
    RelatedArtistsResponse,
)
from opennoise.serving.public.membership_export_eligibility import ExportEligibility

if TYPE_CHECKING:
    from pathlib import Path

# Same-store connection helpers intentionally share a single read transaction.
# ruff: noqa: SLF001

MAX_CREDITS = 64
MAX_MEMBERS = 32
MAX_CONTEXT = 10


class RecordingCreditMember(FrozenModel):
    """One exact ordered credit member, with separate artist-source context."""

    position: int = Field(ge=0)
    credited_name: str
    join_phrase: str
    musicbrainz_artist_id: str
    artist_genres: ArtistGenresResponse
    related_artists: RelatedArtistsResponse


class RecordingCreditContext(FrozenModel):
    """One intact primary-credit observation and its independently authorized definition."""

    artist_credit_id: int = Field(gt=0)
    credit_provenance_id: int = Field(gt=0)
    definition_provenance_id: int = Field(gt=0)
    credit_source_key: str
    definition_source_key: str
    members: tuple[RecordingCreditMember, ...]


class RecordingContextResponse(FrozenModel):
    """A bounded recording entry point, never recording genre membership or relevance."""

    recording_mbid: str
    status: Literal["available", "recording_unavailable", "credit_unavailable", "credit_conflict"]
    recording_entity_id: int | None = None
    title: str | None = None
    credits: tuple[RecordingCreditContext, ...] = ()
    context_scope: Literal["credited_artists_own_direct_source_context"] = (
        "credited_artists_own_direct_source_context"
    )
    genre_limit: int
    related_limit: int


class PublicRecordingNavigationStore:
    """Read registered CC0 native credit observations through existing display eligibility."""

    def __init__(self, path: Path, *, immutable: bool = False) -> None:
        """Use the existing artist store and its unchanged context queries."""
        if type(immutable) is not bool:
            raise ValueError("immutable must be a boolean")
        self.immutable = immutable
        self.path = path.resolve()
        self.artists = PublicArtistNavigationStore(path)

    async def recording_context(
        self, recording_mbid: str, *, genre_limit: int = 10, related_limit: int = 5
    ) -> RecordingContextResponse:
        """Read one exact recording and independently bounded context per credited artist."""
        return await asyncio.to_thread(
            self._recording_context_sync, recording_mbid, genre_limit, related_limit
        )

    def _recording_context_sync(
        self, recording_mbid: str, genre_limit: int = 10, related_limit: int = 5
    ) -> RecordingContextResponse:
        if not isinstance(recording_mbid, str) or str(UUID(recording_mbid)) != recording_mbid:
            raise ValueError("recording MBID must be a canonical lowercase UUID")
        if any(
            type(n) is not int or not 1 <= n <= MAX_CONTEXT for n in (genre_limit, related_limit)
        ):
            raise ValueError("context limits must be integers in 1..10")
        uri = self.path.as_uri() + "?mode=ro" + ("&immutable=1" if self.immutable else "")
        with closing(sqlite3.connect(uri, uri=True)) as connection:
            connection.row_factory = sqlite3.Row
            connection.execute("BEGIN")
            eligibility = ExportEligibility(connection, None, use_kind="display")
            entity_id = self._recording_identity(connection, recording_mbid)
            base = RecordingContextResponse(
                recording_mbid=recording_mbid,
                genre_limit=genre_limit,
                related_limit=related_limit,
                status="recording_unavailable",
            )
            if entity_id is None:
                return base
            if eligibility.blocked("entity", entity_id):
                return base.model_copy(update={"status": "recording_unavailable"})
            identity_rows = connection.execute(
                """SELECT i.provenance_id FROM entity_identifiers i
                   JOIN identifier_types t ON t.id=i.identifier_type_id
                   WHERE i.entity_id=? AND t.type_key='musicbrainz_recording_id'
                   AND i.namespace='musicbrainz' AND i.normalized_value=?""",
                (entity_id, recording_mbid),
            ).fetchall()
            name = eligibility.name(entity_id)
            if not any(eligibility.chain(int(r[0])) for r in identity_rows) or name is None:
                return base.model_copy(update={"status": "recording_unavailable"})
            base = base.model_copy(update={"title": name[0], "recording_entity_id": entity_id})
            # Duration is optional source metadata, not a condition for exposing credits.
            # No separately sourced duration observation is certified by this entry point.
            rows = connection.execute(
                """SELECT l.artist_credit_id,l.provenance_id,c.provenance_id
                   FROM entity_artist_credits l JOIN artist_credits c ON c.id=l.artist_credit_id
                   WHERE l.entity_id=? AND l.credit_kind='primary'
                   ORDER BY l.artist_credit_id,l.provenance_id LIMIT ?""",
                (entity_id, MAX_CREDITS + 1),
            ).fetchall()
            if len(rows) > MAX_CREDITS:
                raise PublicArtistNavigationStoreError(
                    "recording credit observation bound exceeded"
                )
            observations = []
            contexts: dict[int, tuple[ArtistGenresResponse, RelatedArtistsResponse]] = {}
            for credit_id, provenance_id, definition_id in rows:
                credit = self._credit(
                    connection,
                    eligibility,
                    int(credit_id),
                    int(provenance_id),
                    definition_id,
                    genre_limit,
                    related_limit,
                    contexts,
                )
                if credit is not None:
                    observations.append(credit)
            signatures = {
                tuple(
                    (m.position, m.musicbrainz_artist_id, m.credited_name, m.join_phrase)
                    for m in observation.members
                )
                for observation in observations
            }
            if len(signatures) > 1:
                return base.model_copy(update={"status": "credit_conflict"})
            return base.model_copy(
                update={
                    "status": "available" if observations else "credit_unavailable",
                    "credits": tuple(observations),
                }
            )

    @staticmethod
    def _recording_identity(connection: sqlite3.Connection, mbid: str) -> int | None:
        rows = connection.execute(
            """SELECT DISTINCT i.entity_id,e.entity_kind FROM entity_identifiers i
               JOIN identifier_types t ON t.id=i.identifier_type_id
               JOIN catalog_entities e ON e.id=i.entity_id
               WHERE t.type_key='musicbrainz_recording_id' AND i.namespace='musicbrainz'
                 AND i.normalized_value=?""",
            (mbid,),
        ).fetchall()
        if not rows:
            return None
        if len(rows) != 1 or rows[0][1] != "recording":
            raise PublicArtistNavigationStoreError(
                "ambiguous or wrong-kind exact recording identity"
            )
        entity_id = int(rows[0][0])
        aliases = connection.execute(
            """SELECT i.namespace,i.normalized_value,i.value,t.type_key FROM entity_identifiers i
               JOIN identifier_types t ON t.id=i.identifier_type_id
               WHERE i.entity_id=? AND t.type_key GLOB 'musicbrainz_*_id'""",
            (entity_id,),
        ).fetchall()
        if any(
            tuple(row) != ("musicbrainz", mbid, mbid, "musicbrainz_recording_id") for row in aliases
        ):
            raise PublicArtistNavigationStoreError("conflicting exact recording identities")
        return entity_id

    def _credit(  # noqa: PLR0913, PLR0917 -- Intact credit and shared request context.
        self,
        connection: sqlite3.Connection,
        eligibility: ExportEligibility,
        credit_id: int,
        provenance_id: int,
        definition_id: int | None,
        genre_limit: int,
        related_limit: int,
        contexts: dict[int, tuple[ArtistGenresResponse, RelatedArtistsResponse]],
    ) -> RecordingCreditContext | None:
        link = eligibility.chain(provenance_id)
        definition = eligibility.chain(definition_id) if definition_id is not None else None
        if link is None or definition is None or definition_id is None:
            return None
        rows = connection.execute(
            """SELECT position,artist_id,credited_name,join_phrase FROM artist_credit_members
               WHERE artist_credit_id=? ORDER BY position LIMIT ?""",
            (credit_id, MAX_MEMBERS + 1),
        ).fetchall()
        if not rows or len(rows) > MAX_MEMBERS or [r[0] for r in rows] != list(range(len(rows))):
            raise PublicArtistNavigationStoreError("invalid or oversized ordered credit definition")
        members = []
        for position, artist_id, credited_name, join_phrase in rows:
            identity = eligibility.identifier(artist_id, "musicbrainz_artist_id", "musicbrainz")
            name = eligibility.name(artist_id)
            if identity is None or name is None:
                return None
            if artist_id not in contexts:
                contexts[artist_id] = (
                    self.artists._artist_genres_connection(connection, artist_id, 0, genre_limit),
                    self.artists._related_artists_connection(
                        connection, artist_id, 0, related_limit
                    ),
                )
            genres, related = contexts[artist_id]
            actor = PublicArtist(
                entity_id=artist_id, artist_id=f"catalog:artist:{artist_id}", name=name[0]
            )
            genres = genres.model_copy(update={"artist": actor})
            related = related.model_copy(update={"artist": actor})
            members.append(
                RecordingCreditMember(
                    position=position,
                    credited_name=credited_name,
                    join_phrase=join_phrase,
                    musicbrainz_artist_id=identity[0],
                    artist_genres=genres,
                    related_artists=related,
                )
            )
        return RecordingCreditContext(
            artist_credit_id=credit_id,
            credit_provenance_id=provenance_id,
            definition_provenance_id=definition_id,
            credit_source_key=str(link["source_key"]),
            definition_source_key=str(definition["source_key"]),
            members=tuple(members),
        )
