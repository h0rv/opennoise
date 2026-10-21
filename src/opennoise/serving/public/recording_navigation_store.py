"""Exact native recording credits and artist context; no recording genre inference."""

from __future__ import annotations

import asyncio
import sqlite3
import unicodedata
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
MAX_QUERY_CHARS = 200
MAX_SEARCH_OFFSET = 10_000
MAX_TITLE_OBSERVATIONS = 100_000
MAX_TITLE_CANDIDATES = 10_000
MAX_ARTIST_CREDIT_OBSERVATIONS = 10_000


def normalized_title(value: str) -> str:
    """Normalize literal title text, never source identities or diacritics."""
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


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


class RecordingSearchResponse(FrozenModel):
    """Candidate recordings matched by a jointly authorized literal display title."""

    query: str
    offset: int
    limit: int
    results: tuple[RecordingContextResponse, ...] = ()
    match_scope: Literal["retained_recording_display_title_substring"] = (
        "retained_recording_display_title_substring"
    )


class ArtistRecordingsResponse(FrozenModel):
    """Exact retained primary-credit recordings, never a complete discography."""

    artist_mbid: str
    title_filter: str | None
    offset: int
    limit: int
    results: tuple[RecordingContextResponse, ...] = ()
    scope: Literal["retained_primary_credit_recordings"] = "retained_primary_credit_recordings"


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
            return self._recording_context_connection(
                connection, recording_mbid, genre_limit, related_limit
            )

    def _recording_context_connection(
        self,
        connection: sqlite3.Connection,
        recording_mbid: str,
        genre_limit: int,
        related_limit: int,
    ) -> RecordingContextResponse:
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
            raise PublicArtistNavigationStoreError("recording credit observation bound exceeded")
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

    async def search_recordings(
        self,
        query: str,
        *,
        offset: int = 0,
        limit: int = 10,
        genre_limit: int = 10,
        related_limit: int = 5,
    ) -> RecordingSearchResponse:
        """Return candidates without resolving equal titles into one recording."""
        return await asyncio.to_thread(
            self._search_recordings_sync, query, offset, limit, genre_limit, related_limit
        )

    def _search_recordings_sync(  # noqa: C901 -- One bounded search eligibility/pagination boundary.
        self,
        query: str,
        offset: int = 0,
        limit: int = 10,
        genre_limit: int = 10,
        related_limit: int = 5,
    ) -> RecordingSearchResponse:
        if not isinstance(query, str) or len(query) > MAX_QUERY_CHARS:
            raise ValueError("title query must be a string of at most 200 characters")
        text = normalized_title(query)
        if not any(c.isalnum() for c in text):
            raise ValueError("title query requires meaningful alphanumeric text")
        if type(offset) is not int or not 0 <= offset <= MAX_SEARCH_OFFSET:
            raise ValueError("title offset must be an integer in 0..10000")
        if any(
            type(n) is not int or not 1 <= n <= MAX_CONTEXT
            for n in (limit, genre_limit, related_limit)
        ):
            raise ValueError("title and context limits must be integers in 1..10")
        uri = self.path.as_uri() + "?mode=ro" + ("&immutable=1" if self.immutable else "")
        with closing(sqlite3.connect(uri, uri=True)) as connection:
            connection.row_factory = sqlite3.Row
            connection.execute("BEGIN")
            connection.create_function(
                "recording_title_normalized", 1, normalized_title, deterministic=True
            )
            count = connection.execute("""SELECT count(*) FROM entity_names name
                JOIN recordings recording ON recording.id=name.entity_id""").fetchone()[0]
            if count > MAX_TITLE_OBSERVATIONS:
                raise PublicArtistNavigationStoreError("recording title scan bound exceeded")
            rows = connection.execute(
                """SELECT name.entity_id,name.name,name.provenance_id
                FROM entity_names name JOIN recordings recording ON recording.id=name.entity_id
                WHERE instr(recording_title_normalized(name.name),?)>0
                ORDER BY name.id LIMIT ?""",
                (text, MAX_TITLE_CANDIDATES + 1),
            ).fetchall()
            if len(rows) > MAX_TITLE_CANDIDATES:
                raise PublicArtistNavigationStoreError("recording title candidate bound exceeded")
            display = ExportEligibility(connection, None, use_kind="display")
            search = ExportEligibility(connection, None, use_kind="local_search")
            selected: dict[str, tuple[str, str]] = {}
            identities: dict[int, str | None] = {}
            for row in rows:
                entity_id, title, provenance_id = int(row[0]), str(row[1]), int(row[2])
                if (
                    display.blocked("entity", entity_id)
                    or search.blocked("entity", entity_id)
                    or display.chain(provenance_id) is None
                    or search.chain(provenance_id) is None
                ):
                    continue
                if entity_id not in identities:
                    identities[entity_id] = self._search_identity(
                        connection, display, search, entity_id
                    )
                mbid = identities[entity_id]
                if mbid is not None:
                    candidate = (normalized_title(title), title)
                    if mbid not in selected or candidate < selected[mbid]:
                        selected[mbid] = candidate
            ordered = sorted(selected, key=lambda mbid: (selected[mbid][0], mbid))
            results = tuple(
                self._recording_context_connection(
                    connection, mbid, genre_limit, related_limit
                ).model_copy(update={"title": selected[mbid][1]})
                for mbid in ordered[offset : offset + limit]
            )
            return RecordingSearchResponse(query=query, offset=offset, limit=limit, results=results)

    async def recordings_for_artist(  # noqa: PLR0913 -- Matches bounded recording search API.
        self,
        artist_mbid: str,
        *,
        title_filter: str | None = None,
        offset: int = 0,
        limit: int = 10,
        genre_limit: int = 10,
        related_limit: int = 5,
    ) -> ArtistRecordingsResponse:
        """Browse exact retained credits, optionally narrowed by a literal title."""
        return await asyncio.to_thread(
            self._recordings_for_artist_sync,
            artist_mbid,
            title_filter,
            offset,
            limit,
            genre_limit,
            related_limit,
        )

    def _recordings_for_artist_sync(  # noqa: C901, PLR0912, PLR0913, PLR0915, PLR0917 -- One bounded transaction.
        self,
        artist_mbid: str,
        title_filter: str | None = None,
        offset: int = 0,
        limit: int = 10,
        genre_limit: int = 10,
        related_limit: int = 5,
    ) -> ArtistRecordingsResponse:
        if not isinstance(artist_mbid, str) or str(UUID(artist_mbid)) != artist_mbid:
            raise ValueError("artist MBID must be a canonical lowercase UUID")
        text = None
        if title_filter is not None:
            if not isinstance(title_filter, str) or len(title_filter) > MAX_QUERY_CHARS:
                raise ValueError("title filter must be a string of at most 200 characters")
            text = normalized_title(title_filter)
            if not any(c.isalnum() for c in text):
                raise ValueError("title filter requires meaningful alphanumeric text")
        if type(offset) is not int or not 0 <= offset <= MAX_SEARCH_OFFSET:
            raise ValueError("recording offset must be an integer in 0..10000")
        if any(
            type(n) is not int or not 1 <= n <= MAX_CONTEXT
            for n in (limit, genre_limit, related_limit)
        ):
            raise ValueError("recording and context limits must be integers in 1..10")
        base = ArtistRecordingsResponse(
            artist_mbid=artist_mbid,
            title_filter=title_filter,
            offset=offset,
            limit=limit,
        )
        uri = self.path.as_uri() + "?mode=ro" + ("&immutable=1" if self.immutable else "")
        with closing(sqlite3.connect(uri, uri=True)) as connection:
            connection.row_factory = sqlite3.Row
            connection.execute("BEGIN")
            display = ExportEligibility(connection, None, use_kind="display")
            search = ExportEligibility(connection, None, use_kind="local_search")
            owners = connection.execute(
                """SELECT DISTINCT i.entity_id,e.entity_kind FROM entity_identifiers i
                JOIN identifier_types t ON t.id=i.identifier_type_id
                JOIN catalog_entities e ON e.id=i.entity_id
                WHERE t.type_key='musicbrainz_artist_id' AND i.namespace='musicbrainz'
                AND i.normalized_value=?""",
                (artist_mbid,),
            ).fetchall()
            if not owners:
                return base
            if len(owners) != 1 or owners[0][1] != "artist":
                raise PublicArtistNavigationStoreError("ambiguous exact artist browse identity")
            artist_id = int(owners[0][0])
            if display.blocked("entity", artist_id) or search.blocked("entity", artist_id):
                return base
            # The ordinary typed resolver validates raw ownership/consistency; private
            # observations may veto but cannot supply a searchable identity or name.
            try:
                identity = display.identifier(artist_id, "musicbrainz_artist_id", "musicbrainz")
            except ValueError as error:
                raise PublicArtistNavigationStoreError(str(error)) from error
            if (
                identity is None
                or not self._joint_observation(
                    connection,
                    display,
                    search,
                    artist_id,
                    identity=True,
                )
                or not self._joint_observation(connection, display, search, artist_id)
            ):
                return base
            rows = connection.execute(
                """SELECT DISTINCT l.entity_id,l.artist_credit_id,l.provenance_id,
                c.provenance_id FROM entity_artist_credits l
                JOIN recordings r ON r.id=l.entity_id
                JOIN artist_credits c ON c.id=l.artist_credit_id
                JOIN artist_credit_members m ON m.artist_credit_id=c.id
                WHERE m.artist_id=? AND l.credit_kind='primary'
                ORDER BY l.entity_id,l.artist_credit_id,l.provenance_id LIMIT ?""",
                (artist_id, MAX_ARTIST_CREDIT_OBSERVATIONS + 1),
            ).fetchall()
            if len(rows) > MAX_ARTIST_CREDIT_OBSERVATIONS:
                raise PublicArtistNavigationStoreError("artist credit observation bound exceeded")
            supported: dict[int, set[tuple[int, int, int]]] = {}
            for entity_id, credit_id, link, definition in rows:
                if definition is not None and all(
                    gate.chain(int(prov)) is not None
                    for gate in (display, search)
                    for prov in (link, definition)
                ):
                    supported.setdefault(int(entity_id), set()).add(
                        (int(credit_id), int(link), int(definition))
                    )
            selected: list[tuple[str, str, RecordingContextResponse]] = []
            name_count = 0
            for entity_id, observations in supported.items():
                if display.blocked("entity", entity_id) or search.blocked("entity", entity_id):
                    continue
                mbid = self._search_identity(connection, display, search, entity_id)
                if mbid is None:
                    continue
                names = connection.execute(
                    """SELECT name,provenance_id FROM entity_names
                    WHERE entity_id=? ORDER BY id LIMIT ?""",
                    (entity_id, MAX_TITLE_OBSERVATIONS + 1),
                ).fetchall()
                name_count += len(names)
                if name_count > MAX_TITLE_OBSERVATIONS:
                    raise PublicArtistNavigationStoreError("artist recording title bound exceeded")
                titles = [
                    str(row[0])
                    for row in names
                    if (text is None or text in normalized_title(str(row[0])))
                    and all(gate.chain(int(row[1])) is not None for gate in (display, search))
                ]
                if not titles:
                    continue
                context = self._recording_context_connection(
                    connection, mbid, genre_limit, related_limit
                )
                if context.status != "available" or not any(
                    (
                        credit.artist_credit_id,
                        credit.credit_provenance_id,
                        credit.definition_provenance_id,
                    )
                    in observations
                    and any(
                        member.musicbrainz_artist_id == artist_mbid for member in credit.members
                    )
                    for credit in context.credits
                ):
                    continue
                title = min(titles, key=lambda value: (normalized_title(value), value))
                selected.append(
                    (normalized_title(title), mbid, context.model_copy(update={"title": title}))
                )
            selected.sort(key=lambda row: (row[0], row[1]))
            return base.model_copy(
                update={"results": tuple(row[2] for row in selected[offset : offset + limit])}
            )

    @staticmethod
    def _joint_observation(
        connection: sqlite3.Connection,
        display: ExportEligibility,
        search: ExportEligibility,
        entity_id: int,
        *,
        identity: bool = False,
    ) -> bool:
        if identity:
            rows = connection.execute(
                """SELECT i.provenance_id FROM entity_identifiers i
                JOIN identifier_types t ON t.id=i.identifier_type_id
                WHERE i.entity_id=? AND t.type_key='musicbrainz_artist_id' LIMIT ?""",
                (entity_id, MAX_TITLE_OBSERVATIONS + 1),
            )
        else:
            rows = connection.execute(
                "SELECT provenance_id FROM entity_names WHERE entity_id=? LIMIT ?",
                (entity_id, MAX_TITLE_OBSERVATIONS + 1),
            )
        rows = rows.fetchall()
        if len(rows) > MAX_TITLE_OBSERVATIONS:
            raise PublicArtistNavigationStoreError("artist seed observation bound exceeded")
        return any(
            display.chain(int(row[0])) is not None and search.chain(int(row[0])) is not None
            for row in rows
        )

    def _search_identity(
        self,
        connection: sqlite3.Connection,
        display: ExportEligibility,
        search: ExportEligibility,
        entity_id: int,
    ) -> str | None:
        rows = connection.execute(
            """SELECT i.namespace,i.normalized_value,i.provenance_id
            FROM entity_identifiers i JOIN identifier_types t ON t.id=i.identifier_type_id
            WHERE i.entity_id=? AND t.type_key='musicbrainz_recording_id' ORDER BY i.id""",
            (entity_id,),
        ).fetchall()
        if len({(row[0], row[1]) for row in rows}) > 1:
            raise PublicArtistNavigationStoreError("ambiguous exact recording search identity")
        if not rows:
            return None
        namespace, value = str(rows[0][0]), str(rows[0][1])
        try:
            canonical = namespace == "musicbrainz" and str(UUID(value)) == value
        except ValueError:
            canonical = False
        if not canonical:
            return None
        if self._recording_identity(connection, value) != entity_id:
            raise PublicArtistNavigationStoreError("ambiguous exact recording search identity")
        return (
            value
            if any(
                display.chain(int(r[2])) is not None and search.chain(int(r[2])) is not None
                for r in rows
            )
            else None
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
