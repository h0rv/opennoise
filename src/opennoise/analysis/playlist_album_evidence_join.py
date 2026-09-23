"""Join local playlist and MusicBrainz evidence without deriving membership claims."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections import defaultdict
from contextlib import closing
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from opennoise.analysis.listenbrainz_playlist_release_group_overlap import (
    NativeReleaseGroupEvidence,  # noqa: TC001
    PlaylistRecordingOccurrence,  # noqa: TC001
    PlaylistReleaseGroupOverlap,  # noqa: TC001
)
from opennoise.ingest.musicbrainz.release_group_evidence import (
    ReleaseGroupEvidenceArtifact,  # noqa: TC001
)
from opennoise.models.pipeline import SourceLimits
from opennoise.sources.musicbrainz import MusicBrainzReleaseGroup, _iter_raw_archive

if TYPE_CHECKING:
    from pathlib import Path

_MAX_RELEASE_GROUPS = 100
type EvidenceFacet = Literal["musicbrainz_genre", "musicbrainz_tag"]


class PlaylistAlbumEvidenceJoinError(ValueError):
    """The local evidence inputs cannot support an exact identity join."""


class _FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")


class DirectArtistGenreEvidence(_FrozenModel):
    """A local direct-anchor observation, with its genre and tag facets retained."""

    role: Literal["musicbrainz_direct_anchor_artist_seed"] = "musicbrainz_direct_anchor_artist_seed"
    artist_mbid: str = Field(pattern=r"^[0-9a-f-]{36}$")
    seed_id: str = Field(min_length=1)
    facets: tuple[EvidenceFacet, ...] = Field(min_length=1)
    evidence_references: tuple[str, ...] = Field(min_length=1)


class ReleaseGroupCreditedArtistEvidence(_FrozenModel):
    """One ordered artist credit from the exact MusicBrainz release-group record."""

    role: Literal["musicbrainz_release_group_artist_credit"] = (
        "musicbrainz_release_group_artist_credit"
    )
    artist_mbid: str = Field(pattern=r"^[0-9a-f-]{36}$")
    artist_name: str = Field(min_length=1)
    credited_name: str = Field(min_length=1)
    joinphrase: str
    credit_position: int = Field(ge=0)
    record_content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class PlaylistAlbumEvidenceContext(_FrozenModel):
    """One exact release-group context with independent source roles kept separate."""

    release_group_mbid: str = Field(pattern=r"^[0-9a-f-]{36}$")
    playlist_role: Literal["listenbrainz_playlist_track"] = "listenbrainz_playlist_track"
    playlist_occurrences: tuple[PlaylistRecordingOccurrence, ...] = Field(min_length=1)
    native_release_group_role: Literal["native_release_group_proper_genre"] = (
        "native_release_group_proper_genre"
    )
    native_release_group_evidence: tuple[NativeReleaseGroupEvidence, ...] = Field(
        min_length=1, max_length=1
    )
    native_proper_genre_status: Literal["present", "no_native_proper_genre"]
    credited_artists: tuple[ReleaseGroupCreditedArtistEvidence, ...]
    direct_anchor_artist_seed_evidence: tuple[DirectArtistGenreEvidence, ...]
    artist_membership_asserted: Literal[False] = False
    genre_membership_inferred_from_context: Literal[False] = False

    @model_validator(mode="after")
    def exact_release_group_identity_is_preserved(self) -> PlaylistAlbumEvidenceContext:
        """Require a single matching, positive native proper-genre observation."""
        if str(self.native_release_group_evidence[0].release_group_mbid) != self.release_group_mbid:
            raise ValueError("native release-group evidence does not match the context ID")
        has_proper_genres = bool(self.native_release_group_evidence[0].proper_genres)
        if has_proper_genres != (self.native_proper_genre_status == "present"):
            raise ValueError("native proper-genre status does not match the retained observation")
        return self


class PlaylistAlbumEvidenceJoinReport(_FrozenModel):
    """A bounded local-only report with no derived artist-to-genre membership."""

    revision: Literal["playlist-album-evidence-join-v2"] = "playlist-album-evidence-join-v2"
    local_only: Literal[True] = True
    export_allowed: Literal[False] = False
    serving_allowed: Literal[False] = False
    model_input_allowed: Literal[False] = False
    artist_membership_asserted: Literal[False] = False
    genre_membership_inferred_from_playlist: Literal[False] = False
    genre_membership_inferred_from_album_context: Literal[False] = False
    playlist_overlap_report_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    release_group_evidence_artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    release_group_evidence_database_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    artist_credit_archive_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    artist_credit_archive_bytes: int = Field(gt=0)
    requested_release_group_count: int = Field(ge=0, le=_MAX_RELEASE_GROUPS)
    release_groups_with_native_proper_genres: int = Field(ge=0)
    release_groups_with_credited_artist_evidence: int = Field(ge=0)
    credited_artists_with_direct_evidence: int = Field(ge=0)
    contexts: tuple[PlaylistAlbumEvidenceContext, ...]
    output_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


def report_sha256(report: PlaylistAlbumEvidenceJoinReport) -> str:
    """Return the deterministic logical hash excluding the self-reference."""
    payload = json.dumps(
        report.model_dump(mode="json", exclude={"output_sha256"}),
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def join_playlist_album_evidence(  # noqa: PLR0913
    overlaps: tuple[PlaylistReleaseGroupOverlap, ...],
    *,
    playlist_overlap_report_sha256: str,
    evidence_database: Path,
    evidence_artifact: ReleaseGroupEvidenceArtifact,
    artist_credits: dict[str, tuple[ReleaseGroupCreditedArtistEvidence, ...]],
    artist_credit_archive_sha256: str,
    artist_credit_archive_bytes: int,
) -> PlaylistAlbumEvidenceJoinReport:
    """Connect exact IDs in local artifacts while keeping each source role separate."""
    release_group_ids = tuple(sorted({str(item.identity.release_group_mbid) for item in overlaps}))
    if len(release_group_ids) > _MAX_RELEASE_GROUPS:
        raise PlaylistAlbumEvidenceJoinError("release-group query exceeds the local bound")
    if not release_group_ids:
        return _report(
            (),
            playlist_overlap_report_sha256,
            evidence_artifact,
            artist_credit_archive_sha256,
            artist_credit_archive_bytes,
            0,
            0,
            0,
            0,
        )
    _require_artifact_database_binding(evidence_database, evidence_artifact)
    direct = _read_direct_evidence(evidence_database, artist_credits, release_group_ids)
    contexts = tuple(
        _context_for_overlap(overlap, artist_credits, direct)
        for overlap in sorted(overlaps, key=lambda item: str(item.identity.release_group_mbid))
    )
    return _report(
        contexts,
        playlist_overlap_report_sha256,
        evidence_artifact,
        artist_credit_archive_sha256,
        artist_credit_archive_bytes,
        len(release_group_ids),
        len(
            {
                str(item.identity.release_group_mbid)
                for item in overlaps
                if item.native_evidence.proper_genres
            }
        ),
        sum(bool(artist_credits.get(item)) for item in release_group_ids),
        len(
            {
                artist.artist_mbid
                for artists in artist_credits.values()
                for artist in artists
                if direct.get(artist.artist_mbid)
            }
        ),
    )


def _report(  # noqa: PLR0913, PLR0917  # The report binds its four explicit source counts.
    contexts: tuple[PlaylistAlbumEvidenceContext, ...],
    playlist_overlap_report_sha256: str,
    artifact: ReleaseGroupEvidenceArtifact,
    artist_credit_archive_sha256: str,
    artist_credit_archive_bytes: int,
    requested_release_group_count: int,
    release_groups_with_native_proper_genres: int,
    release_groups_with_credited_artist_evidence: int,
    credited_artists_with_direct_evidence: int,
) -> PlaylistAlbumEvidenceJoinReport:
    preliminary = PlaylistAlbumEvidenceJoinReport(
        playlist_overlap_report_sha256=playlist_overlap_report_sha256,
        release_group_evidence_artifact_sha256=artifact.output_sha256,
        release_group_evidence_database_sha256=artifact.evidence_database_sha256,
        artist_credit_archive_sha256=artist_credit_archive_sha256,
        artist_credit_archive_bytes=artist_credit_archive_bytes,
        requested_release_group_count=requested_release_group_count,
        release_groups_with_native_proper_genres=release_groups_with_native_proper_genres,
        release_groups_with_credited_artist_evidence=release_groups_with_credited_artist_evidence,
        credited_artists_with_direct_evidence=credited_artists_with_direct_evidence,
        contexts=contexts,
        output_sha256="0" * 64,
    )
    return preliminary.model_copy(update={"output_sha256": report_sha256(preliminary)})


def _require_artifact_database_binding(
    database: Path, artifact: ReleaseGroupEvidenceArtifact
) -> None:
    digest = hashlib.sha256()
    size = 0
    with database.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
    if (
        digest.hexdigest() != artifact.evidence_database_sha256
        or size != artifact.evidence_database_bytes
    ):
        raise PlaylistAlbumEvidenceJoinError(
            "evidence database does not match the completed artifact"
        )


def _read_direct_evidence(
    database_path: Path,
    artist_credits: dict[str, tuple[ReleaseGroupCreditedArtistEvidence, ...]],
    release_group_ids: tuple[str, ...],
) -> dict[str, tuple[DirectArtistGenreEvidence, ...]]:
    """Read direct artist facts only for artists reached by exact credit records."""
    artist_ids = tuple(
        sorted(
            {
                credit.artist_mbid
                for release_group_id in release_group_ids
                for credit in artist_credits.get(release_group_id, ())
            }
        )
    )
    if not artist_ids:
        return {}
    with closing(sqlite3.connect(f"file:{database_path}?mode=ro", uri=True)) as database:
        try:
            artist_placeholders = ",".join("?" for _ in artist_ids)
            direct_query = f"""SELECT artist_id, genre_id, facet, evidence_ref
                                FROM direct_anchor
                               WHERE artist_id IN ({artist_placeholders})
                               ORDER BY artist_id, genre_id, facet, evidence_ref"""  # noqa: S608
            direct_rows = database.execute(direct_query, artist_ids).fetchall()
        except sqlite3.DatabaseError as error:
            raise PlaylistAlbumEvidenceJoinError(
                "evidence database lacks direct artist evidence"
            ) from error
    direct_groups: dict[str, list[tuple[str, EvidenceFacet, str]]] = defaultdict(list)
    for artist_id, seed_id, facet, evidence_ref in direct_rows:
        direct_groups[str(artist_id)].append((str(seed_id), _facet(str(facet)), str(evidence_ref)))
    return {
        artist_id: tuple(
            DirectArtistGenreEvidence(
                artist_mbid=artist_id,
                seed_id=seed_id,
                facets=tuple(sorted({row[1] for row in rows if row[0] == seed_id})),
                evidence_references=tuple(sorted({row[2] for row in rows if row[0] == seed_id})),
            )
            for seed_id in sorted({row[0] for row in rows})
        )
        for artist_id, rows in direct_groups.items()
    }


def _facet(value: str) -> EvidenceFacet:
    """Parse the closed facet set retained by the completed evidence schema."""
    match value:
        case "musicbrainz_genre" | "musicbrainz_tag":
            return value
        case _:
            raise PlaylistAlbumEvidenceJoinError("evidence database has an unknown facet")


def _context_for_overlap(
    overlap: PlaylistReleaseGroupOverlap,
    artist_credits: dict[str, tuple[ReleaseGroupCreditedArtistEvidence, ...]],
    direct: dict[str, tuple[DirectArtistGenreEvidence, ...]],
) -> PlaylistAlbumEvidenceContext:
    release_group_id = str(overlap.identity.release_group_mbid)
    credited_artists = artist_credits.get(release_group_id, ())
    direct_evidence = tuple(
        item
        for artist_mbid in sorted({artist.artist_mbid for artist in credited_artists})
        for item in direct.get(artist_mbid, ())
    )
    return PlaylistAlbumEvidenceContext(
        release_group_mbid=release_group_id,
        playlist_occurrences=overlap.playlist_occurrences,
        native_release_group_evidence=(overlap.native_evidence,),
        native_proper_genre_status=(
            "present" if overlap.native_evidence.proper_genres else "no_native_proper_genre"
        ),
        credited_artists=credited_artists,
        direct_anchor_artist_seed_evidence=direct_evidence,
    )


def read_exact_release_group_artist_credits(  # noqa: C901
    archive_path: Path, overlaps: tuple[PlaylistReleaseGroupOverlap, ...]
) -> dict[str, tuple[ReleaseGroupCreditedArtistEvidence, ...]]:
    """Extract credits only when a local raw record replays the overlap receipt exactly."""
    expected = {
        str(overlap.identity.release_group_mbid): overlap.native_evidence.record_content_sha256
        for overlap in overlaps
    }
    if len(expected) > _MAX_RELEASE_GROUPS:
        raise PlaylistAlbumEvidenceJoinError("release-group query exceeds the local bound")
    target_bytes = tuple(release_group_id.encode() for release_group_id in expected)
    found: dict[str, tuple[ReleaseGroupCreditedArtistEvidence, ...]] = {}
    limits = SourceLimits(
        max_archive_bytes=archive_path.stat().st_size, max_record_bytes=2 * 1024**2
    )
    for raw in _iter_raw_archive(archive_path, limits, member_name="release-group"):
        if raw.payload is None:
            continue
        if not any(release_group_id in raw.payload for release_group_id in target_bytes):
            continue
        try:
            decoded = json.loads(raw.payload)
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
        if not isinstance(decoded, dict):
            continue
        raw_id = decoded.get("id")
        if not isinstance(raw_id, str) or raw_id not in expected:
            continue
        if raw_id in found:
            raise PlaylistAlbumEvidenceJoinError("release-group archive repeats an exact target")
        if raw.sha256 != expected[raw_id]:
            raise PlaylistAlbumEvidenceJoinError(
                "artist-credit record differs from overlap receipt"
            )
        try:
            group = MusicBrainzReleaseGroup.model_validate_json(raw.payload)
        except ValueError as error:
            raise PlaylistAlbumEvidenceJoinError(
                "artist-credit target record is malformed"
            ) from error
        found[raw_id] = tuple(
            ReleaseGroupCreditedArtistEvidence(
                artist_mbid=str(credit.artist.id),
                artist_name=credit.artist.name,
                credited_name=credit.name,
                joinphrase=credit.joinphrase,
                credit_position=position,
                record_content_sha256=raw.sha256,
            )
            for position, credit in enumerate(group.artist_credit)
        )
    missing = set(expected) - set(found)
    if missing:
        raise PlaylistAlbumEvidenceJoinError(
            "artist-credit archive lacks an exact target release group"
        )
    return found
