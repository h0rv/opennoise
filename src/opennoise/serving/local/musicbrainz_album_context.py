"""Compose bounded local album, artist, and playlist evidence by exact identities."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from typing import TYPE_CHECKING, Literal
from uuid import UUID

from pydantic import Field

from opennoise.analysis.playlist_album_evidence_join import (
    PlaylistAlbumEvidenceContext,
    PlaylistAlbumEvidenceJoinReport,
    report_sha256,
)
from opennoise.models import FrozenModel
from opennoise.serving.local.musicbrainz_album_discovery import (
    AlbumDiscoveryResult,
    query_album_examples,
)
from opennoise.serving.local.musicbrainz_artist_evidence import (
    AlbumSupportedSeedClaim,  # noqa: TC001 -- Runtime Pydantic field.
    LocalResearchSeed,  # noqa: TC001 -- Runtime Pydantic field.
)
from opennoise.taxonomy.seeds.universe import normalize_label

if TYPE_CHECKING:
    from pathlib import Path

    from opennoise.ingest.musicbrainz.release_group_album_examples import (
        ReleaseGroupAlbumExamplesReport,
    )
    from opennoise.serving.local.musicbrainz_artist_evidence import (
        LocalMusicBrainzArtistEvidenceStore,
    )

_MAX_ALBUMS = 25
_MAX_ARTISTS = 100
_MAX_DIRECT_OBSERVATIONS = 1000


class AlbumContextError(ValueError):
    """Inputs cannot support an exact, bounded local context query."""


class DirectArtistSeedObservation(FrozenModel):
    """An exact artist-record facet and reference, independent of album credits."""

    seed_id: str
    facet: Literal["musicbrainz_genre", "musicbrainz_tag"]
    evidence_reference: str


class CreditedArtistContext(FrozenModel):
    """Separate direct artist observations from release-group support."""

    artist_mbid: str
    role: Literal["release_group_artist_credit_context"] = "release_group_artist_credit_context"
    direct_artist_seeds: tuple[LocalResearchSeed, ...]
    direct_artist_observations: tuple[DirectArtistSeedObservation, ...]
    album_supported_seeds: tuple[AlbumSupportedSeedClaim, ...]
    remaining_direct_seed_count: int = Field(ge=0)
    remaining_album_supported_seed_count: int = Field(ge=0)


class AlbumContextResult(FrozenModel):
    """One native album observation and its independent exact-identity contexts."""

    album: AlbumDiscoveryResult
    credited_artist_contexts: tuple[CreditedArtistContext, ...]
    playlist_status: Literal["unavailable", "no_exact_matches", "matched"]
    playlist_contexts: tuple[PlaylistAlbumEvidenceContext, ...]


class AlbumContextResponse(FrozenModel):
    """A deterministic research response, never an inferred membership model."""

    revision: Literal["musicbrainz-album-context-query-v1"] = "musicbrainz-album-context-query-v1"
    local_only: Literal[True] = True
    export_allowed: Literal[False] = False
    serving_allowed: Literal[False] = False
    model_input_allowed: Literal[False] = False
    artist_membership_inferred_from_context: Literal[False] = False
    matched_by: Literal["genre_name", "artist_mbid"]
    query: str
    result_count: int = Field(ge=0)
    album_report_sha256: str
    artist_evidence_sha256: str
    playlist_report_sha256: str | None
    total_album_count: int = Field(ge=0)
    remaining_album_count: int = Field(ge=0)
    results: tuple[AlbumContextResult, ...]


def load_playlist_context_report(path: Path) -> PlaylistAlbumEvidenceJoinReport:
    """Read and structurally replay an optional local playlist join receipt."""
    return verify_playlist_context_report(
        PlaylistAlbumEvidenceJoinReport.model_validate_json(path.read_bytes())
    )


def verify_playlist_context_report(
    report: PlaylistAlbumEvidenceJoinReport,
) -> PlaylistAlbumEvidenceJoinReport:
    """Reject changed receipts, duplicate contexts, and misattributed direct evidence."""
    report = PlaylistAlbumEvidenceJoinReport.model_validate_json(report.model_dump_json())
    if report_sha256(report) != report.output_sha256:
        raise AlbumContextError("playlist context report hash does not replay")
    ids = tuple(context.release_group_mbid for context in report.contexts)
    if len(set(ids)) != report.requested_release_group_count:
        raise AlbumContextError("playlist context release-group counts or identities differ")
    serialized_contexts = tuple(context.model_dump_json() for context in report.contexts)
    if len(serialized_contexts) != len(set(serialized_contexts)):
        raise AlbumContextError("playlist report repeats an identical recording context")
    for context in report.contexts:
        native_hash = context.native_release_group_evidence[0].record_content_sha256
        if any(credit.record_content_sha256 != native_hash for credit in context.credited_artists):
            raise AlbumContextError("playlist artist credit record hash differs from native record")
        artists = {credit.artist_mbid for credit in context.credited_artists}
        positions = tuple(credit.credit_position for credit in context.credited_artists)
        if len(positions) != len(set(positions)):
            raise AlbumContextError("playlist context repeats an artist credit position")
        if any(
            row.artist_mbid not in artists for row in context.direct_anchor_artist_seed_evidence
        ):
            raise AlbumContextError(
                "playlist direct evidence is not attributed to a credited artist"
            )
    proper = len(
        {
            context.release_group_mbid
            for context in report.contexts
            if context.native_proper_genre_status == "present"
        }
    )
    credited = len(
        {context.release_group_mbid for context in report.contexts if context.credited_artists}
    )
    direct = len(
        {
            row.artist_mbid
            for context in report.contexts
            for row in context.direct_anchor_artist_seed_evidence
        }
    )
    if (proper, credited, direct) != (
        report.release_groups_with_native_proper_genres,
        report.release_groups_with_credited_artist_evidence,
        report.credited_artists_with_direct_evidence,
    ):
        raise AlbumContextError("playlist context aggregate counts do not replay")
    return report


def query_album_context(  # noqa: PLR0913, C901, PLR0912 -- Explicit source checks precede joins.
    report: ReleaseGroupAlbumExamplesReport,
    artist_store: LocalMusicBrainzArtistEvidenceStore,
    *,
    genre_name: str | None = None,
    artist_mbid: str | None = None,
    playlist_report: PlaylistAlbumEvidenceJoinReport | None = None,
    limit: int = 10,
) -> AlbumContextResponse:
    """Join verified native albums, artist observations, and optional playlists."""
    if not artist_store.configured:
        raise AlbumContextError("artist evidence store must be startup-certified")
    if type(limit) is not int or not 1 <= limit <= _MAX_ALBUMS:
        raise AlbumContextError("album limit must be between 1 and 25")
    if artist_mbid is not None and str(UUID(artist_mbid)) != artist_mbid:
        raise AlbumContextError("artist query requires a canonical UUID")
    source = artist_store.sources.evidence_artifact
    if (report.source_archive_sha256, report.source_archive_bytes) != (
        source.source_archive_sha256,
        source.source_archive_bytes,
    ):
        raise AlbumContextError("album and artist evidence archives differ")
    albums = query_album_examples(report, genre_name=genre_name, artist_mbid=artist_mbid)
    selected = albums.results[:limit]
    seeds = {row.source_item_id: row for row in artist_store.sources.reconciliation.dispositions}
    for album in selected:
        seed = seeds.get(album.seed_source_item_id)
        if seed is None or normalize_label(seed.seed_name) != album.normalized_seed_name:
            raise AlbumContextError("album seed does not match artist reconciliation")
    if playlist_report is not None:
        playlist_report = verify_playlist_context_report(playlist_report)
        if (
            playlist_report.release_group_evidence_artifact_sha256 != source.output_sha256
            or playlist_report.release_group_evidence_database_sha256
            != source.evidence_database_sha256
            or playlist_report.artist_credit_archive_sha256 != report.source_archive_sha256
            or playlist_report.artist_credit_archive_bytes != report.source_archive_bytes
        ):
            raise AlbumContextError("playlist and album artist evidence source bindings differ")
    artist_ids = tuple(
        dict.fromkeys(credit.artist_mbid for album in selected for credit in album.credited_artists)
    )
    if len(artist_ids) > _MAX_ARTISTS:
        raise AlbumContextError("selected album credits exceed the 100-artist query bound")
    contexts: dict[str, CreditedArtistContext] = {}
    for identifier in artist_ids:
        evidence = artist_store.seeds_for_artist(identifier, limit=_MAX_ARTISTS)
        contexts[identifier] = CreditedArtistContext(
            artist_mbid=identifier,
            direct_artist_seeds=evidence.seeds,
            direct_artist_observations=_direct_observations(artist_store, identifier),
            album_supported_seeds=evidence.album_supported_seeds,
            remaining_direct_seed_count=evidence.remaining_direct_seed_count,
            remaining_album_supported_seed_count=evidence.remaining_album_supported_seed_count,
        )
    results = []
    for album in selected:
        playlist = (
            tuple(
                context
                for context in playlist_report.contexts
                if context.release_group_mbid == album.release_group_mbid
            )
            if playlist_report is not None
            else ()
        )
        for context in playlist:
            for direct in context.direct_anchor_artist_seed_evidence:
                artist_context = contexts.get(direct.artist_mbid)
                if artist_context is None:
                    raise AlbumContextError("playlist direct artist is outside exact album credits")
                observed = artist_context.direct_artist_observations
                for facet in direct.facets:
                    if not any(
                        row.seed_id == direct.seed_id and row.facet == facet for row in observed
                    ):
                        raise AlbumContextError(
                            "playlist direct facet differs from certified artist evidence"
                        )
                available_refs = {
                    row.evidence_reference for row in observed if row.seed_id == direct.seed_id
                }
                if not set(direct.evidence_references).issubset(available_refs):
                    raise AlbumContextError(
                        "playlist direct references differ from certified artist evidence"
                    )
            native = context.native_release_group_evidence[0]
            if not any(
                str(genre.genre_mbid) == album.genre_mbid
                and genre.name == album.genre_name
                and genre.vote_count == album.genre_vote_count
                for genre in native.proper_genres
            ):
                raise AlbumContextError("album genre differs from native playlist evidence")
            if native.record_content_sha256 != album.record_content_sha256:
                raise AlbumContextError("same release group has conflicting native record hashes")
            if tuple(
                credit.artist_mbid
                for credit in sorted(
                    context.credited_artists, key=lambda credit: credit.credit_position
                )
            ) != tuple(credit.artist_mbid for credit in album.credited_artists):
                raise AlbumContextError("same release group has conflicting artist credits")
        results.append(
            AlbumContextResult(
                album=album,
                credited_artist_contexts=tuple(
                    contexts[credit.artist_mbid] for credit in album.credited_artists
                ),
                playlist_status=(
                    "unavailable"
                    if playlist_report is None
                    else "matched"
                    if playlist
                    else "no_exact_matches"
                ),
                playlist_contexts=playlist,
            )
        )
    return AlbumContextResponse(
        matched_by="genre_name" if genre_name is not None else "artist_mbid",
        query=genre_name if genre_name is not None else str(artist_mbid),
        result_count=len(results),
        album_report_sha256=report.output_sha256,
        artist_evidence_sha256=source.output_sha256,
        playlist_report_sha256=playlist_report.output_sha256
        if playlist_report is not None
        else None,
        total_album_count=albums.result_count,
        remaining_album_count=albums.result_count - len(results),
        results=tuple(results),
    )


def response_json(response: AlbumContextResponse) -> str:
    """Serialize without nondeterministic query timings."""
    return json.dumps(
        response.model_dump(mode="json"),
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _direct_observations(
    store: LocalMusicBrainzArtistEvidenceStore, artist_mbid: str
) -> tuple[DirectArtistSeedObservation, ...]:
    """Read only exact artist anchor rows from the startup-certified immutable source."""
    try:
        with closing(
            sqlite3.connect(store.sources.database.resolve().as_uri() + "?mode=ro", uri=True)
        ) as connection:
            rows = connection.execute(
                "SELECT genre_id, facet, evidence_ref FROM direct_anchor "
                "WHERE artist_id = ? ORDER BY genre_id, facet, evidence_ref LIMIT 1001",
                (artist_mbid,),
            ).fetchall()
    except sqlite3.Error as error:
        raise AlbumContextError("certified artist observations cannot be queried") from error
    if len(rows) > _MAX_DIRECT_OBSERVATIONS:
        raise AlbumContextError("exact artist evidence exceeds the 1000-observation bound")
    return tuple(
        DirectArtistSeedObservation(seed_id=seed, facet=facet, evidence_reference=reference)
        for seed, facet, reference in rows
    )
